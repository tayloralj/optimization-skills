#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

# Read-only snapshot of a JVM's native memory picture. Uses only /proc, cgroup
# files, and non-mutating jcmd diagnostics (no GC, no heap dump, no NMT
# baseline, no command line or system properties). Run twice and compare with
# nmt-compare.py.
usage() {
  printf 'Usage: %s PID NEW_OUTPUT_DIR\n' "${0##*/}" >&2
  printf 'Example: %s 1234 ./nm-$(date -u +%%Y%%m%%dT%%H%%M%%SZ)\n' "${0##*/}" >&2
}
if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# -eq 2 ]] || { usage; exit 2; }
pid=$1
output_dir=$2
[[ "$pid" =~ ^[1-9][0-9]*$ ]] || { printf 'PID must be a positive integer.\n' >&2; exit 2; }
[[ -n "$output_dir" && ! -e "$output_dir" && ! -L "$output_dir" ]] || {
  printf 'NEW_OUTPUT_DIR must not already exist.\n' >&2; exit 2;
}
command -v jcmd >/dev/null 2>&1 || { printf 'jcmd not found; use the JDK matching the target.\n' >&2; exit 3; }

proc_root=${PROC_ROOT:-/proc}
target_start_time() {
  local raw rest
  raw=$(<"$proc_root/$pid/stat") || return 1
  rest=${raw##*) }
  # shellcheck disable=SC2086
  set -- $rest
  printf '%s' "${20}"
}
[[ -r "$proc_root/$pid/status" && -r "$proc_root/$pid/stat" ]] || { printf 'Target PID is not visible or readable.\n' >&2; exit 4; }
[[ $(awk '/^Uid:/ {print $2; exit}' "$proc_root/$pid/status") == "$(id -u)" ]] || {
  printf 'Target must be owned by the current user.\n' >&2; exit 4;
}
[[ $(basename "$(readlink "$proc_root/$pid/exe" 2>/dev/null || true)") == java ]] || {
  printf 'Target executable is not a visible Java launcher.\n' >&2; exit 4;
}
start_before=$(target_start_time) || exit 4

parent_dir=$(dirname "$output_dir")
[[ -d "$parent_dir" && ! -L "$parent_dir" ]] || { printf 'Parent directory must exist and not be a symlink.\n' >&2; exit 4; }
mkdir -m 700 -- "$output_dir"

capture() {
  local name=$1; shift
  if "$@" > "$output_dir/$name" 2>&1; then :; else printf 'capture_failed=%s\n' "$name" >> "$output_dir/meta.txt"; fi
}

{
  printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'pid=%s\n' "$pid"
  printf 'target_start_time=%s\n' "$start_before"
  printf 'page_size=%s\n' "$(getconf PAGESIZE 2>/dev/null || printf unknown)"
} > "$output_dir/meta.txt"

grep -E '^(VmPeak|VmSize|VmHWM|VmRSS|RssAnon|RssFile|RssShmem|VmSwap|VmPTE|Threads):' \
  "$proc_root/$pid/status" > "$output_dir/proc-status.txt" || true
[[ -r "$proc_root/$pid/smaps_rollup" ]] && cp -- "$proc_root/$pid/smaps_rollup" "$output_dir/smaps-rollup.txt"

cgroup_rel=$(awk -F: '$1 == "0" {print $3; exit}' "$proc_root/$pid/cgroup" 2>/dev/null || true)
cgroup_dir=${CGROUP_ROOT:-/sys/fs/cgroup}${cgroup_rel}
if [[ -n "$cgroup_rel" && -r "$cgroup_dir/memory.current" ]]; then
  for file in memory.current memory.max memory.high memory.peak memory.swap.current memory.events; do
    [[ -r "$cgroup_dir/$file" ]] && printf '%s=%s\n' "$file" "$(tr '\n' ' ' < "$cgroup_dir/$file")"
  done > "$output_dir/cgroup-memory.txt"
  grep -E '^(anon|file|kernel|kernel_stack|pagetables|sock|shmem|file_mapped) ' "$cgroup_dir/memory.stat" \
    >> "$output_dir/cgroup-memory.txt" 2>/dev/null || true
fi

capture nmt-summary.txt jcmd "$pid" VM.native_memory summary scale=KB
if grep -q 'Native memory tracking is not enabled' "$output_dir/nmt-summary.txt" 2>/dev/null; then
  printf 'nmt=disabled (restart with -XX:NativeMemoryTracking=summary to enable)\n' >> "$output_dir/meta.txt"
fi
capture gc-heap-info.txt jcmd "$pid" GC.heap_info
capture metaspace.txt jcmd "$pid" VM.metaspace
capture codecache.txt jcmd "$pid" Compiler.codecache
if jcmd "$pid" help 2>/dev/null | grep -q 'System.native_heap_info'; then
  capture native-heap-info.xml jcmd "$pid" System.native_heap_info
fi

if ! start_after=$(target_start_time 2>/dev/null); then
  printf 'Target exited during snapshot; discard %s.\n' "$output_dir" >&2; exit 5
fi
[[ "$start_after" == "$start_before" ]] || {
  printf 'Target PID was reused during snapshot; discard %s.\n' "$output_dir" >&2; exit 5;
}
chmod 600 "$output_dir"/*
printf 'snapshot=%s\n' "$output_dir"
