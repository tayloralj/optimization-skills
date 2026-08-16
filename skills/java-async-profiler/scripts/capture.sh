#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

usage() {
  printf 'Usage: %s PID DURATION_SECONDS EVENT OUTPUT\n' "${0##*/}" >&2
  printf 'Example: install -d -m 700 ./profiles && %s 1234 30 ctimer ./profiles/cpu.html\n' "${0##*/}" >&2
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# -eq 4 ]] || { usage; exit 2; }
pid=$1
duration=$2
event=$3
output=$4
asprof_memlimit=${ASPROF_MEMLIMIT_BYTES:-134217728}

[[ "$pid" =~ ^[1-9][0-9]*$ ]] || { printf 'PID must be a positive integer.\n' >&2; exit 2; }
[[ "$duration" =~ ^[1-9][0-9]*$ ]] && (( duration <= 3600 )) || {
  printf 'Duration must be an integer from 1 to 3600 seconds.\n' >&2; exit 2;
}
case "$event" in cpu|ctimer|itimer|wall|alloc|lock) ;; *)
  printf 'Unsupported safe event: %s\n' "$event" >&2
  printf 'Use cpu, ctimer, itimer, wall, alloc, or lock after checking installed support.\n' >&2
  exit 2
esac
[[ "$asprof_memlimit" =~ ^[1-9][0-9]*$ ]] && (( asprof_memlimit <= 2147483648 )) || {
  printf 'ASPROF_MEMLIMIT_BYTES must be 1 to 2147483648.\n' >&2; exit 2;
}
case "$output" in *.html|*.jfr|*.collapsed|*.txt) ;; *)
  printf 'Output must end in .html, .jfr, .collapsed, or .txt.\n' >&2; exit 2
esac
[[ ! -e "$output" && ! -L "$output" ]] || { printf 'Output already exists or is a symlink; refusing overwrite.\n' >&2; exit 4; }

if command -v asprof >/dev/null 2>&1; then
  asprof_bin=$(command -v asprof)
elif [[ -n "${ASYNC_PROFILER_HOME:-}" && -x "${ASYNC_PROFILER_HOME}/bin/asprof" ]]; then
  asprof_bin=${ASYNC_PROFILER_HOME}/bin/asprof
else
  printf 'asprof not found. Install a pinned, verified async-profiler release first.\n' >&2
  exit 3
fi
"$asprof_bin" --version >/dev/null

output_dir=$(dirname "$output")
[[ -d "$output_dir" && ! -L "$output_dir" ]] || {
  printf 'Create a real output directory first, preferably with mode 0700.\n' >&2; exit 4;
}
output_dir=$(cd "$output_dir" && pwd -P)
[[ $(stat -c %u "$output_dir") -eq $(id -u) ]] || { printf 'Output directory is not owned by this user.\n' >&2; exit 4; }
dir_mode=$(stat -c %a "$output_dir")
(( (8#$dir_mode & 077) == 0 )) || { printf 'Output directory must not grant group/other access.\n' >&2; exit 4; }
[[ -w "$output_dir" ]] || { printf 'Output directory is not writable.\n' >&2; exit 4; }
output=$output_dir/$(basename "$output")
[[ ! -e "$output" && ! -L "$output" ]] || { printf 'Resolved output already exists; refusing overwrite.\n' >&2; exit 4; }

target_start_time() {
  local raw rest
  raw=$(<"/proc/$pid/stat") || return 1
  rest=${raw##*) }
  set -- $rest
  printf '%s' "${20}"
}
[[ -r "/proc/$pid/status" && -r "/proc/$pid/stat" ]] || { printf 'Target PID is not visible or readable.\n' >&2; exit 4; }
target_uid=$(awk '/^Uid:/ {print $2; exit}' "/proc/$pid/status")
[[ "$target_uid" == "$(id -u)" ]] || { printf 'Target must be owned by the current user.\n' >&2; exit 4; }
target_exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
[[ $(basename "$target_exe") == java ]] || { printf 'Target executable is not a visible Java launcher.\n' >&2; exit 4; }
start_time_before=$(target_start_time) || { printf 'Cannot read target start time.\n' >&2; exit 4; }
initial_status=$("$asprof_bin" status "$pid" 2>&1) || {
  printf 'Cannot verify target profiler state; check attach policy and namespaces.\n' >&2; exit 4;
}
[[ "$initial_status" == *"Profiler is not active"* ]] || {
  printf 'A profiler session may already be active; refusing to interfere.\n' >&2; exit 4;
}
[[ $(target_start_time) == "$start_time_before" ]] || { printf 'Target changed during preflight.\n' >&2; exit 4; }

extension=.${output##*.}
stem=${output%.*}
partial=$stem.partial.$$${extension}
[[ ! -e "$partial" && ! -L "$partial" ]] || { printf 'Partial output collision.\n' >&2; exit 4; }
child_pid=
profiling_started=0
cleanup_capture() {
  local current_status
  [[ -z "$child_pid" ]] || kill -TERM "$child_pid" 2>/dev/null || true
  [[ -z "$child_pid" ]] || wait "$child_pid" 2>/dev/null || true
  if (( profiling_started )) && [[ -r "/proc/$pid/stat" ]] && [[ $(target_start_time) == "$start_time_before" ]]; then
    current_status=$("$asprof_bin" status "$pid" 2>&1) || current_status=unavailable
    if [[ "$current_status" != *"Profiler is not active"* ]]; then
      "$asprof_bin" stop "$pid" >/dev/null 2>&1 || true
      current_status=$("$asprof_bin" status "$pid" 2>&1) || current_status=unavailable
      [[ "$current_status" == *"Profiler is not active"* ]] || \
        printf 'WARNING: could not verify that the target profiler stopped.\n' >&2
    fi
  fi
  rm -f -- "$partial"
}
stop_capture() {
  [[ -z "$child_pid" ]] || kill -TERM "$child_pid" 2>/dev/null || true
  [[ -z "$child_pid" ]] || wait "$child_pid" 2>/dev/null || true
  exit 130
}
trap stop_capture HUP INT TERM
trap cleanup_capture EXIT

profiling_started=1
"$asprof_bin" -d "$duration" -e "$event" --memlimit "$asprof_memlimit" -f "$partial" "$pid" &
child_pid=$!
capture_status=0
wait "$child_pid" || capture_status=$?
child_pid=
if (( capture_status != 0 )); then
  printf 'Capture failed. Check target identity, attach policy, PID/mount namespaces, and event support.\n' >&2
  exit 5
fi
profiling_started=0
[[ -s "$partial" ]] || { printf 'Profiler did not create a non-empty artifact.\n' >&2; exit 5; }
if [[ -r "/proc/$pid/stat" ]]; then
  start_time_after=$(target_start_time) || start_time_after=unavailable
  [[ "$start_time_after" == "$start_time_before" ]] || { printf 'Target PID was reused during capture.\n' >&2; exit 5; }
fi
chmod 600 "$partial"
[[ ! -e "$output" && ! -L "$output" ]] || { printf 'Output appeared during capture; refusing overwrite.\n' >&2; exit 5; }
mv -n -- "$partial" "$output"
[[ -s "$output" && ! -e "$partial" ]] || { printf 'Atomic publish failed.\n' >&2; exit 5; }
trap - EXIT HUP INT TERM
printf 'profile=%s\n' "$output"
printf 'target_start_time=%s\n' "$start_time_before"
