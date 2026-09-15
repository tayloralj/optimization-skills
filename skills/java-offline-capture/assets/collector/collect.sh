#!/usr/bin/env bash
set -uo pipefail
export LC_ALL=C
umask 077

# JVM performance evidence collector for hosts without an AI agent.
# Needs bash 4+, coreutils, tar, gzip, sha256sum. Uses the target JVM's own
# jcmd/jfr when present. Read-only except attaching to the chosen JVM
# (JFR recording, jcmd diagnostics). Never uses sudo, never changes the host.
kit_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
kit_version=$(cat "$kit_dir/VERSION" 2>/dev/null || printf unknown)

usage() {
  cat <<EOF
Usage: ${0##*/} --pid PID [options]
       ${0##*/} --list

Collects a bounded, checksummed evidence bundle about one JVM for analysis elsewhere.

Target and time:
  --pid PID               JVM process to examine (run as the same user as the JVM)
  --list                  list visible Java processes and exit
  --duration SECONDS      recording window, 10-3600 (default 120)

What to collect:
  --jfr new|dump|none     new: record the window (default); dump: copy the JVM's existing
                          continuous recording at the end; none: no JFR
  --jfr-settings NAME     default | profile (default profile)
  --thread-dumps N        thread dumps spread over the window, 0-20 (default 0)
  --gc-logs auto|none     auto: copy GC log files named in the JVM's -Xlog config (default)
  --gc-log PATH           copy this log file (and its rotations); repeatable
  --cpus LIST             latency-critical CPUs for the host audit, e.g. 2-5
  --asprof EVENT          also run async-profiler (cpu|ctimer|wall|alloc|lock) if asprof is installed
  --vendor-artifact PATH  copy an existing VTune/uProf/perf/PCM result into vendor/ (repeatable)
  --readiness-smoke-test  let the readiness check run its short perf/JFR self-tests

Privacy and limits:
  --max-mb MB             cap on bundle contents, 16-4096 (default 512)
  --redact-hostname       replace the hostname with a hash in names and metadata
  --keep-command-line     keep JVM/system command lines and properties in JFR (removed by default)
  --out DIR               where to create the bundle (default ./jvmcap-bundles)

Run control:
  --dry-run               print the plan and exit without collecting
  --yes                   do not ask for confirmation
EOF
}

pid=; duration=120; jfr_mode=new; jfr_settings=profile; thread_dumps=0; gc_logs=auto
cpus=; asprof_event=; readiness_smoke=0; max_mb=512; redact_host=0; keep_cmdline=0
out_parent=./jvmcap-bundles; dry_run=0; assume_yes=0; list=0
declare -a extra_gc_logs=()
declare -a vendor_artifacts=()
while (( $# )); do
  case "$1" in
    --pid) pid=${2:-}; shift ;;
    --list) list=1 ;;
    --duration) duration=${2:-}; shift ;;
    --jfr) jfr_mode=${2:-}; shift ;;
    --jfr-settings) jfr_settings=${2:-}; shift ;;
    --thread-dumps) thread_dumps=${2:-}; shift ;;
    --gc-logs) gc_logs=${2:-}; shift ;;
    --gc-log) extra_gc_logs+=("${2:-}"); shift ;;
    --vendor-artifact) vendor_artifacts+=("${2:-}"); shift ;;
    --cpus) cpus=${2:-}; shift ;;
    --asprof) asprof_event=${2:-}; shift ;;
    --readiness-smoke-test) readiness_smoke=1 ;;
    --max-mb) max_mb=${2:-}; shift ;;
    --redact-hostname) redact_host=1 ;;
    --keep-command-line) keep_cmdline=1 ;;
    --out) out_parent=${2:-}; shift ;;
    --dry-run) dry_run=1 ;;
    --yes) assume_yes=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { printf '%s\n' "$1" >&2; exit "${2:-2}"; }

if (( list )); then
  printf '%-8s %-10s %s\n' PID USER EXECUTABLE
  for status in /proc/[0-9]*/status; do
    p=${status#/proc/}; p=${p%/status}
    exe=$(readlink "/proc/$p/exe" 2>/dev/null) || continue
    [[ ${exe##*/} == java ]] || continue
    uid=$(awk '/^Uid:/ {print $2; exit}' "$status" 2>/dev/null)
    printf '%-8s %-10s %s\n' "$p" "$(id -nu "$uid" 2>/dev/null || printf '%s' "$uid")" "$exe"
  done
  exit 0
fi

[[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "--pid is required (use --list to find it)."
[[ "$duration" =~ ^[0-9]+$ ]] && (( duration >= 10 && duration <= 3600 )) || die "--duration must be 10-3600."
[[ "$jfr_mode" =~ ^(new|dump|none)$ ]] || die "--jfr must be new, dump, or none."
[[ "$jfr_settings" =~ ^(default|profile)$ ]] || die "--jfr-settings must be default or profile."
[[ "$thread_dumps" =~ ^[0-9]+$ ]] && (( thread_dumps <= 20 )) || die "--thread-dumps must be 0-20."
[[ "$gc_logs" =~ ^(auto|none)$ ]] || die "--gc-logs must be auto or none."
[[ -z "$cpus" || "$cpus" =~ ^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$ ]] || die "--cpus must look like 2-5,8."
[[ -z "$asprof_event" || "$asprof_event" =~ ^(cpu|ctimer|wall|alloc|lock)$ ]] || die "--asprof must be cpu, ctimer, wall, alloc, or lock."
[[ "$max_mb" =~ ^[0-9]+$ ]] && (( max_mb >= 16 && max_mb <= 4096 )) || die "--max-mb must be 16-4096."
for log in "${extra_gc_logs[@]}"; do [[ -n "$log" && -f "$log" ]] || die "--gc-log file not found: $log"; done
for artifact in "${vendor_artifacts[@]}"; do
  [[ -n "$artifact" && -e "$artifact" && ! -L "$artifact" ]] || die "--vendor-artifact must be an existing non-symlink path: $artifact"
done

# Target checks: same user, visible java, readable identity.
[[ -r "/proc/$pid/status" ]] || die "PID $pid is not visible to this user." 4
target_uid=$(awk '/^Uid:/ {print $2; exit}' "/proc/$pid/status")
target_exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
[[ ${target_exe##*/} == java ]] || die "PID $pid is not a visible Java process (exe: ${target_exe:-unknown})." 4
if [[ "$target_uid" != "$(id -u)" ]]; then
  die "PID $pid belongs to $(id -nu "$target_uid" 2>/dev/null || printf 'uid %s' "$target_uid"). Re-run as that user, for example:
  sudo -u $(id -nu "$target_uid" 2>/dev/null || printf '#%s' "$target_uid") bash $kit_dir/collect.sh --pid $pid ..." 4
fi
start_time() { local raw rest; raw=$(<"/proc/$pid/stat") || return 1; rest=${raw##*) }; read -ra f <<< "$rest"; printf '%s' "${f[19]}"; }
target_start=$(start_time) || die "Cannot read PID $pid identity." 4

# Use the target JVM's own tools when they exist (a JRE-only image has none).
jvm_bin=$(dirname "$target_exe")
jcmd_bin=; jfr_bin=
[[ -x "$jvm_bin/jcmd" ]] && jcmd_bin=$jvm_bin/jcmd
[[ -z "$jcmd_bin" ]] && command -v jcmd >/dev/null 2>&1 && jcmd_bin=$(command -v jcmd)
[[ -x "$jvm_bin/jfr" ]] && jfr_bin=$jvm_bin/jfr
[[ -z "$jfr_bin" ]] && command -v jfr >/dev/null 2>&1 && jfr_bin=$(command -v jfr)
export PATH="$jvm_bin:$PATH"
asprof_bin=
if [[ -n "$asprof_event" ]]; then
  if command -v asprof >/dev/null 2>&1; then asprof_bin=$(command -v asprof)
  elif [[ -n "${ASYNC_PROFILER_HOME:-}" && -x "$ASYNC_PROFILER_HOME/bin/asprof" ]]; then asprof_bin=$ASYNC_PROFILER_HOME/bin/asprof
  fi
fi

host=$(uname -n 2>/dev/null || printf unknown)
host_label=$host
if (( redact_host )); then host_label=host-$(printf '%s' "$host" | sha256sum | cut -c1-8); fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
bundle_name=jvmcap-${host_label//[^A-Za-z0-9._-]/_}-$pid-$stamp
max_bytes=$((max_mb * 1024 * 1024))
jfr_max_mb=$(( max_mb / 2 < 256 ? max_mb / 2 : 256 ))

# Plan
printf 'JVM capture plan (kit %s)\n' "$kit_version"
printf '  target      pid=%s user=%s java=%s\n' "$pid" "$(id -nu)" "$target_exe"
printf '  window      %s seconds\n' "$duration"
printf '  jfr         %s' "$jfr_mode"
[[ "$jfr_mode" == new ]] && printf ' (settings=%s, maxsize=%sM)' "$jfr_settings" "$jfr_max_mb"
[[ "$jfr_mode" != none && -z "$jcmd_bin" ]] && printf ' -> SKIPPED: no jcmd next to the target JVM or on PATH'
printf '\n'
printf '  jvm info    %s\n' "$([[ -n "$jcmd_bin" ]] && printf 'jcmd diagnostics (version, flags, heap, metaspace, code cache, log config)' || printf 'skipped (no jcmd)')"
printf '  gc logs     %s%s\n' "$gc_logs" "$( (( ${#extra_gc_logs[@]} )) && printf ' + %s' "${extra_gc_logs[*]}")"
printf '  threads     %s thread dump(s)\n' "$thread_dumps"
printf '  asprof      %s\n' "${asprof_event:-no}$([[ -n "$asprof_event" && -z "$asprof_bin" ]] && printf ' -> SKIPPED: asprof not installed')"
printf '  host        read-only readiness report and jitter audit%s; /proc counters at start and end\n' "${cpus:+ (cpus $cpus)}"
printf '  privacy     %s; hostname %s\n' "$( (( keep_cmdline )) && printf 'command lines KEPT' || printf 'env vars, system properties, command lines, other processes removed from JFR')" "$( (( redact_host )) && printf 'redacted' || printf 'kept')"
printf '  output      %s/%s.tar.gz (contents capped at %s MB)\n' "$out_parent" "$bundle_name" "$max_mb"
printf '  overhead    JFR %s settings typically low single-digit %% CPU; thread dumps pause the JVM briefly\n' "$jfr_settings"
if (( dry_run )); then printf 'dry_run=1: nothing collected.\n'; exit 0; fi
if (( ! assume_yes )); then
  [[ -t 0 ]] || die "Not interactive: re-run with --yes after reviewing the plan (or --dry-run)."
  read -r -p 'Proceed? [y/N] ' answer
  [[ "$answer" =~ ^[Yy]$ ]] || die "Cancelled." 1
fi

# Output location and space
if [[ ! -e "$out_parent" ]]; then
  mkdir -p -- "$out_parent" || die "Cannot create $out_parent." 4
  chmod 700 -- "$out_parent"
fi
[[ -d "$out_parent" && ! -L "$out_parent" ]] || die "--out must be a directory, not a symlink." 4
out_parent=$(cd "$out_parent" && pwd -P)
[[ $(stat -c %u "$out_parent") -eq $(id -u) ]] || die "$out_parent is not owned by this user." 4
(( (8#$(stat -c %a "$out_parent") & 077) == 0 )) || die "$out_parent is readable by other users; use a private directory (for example a new one: --out ~/jvmcap/bundles)." 4
free_bytes=$(( $(df -Pk "$out_parent" | awk 'NR==2 {print $4}') * 1024 ))
(( free_bytes > 3 * max_bytes )) || die "Need at least $((3 * max_mb)) MB free in $out_parent (bundle, archive, headroom)." 4
bundle=$out_parent/$bundle_name
mkdir -m 700 -- "$bundle" || die "Cannot create $bundle." 4
mkdir -m 700 -- "$bundle/proc-start" "$bundle/proc-end" "$bundle/jvm" "$bundle/host" "$bundle/logs"
if (( ${#vendor_artifacts[@]} )); then mkdir -m 700 -- "$bundle/vendor"; fi

manifest=$bundle/MANIFEST.txt
cmdlog=$bundle/commands.log
man() { printf '%s=%s\n' "$1" "$2" >> "$manifest"; }
step_status() { man "step.$1" "$2"; printf '[%s] %-22s %s\n' "$(date -u +%H:%M:%S)" "$1" "$2"; }
run_step() { # name output_file command...
  local name=$1 file=$2 rc
  shift 2
  printf '%s $' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$cmdlog"; printf ' %q' "$@" >> "$cmdlog"; printf '\n' >> "$cmdlog"
  "$@" > "$file" 2> "$file.stderr"; rc=$?
  [[ -s "$file.stderr" ]] || rm -f -- "$file.stderr"
  if (( rc == 0 )); then step_status "$name" ok; else step_status "$name" "failed(rc=$rc)"; fi
  return "$rc"
}
alive() { [[ "$(start_time 2>/dev/null)" == "$target_start" ]]; }

{
  printf 'bundle_format=1\n'
  printf 'kit_version=%s\n' "$kit_version"
  printf 'bundle=%s\n' "$bundle_name"
  printf 'host=%s\n' "$host_label"
  printf 'kernel=%s\n' "$(uname -r)"
  printf 'pid=%s\n' "$pid"
  printf 'target_start_ticks=%s\n' "$target_start"
  printf 'clk_tck=%s\n' "$(getconf CLK_TCK 2>/dev/null || printf 100)"
  printf 'logical_cpus=%s\n' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf unknown)"
  printf 'duration_s=%s\n' "$duration"
  printf 'jfr_mode=%s\njfr_settings=%s\nthread_dumps=%s\ngc_logs=%s\nasprof_event=%s\n' "$jfr_mode" "$jfr_settings" "$thread_dumps" "$gc_logs" "${asprof_event:-none}"
  printf 'max_mb=%s\nredact_hostname=%s\nkeep_command_line=%s\n' "$max_mb" "$redact_host" "$keep_cmdline"
  printf 'vendor_artifacts=%s\n' "${#vendor_artifacts[@]}"
  printf 'jcmd=%s\njfr_tool=%s\n' "${jcmd_bin:-missing}" "${jfr_bin:-missing}"
} > "$manifest"

declare -a bg_pids=()
interrupted=0
on_interrupt() {
  interrupted=1
  printf 'Interrupted: stopping captures and packaging what was collected.\n' >&2
  local p
  for p in "${bg_pids[@]}"; do kill -TERM "$p" 2>/dev/null || true; done
}
trap on_interrupt INT TERM HUP

snapshot_proc() { # dir
  local dir=$1 f task tid comm stat_raw rest vol invol rundelay
  for f in interrupts softirqs vmstat meminfo stat loadavg diskstats net/snmp net/netstat pressure/cpu pressure/io pressure/memory; do
    [[ -r /proc/$f ]] && cat "/proc/$f" > "$dir/${f//\//_}" 2>/dev/null
  done
  for f in status limits cgroup sched_autogroup; do
    [[ -r /proc/$pid/$f ]] && cat "/proc/$pid/$f" > "$dir/pid_$f" 2>/dev/null
  done
  [[ -r /proc/$pid/smaps_rollup ]] && cat "/proc/$pid/smaps_rollup" > "$dir/pid_smaps_rollup" 2>/dev/null
  printf 'tid\tcomm\tutime\tstime\tvoluntary_ctxt\tnonvoluntary_ctxt\trun_delay_ns\tprocessor\n' > "$dir/threads.tsv"
  for task in /proc/"$pid"/task/*; do
    tid=${task##*/}
    stat_raw=$(<"$task/stat") 2>/dev/null || continue
    comm=$(<"$task/comm") 2>/dev/null || comm="?"
    rest=${stat_raw##*) }
    read -ra fields <<< "$rest"
    vol=$(awk '/^voluntary_ctxt_switches:/ {print $2}' "$task/status" 2>/dev/null)
    invol=$(awk '/^nonvoluntary_ctxt_switches:/ {print $2}' "$task/status" 2>/dev/null)
    rundelay=$(awk '{print $2}' "$task/schedstat" 2>/dev/null)
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$tid" "${comm//$'\t'/ }" "${fields[11]}" "${fields[12]}" \
      "${vol:-}" "${invol:-}" "${rundelay:-}" "${fields[36]}" >> "$dir/threads.tsv"
  done
  date -u +%Y-%m-%dT%H:%M:%S.%NZ > "$dir/timestamp"
  awk '{print $1}' /proc/uptime > "$dir/uptime_s" 2>/dev/null
}

scrub_jfr() { # file
  local file=$1 tmp
  if (( keep_cmdline )); then man "jfr_scrub.${file##*/}" "skipped(--keep-command-line)"; return 0; fi
  if [[ -z "$jfr_bin" ]]; then
    man "jfr_scrub.${file##*/}" "NOT_SCRUBBED(no jfr tool; recording may contain env vars and command lines)"
    printf 'WARNING: no jfr tool; %s was not scrubbed of environment variables and command lines.\n' "${file##*/}" >&2
    return 0
  fi
  tmp=${file%.jfr}.scrubbed.jfr
  if "$jfr_bin" scrub --exclude-events jdk.InitialEnvironmentVariable,jdk.InitialSystemProperty,jdk.InitialSecurityProperty,jdk.SystemProcess,jdk.JVMInformation \
       "$file" "$tmp" >> "$cmdlog" 2>&1; then
    mv -f -- "$tmp" "$file"; chmod 600 "$file"
    man "jfr_scrub.${file##*/}" ok
  else
    rm -f -- "$file" "$tmp"
    man "jfr_scrub.${file##*/}" "failed(recording removed to avoid leaking secrets)"
  fi
}

man started_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'Collecting into %s\n' "$bundle"

# Context before the window
snapshot_proc "$bundle/proc-start"; step_status proc-start ok
if (( readiness_smoke )); then
  run_step readiness "$bundle/host/readiness.txt" bash "$kit_dir/lib/check-profiling-readiness.sh"
else
  run_step readiness "$bundle/host/readiness.txt" bash "$kit_dir/lib/check-profiling-readiness.sh" --no-smoke-test
fi
if [[ -n "$jcmd_bin" ]]; then
  for cmd in VM.version VM.uptime VM.flags GC.heap_info VM.metaspace Compiler.codecache VM.log; do
    args=("$cmd"); [[ "$cmd" == VM.log ]] && args=(VM.log list)
    run_step "jcmd-$cmd" "$bundle/jvm/$cmd.txt" "$jcmd_bin" "$pid" "${args[@]}"
  done
  if "$jcmd_bin" "$pid" VM.native_memory summary scale=KB 2>/dev/null | grep '^Total:' >/dev/null; then
    run_step nmt-start "$bundle/jvm/nmt-start.log" bash "$kit_dir/lib/native-memory-snapshot.sh" "$pid" "$bundle/jvm/nmt-start"
  else
    step_status nmt "skipped(NMT not enabled; add -XX:NativeMemoryTracking=summary at launch)"
  fi
else
  step_status jvm-info "skipped(no jcmd: JRE-only runtime or tools not installed)"
fi

# Background captures for the window
window_start=$SECONDS
if [[ "$jfr_mode" == new && -n "$jcmd_bin" ]]; then
  ( JFR_MAXSIZE=${jfr_max_mb}M bash "$kit_dir/lib/jfr-capture.sh" "$pid" "$duration" "$bundle/jvm/recording.jfr" "$jfr_settings" \
      > "$bundle/jvm/jfr-capture.log" 2>&1; printf '%s' $? > "$bundle/jvm/jfr-capture.rc" ) &
  bg_pids+=($!)
elif [[ "$jfr_mode" != none && -z "$jcmd_bin" ]]; then
  step_status jfr "skipped(no jcmd)"
fi
if [[ -n "$asprof_bin" ]]; then
  ( ASYNC_PROFILER_HOME=$(dirname "$(dirname "$asprof_bin")") bash "$kit_dir/lib/asprof-capture.sh" "$pid" "$duration" "$asprof_event" \
      "$bundle/jvm/asprof-$asprof_event.jfr" > "$bundle/jvm/asprof.log" 2>&1; printf '%s' $? > "$bundle/jvm/asprof.rc" ) &
  bg_pids+=($!)
elif [[ -n "$asprof_event" ]]; then
  step_status asprof "skipped(asprof not installed)"
fi
audit_args=(--pid "$pid" --sample-seconds "$(( duration / 4 < 30 ? duration / 4 : 30 ))")
[[ -n "$cpus" ]] && audit_args+=(--cpus "$cpus")
( bash "$kit_dir/lib/latency-host-audit.sh" "${audit_args[@]}" > "$bundle/host/audit.txt" 2> "$bundle/host/audit.stderr"
  printf '%s' $? > "$bundle/host/audit.rc" ) &
bg_pids+=($!)

# Thread dumps spread across the window, then wait for the window to end
if (( thread_dumps > 0 )) && [[ -n "$jcmd_bin" ]]; then
  gap=$(( duration / (thread_dumps + 1) ))
  for (( i = 1; i <= thread_dumps && ! interrupted; i++ )); do
    while (( SECONDS - window_start < gap * i && ! interrupted )); do sleep 1; done
    alive || break
    printf -v tfile '%s/jvm/thread-dump-%02d.txt' "$bundle" "$i"
    run_step "thread-dump-$i" "$tfile" "$jcmd_bin" "$pid" Thread.print -l
  done
fi
while (( SECONDS - window_start < duration && ! interrupted )); do
  alive || { step_status target "exited during window"; break; }
  sleep 1
done
for p in "${bg_pids[@]}"; do wait "$p" 2>/dev/null; done
[[ -f "$bundle/jvm/jfr-capture.rc" ]] && step_status jfr-new "$([[ $(<"$bundle/jvm/jfr-capture.rc") == 0 ]] && printf ok || printf 'failed(see jvm/jfr-capture.log)')"
[[ -f "$bundle/jvm/asprof.rc" ]] && step_status asprof "$([[ $(<"$bundle/jvm/asprof.rc") == 0 ]] && printf ok || printf 'failed(see jvm/asprof.log)')"
[[ -f "$bundle/host/audit.rc" ]] && step_status host-audit "$([[ $(<"$bundle/host/audit.rc") == 0 ]] && printf ok || printf 'failed')"
rm -f -- "$bundle"/jvm/*.rc "$bundle"/host/*.rc
[[ -s "$bundle/host/audit.stderr" ]] || rm -f -- "$bundle/host/audit.stderr"

# Context after the window
snapshot_proc "$bundle/proc-end"; step_status proc-end ok
if alive && [[ -n "$jcmd_bin" ]]; then
  run_step jcmd-heap-end "$bundle/jvm/GC.heap_info-end.txt" "$jcmd_bin" "$pid" GC.heap_info
  if [[ -d "$bundle/jvm/nmt-start" ]]; then
    run_step nmt-end "$bundle/jvm/nmt-end.log" bash "$kit_dir/lib/native-memory-snapshot.sh" "$pid" "$bundle/jvm/nmt-end"
  fi
  if [[ "$jfr_mode" == dump ]]; then
    run_step jfr-dump "$bundle/jvm/jfr-dump.log" "$jcmd_bin" "$pid" JFR.dump "filename=$bundle/jvm/continuous.jfr"
    [[ -s "$bundle/jvm/continuous.jfr" ]] || step_status jfr-dump "failed(no continuous recording? start the JVM with -XX:StartFlightRecording)"
  fi
fi
for jfr_file in "$bundle"/jvm/*.jfr; do [[ -f "$jfr_file" ]] && scrub_jfr "$jfr_file"; done

# GC logs, newest first, within a quarter of the size budget
gc_budget=$(( max_bytes / 4 ))
declare -a gc_candidates=()
if [[ "$gc_logs" == auto && -f "$bundle/jvm/VM.log.txt" ]]; then
  while read -r path; do
    [[ -n "$path" ]] && gc_candidates+=("$path")
  done < <(grep -oE 'file=[^ ]+' "$bundle/jvm/VM.log.txt" | cut -d= -f2- | sed 's/^"//; s/"$//')
fi
gc_candidates+=("${extra_gc_logs[@]}")
copied=0; copied_bytes=0
for base in "${gc_candidates[@]}"; do
  [[ "$base" == /* ]] || base=/proc/$pid/cwd/$base
  while read -r file; do
    [[ -f "$file" && -r "$file" ]] || continue
    size=$(stat -c %s "$file")
    (( copied_bytes + size <= gc_budget )) || { man "gc_log_skipped.${file##*/}" "size budget"; continue; }
    cp -- "$file" "$bundle/logs/$(printf '%02d' "$copied")-${file##*/}" && copied=$((copied + 1)) && copied_bytes=$((copied_bytes + size))
  done < <(ls -1t -- "$base" "$base".* 2>/dev/null)
done
step_status gc-logs "copied=$copied bytes=$copied_bytes"

# Preserve externally collected vendor sessions without parsing or modifying them.
vendor_copied=0
for artifact in "${vendor_artifacts[@]}"; do
  name=${artifact##*/}
  [[ -n "$name" && ! -e "$bundle/vendor/$name" ]] || die "duplicate vendor artifact name: $name"
  cp -R -- "$artifact" "$bundle/vendor/$name" || die "cannot copy vendor artifact: $artifact"
  if find "$bundle/vendor/$name" -type l -print -quit | grep -q .; then
    die "vendor artifact contains symlinks: $artifact"
  fi
  vendor_copied=$((vendor_copied + 1))
done
step_status vendor-artifacts "copied=$vendor_copied"

# Seal: size check, checksums, archive
content_bytes=$(du -sb "$bundle" | awk '{print $1}')
man content_bytes "$content_bytes"
if (( content_bytes > max_bytes )); then
  man size_warning "contents exceed --max-mb; largest files listed in commands.log"
  du -ab "$bundle" | sort -rn | head -5 >> "$cmdlog"
fi
man finished_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
man interrupted "$interrupted"
man target_alive_at_end "$(alive && printf yes || printf no)"
( cd "$bundle" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
archive=$out_parent/$bundle_name.tar.gz
tar -C "$out_parent" --owner=0 --group=0 --numeric-owner -czf "$archive" "$bundle_name" || die "Archiving failed; the directory $bundle is intact." 5
chmod 600 "$archive"
rm -rf -- "$bundle"
archive_sha=$(sha256sum "$archive" | awk '{print $1}')
printf '\nbundle=%s\nsize_bytes=%s\nsha256=%s\n' "$archive" "$(stat -c %s "$archive")" "$archive_sha"
printf 'Copy it to the analysis machine (scp, kubectl cp, or your file-transfer process) and check the sha256 there.\n'
printf 'The bundle may still contain class names, thread names, file paths, and host details: handle it as confidential.\n'
(( interrupted )) && exit 130
exit 0
