#!/usr/bin/env bash
set -uo pipefail
export LC_ALL=C
umask 077

# JVM performance evidence collector for hosts without an AI agent.
# Needs bash 4.2+, coreutils (including timeout), tar, gzip, sha256sum. Uses the
# target JVM's own jcmd/jfr when present, or the kit's bundled async-profiler
# for attach on JRE-only runtimes. Read-only except attaching to the chosen JVM
# (JFR recording, jcmd diagnostics). Never uses sudo, never changes the host.
kit_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
kit_version=$(cat "$kit_dir/VERSION" 2>/dev/null || printf unknown)
self=$kit_dir/${BASH_SOURCE[0]##*/}

usage() {
  cat <<EOF
Usage: ${0##*/} --pid PID [--pid PID ...] [options]
       ${0##*/} --list
       ${0##*/} --check [--pid PID]

Collects a bounded, checksummed evidence bundle about one JVM (one bundle per
--pid) for analysis elsewhere.

Target and time:
  --pid PID               JVM process to examine (run as the same user as the JVM); repeat for several JVMs
  --list                  list Java processes, including ones this user cannot examine, and exit
  --check                 check this host (and --pid, if given) can run a capture, then exit
  --duration SECONDS      recording window, 10-3600 (default 120)
  --start-at HH:MM        wait until this local time before starting the window
  --trigger SPEC          start the window when a condition holds (repeatable; any one fires):
                            cpu:PCT      process CPU >= PCT % of one core over 5 s
                            rss:MB       resident memory >= MB
                            gcpause:MS   a new GC log line reports a pause >= MS ms
                            file:PATH    PATH exists (for a manual or external signal)
  --max-wait SECONDS      give up waiting for --start-at/--trigger after this long, 60-604800 (default 86400)

What to collect:
  --jfr new|dump|none     new: record the window (default); dump: copy the JVM's existing
                          continuous recording at the end (includes time before a trigger); none: no JFR
  --jfr-settings NAME     default | profile (default profile)
  --thread-dumps N        thread dumps spread over the window, 0-20 (default 0)
  --json-thread-dumps     also write a JSON thread dump (includes virtual threads) with each thread dump
  --class-histogram       class histogram at start and end (jcmd GC.class_histogram -all; no forced GC)
  --gc-logs auto|none     auto: copy GC log files named in the JVM's -Xlog config (default)
  --gc-log PATH           copy this log file (and its rotations); repeatable
  --sample-interval SEC   sample process, thread, host CPU, and pressure every SEC seconds, 0-60 (default 5; 0 off)
  --cpus LIST             latency-critical CPUs for the host audit, e.g. 2-5
  --asprof EVENT          also run async-profiler (cpu|ctimer|wall|alloc|lock), bundled or installed
  --vendor-artifact PATH  copy an existing VTune/uProf/perf/PCM result into vendor/ (repeatable)
  --readiness-smoke-test  let the readiness check run its short perf/JFR self-tests

Privacy, limits, and transfer:
  --max-mb MB             size budget for bundle contents, 16-4096 (default 512)
  --redact-hostname       replace the hostname with a hash in names and metadata
  --keep-command-line     keep JVM/system/child-process command lines and properties in JFR (removed by default)
  --digest                also write a small text summary (NAME.digest.txt) that can be pasted into a ticket
  --split-mb MB           split the archive into parts of at most MB, 1-4096 (for attachment limits)
  --out DIR               where to create the bundle (default ./jvmcap-bundles)

Run control:
  --dry-run               print the plan and exit without collecting
  --yes                   do not ask for confirmation

Environment: JCMD_TIMEOUT_SECONDS (default 30, maximum 60) bounds each JVM diagnostic command.
EOF
}

orig_args=("$@")
duration=120; jfr_mode=new; jfr_settings=profile; thread_dumps=0; gc_logs=auto
cpus=; asprof_event=; readiness_smoke=0; max_mb=512; redact_host=0; keep_cmdline=0
out_parent=./jvmcap-bundles; dry_run=0; assume_yes=0; list=0; check=0
start_at=; max_wait=86400; sample_interval=5; json_dumps=0; histogram=0; digest=0; split_mb=0
declare -a pids=() extra_gc_logs=() vendor_artifacts=() triggers=()
while (( $# )); do
  case "$1" in
    --pid) pids+=("${2:-}"); shift ;;
    --list) list=1 ;;
    --check) check=1 ;;
    --duration) duration=${2:-}; shift ;;
    --start-at) start_at=${2:-}; shift ;;
    --trigger) triggers+=("${2:-}"); shift ;;
    --max-wait) max_wait=${2:-}; shift ;;
    --jfr) jfr_mode=${2:-}; shift ;;
    --jfr-settings) jfr_settings=${2:-}; shift ;;
    --thread-dumps) thread_dumps=${2:-}; shift ;;
    --json-thread-dumps) json_dumps=1 ;;
    --class-histogram) histogram=1 ;;
    --gc-logs) gc_logs=${2:-}; shift ;;
    --gc-log) extra_gc_logs+=("${2:-}"); shift ;;
    --sample-interval) sample_interval=${2:-}; shift ;;
    --vendor-artifact) vendor_artifacts+=("${2:-}"); shift ;;
    --cpus) cpus=${2:-}; shift ;;
    --asprof) asprof_event=${2:-}; shift ;;
    --readiness-smoke-test) readiness_smoke=1 ;;
    --max-mb) max_mb=${2:-}; shift ;;
    --redact-hostname) redact_host=1 ;;
    --keep-command-line) keep_cmdline=1 ;;
    --digest) digest=1 ;;
    --split-mb) split_mb=${2:-}; shift ;;
    --out) out_parent=${2:-}; shift ;;
    --dry-run) dry_run=1 ;;
    --yes) assume_yes=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { printf '%s\n' "$1" >&2; exit "${2:-2}"; }
user_name() { id -nu "$1" 2>/dev/null || printf 'uid %s' "$1"; }

# JDK diagnostics wait at most this long, so a stuck JVM cannot hang the collector.
jcmd_timeout=${JCMD_TIMEOUT_SECONDS:-30}
[[ "$jcmd_timeout" =~ ^[1-9][0-9]*$ ]] && (( jcmd_timeout <= 60 )) || die "JCMD_TIMEOUT_SECONDS must be 1-60."

# async-profiler: the kit's bundled copy (if built with one for this CPU), then an installed one.
asprof_bin=; asprof_note=
bundled_asprof=$kit_dir/async-profiler/bin/asprof
if [[ -x "$bundled_asprof" ]]; then
  if [[ "$(cat "$kit_dir/async-profiler/ARCH" 2>/dev/null)" == "$(uname -m)" ]]; then asprof_bin=$bundled_asprof
  else asprof_note="bundled async-profiler is for $(cat "$kit_dir/async-profiler/ARCH" 2>/dev/null || printf unknown), host is $(uname -m)"
  fi
fi
if [[ -z "$asprof_bin" ]]; then
  if command -v asprof >/dev/null 2>&1; then asprof_bin=$(command -v asprof)
  elif [[ -n "${ASYNC_PROFILER_HOME:-}" && -x "$ASYNC_PROFILER_HOME/bin/asprof" ]]; then asprof_bin=$ASYNC_PROFILER_HOME/bin/asprof
  fi
fi

if (( list )); then
  printf '%-8s %-12s %-10s %s\n' PID USER EXAMINE EXECUTABLE
  me=$(id -u)
  for dir in /proc/[0-9]*; do
    p=${dir#/proc/}
    if exe=$(readlink "$dir/exe" 2>/dev/null); then
      [[ ${exe##*/} == java ]] || continue
    else
      read -r comm 2>/dev/null < "$dir/comm" || continue
      [[ "$comm" == java ]] || continue
      exe=$(tr '\0' '\n' 2>/dev/null < "$dir/cmdline" | head -n 1)
      exe="${exe:-java} (path hidden)"
    fi
    uid=$(awk '/^Uid:/ {print $2; exit}' "$dir/status" 2>/dev/null) || continue
    [[ -n "$uid" ]] || continue
    owner=$(user_name "$uid")
    if [[ "$uid" == "$me" ]]; then access=yes; else access="as $owner"; fi
    printf '%-8s %-12s %-10s %s\n' "$p" "$owner" "$access" "$exe"
  done
  printf 'Run collect.sh as the user in the EXAMINE column (for example: sudo -u USER bash collect.sh ...).\n'
  exit 0
fi

# Several JVMs: run one collector per PID in parallel, each writing its own bundle.
if (( ${#pids[@]} > 1 )); then
  (( ! check )) || die "--check takes at most one --pid."
  declare -a child_args=()
  skip=0
  for arg in "${orig_args[@]}"; do
    if (( skip )); then skip=0; continue; fi
    [[ "$arg" == --pid ]] && { skip=1; continue; }
    [[ "$arg" == --yes || "$arg" == --dry-run ]] && continue
    child_args+=("$arg")
  done
  for p in "${pids[@]}"; do [[ "$p" =~ ^[1-9][0-9]*$ ]] || die "--pid must be a process id: $p"; done
  status=0
  for p in "${pids[@]}"; do
    printf '== PID %s\n' "$p"
    bash "$self" --pid "$p" ${child_args[@]+"${child_args[@]}"} --dry-run || status=$?
  done
  (( status == 0 )) || die "Fix the plan above first." "$status"
  (( dry_run )) && exit 0
  if (( ! assume_yes )); then
    [[ -t 0 ]] || die "Not interactive: re-run with --yes after reviewing the plans (or --dry-run)."
    read -r -p "Collect from ${#pids[@]} JVMs in parallel? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || die "Cancelled." 1
  fi
  declare -a children=()
  for p in "${pids[@]}"; do
    bash "$self" --pid "$p" ${child_args[@]+"${child_args[@]}"} --yes \
      > >(while IFS= read -r line; do printf '[pid %s] %s\n' "$p" "$line"; done) 2>&1 &
    children+=($!)
  done
  trap 'kill -TERM "${children[@]}" 2>/dev/null' INT TERM HUP
  for c in "${children[@]}"; do wait "$c" || { rc=$?; (( rc > status )) && status=$rc; }; done
  exit "$status"
fi
pid=${pids[0]:-}

[[ -z "$pid" && $check == 1 ]] || [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "--pid is required (use --list to find it)."
[[ "$duration" =~ ^[0-9]+$ ]] && (( duration >= 10 && duration <= 3600 )) || die "--duration must be 10-3600."
[[ "$jfr_mode" =~ ^(new|dump|none)$ ]] || die "--jfr must be new, dump, or none."
[[ "$jfr_settings" =~ ^(default|profile)$ ]] || die "--jfr-settings must be default or profile."
[[ "$thread_dumps" =~ ^[0-9]+$ ]] && (( thread_dumps <= 20 )) || die "--thread-dumps must be 0-20."
(( ! json_dumps || thread_dumps > 0 )) || die "--json-thread-dumps needs --thread-dumps N."
[[ "$gc_logs" =~ ^(auto|none)$ ]] || die "--gc-logs must be auto or none."
[[ -z "$cpus" || "$cpus" =~ ^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$ ]] || die "--cpus must look like 2-5,8."
[[ -z "$asprof_event" || "$asprof_event" =~ ^(cpu|ctimer|wall|alloc|lock)$ ]] || die "--asprof must be cpu, ctimer, wall, alloc, or lock."
[[ "$max_mb" =~ ^[0-9]+$ ]] && (( max_mb >= 16 && max_mb <= 4096 )) || die "--max-mb must be 16-4096."
[[ "$sample_interval" =~ ^[0-9]+$ ]] && (( sample_interval <= 60 )) || die "--sample-interval must be 0-60."
[[ "$split_mb" =~ ^[0-9]+$ ]] && (( split_mb <= 4096 )) || die "--split-mb must be 1-4096."
[[ -z "$start_at" || "$start_at" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || die "--start-at must be HH:MM (24-hour, local time)."
[[ "$max_wait" =~ ^[0-9]+$ ]] && (( max_wait >= 60 && max_wait <= 604800 )) || die "--max-wait must be 60-604800."
for t in ${triggers[@]+"${triggers[@]}"}; do
  [[ "$t" =~ ^(cpu|rss|gcpause):[1-9][0-9]{0,6}$ || "$t" =~ ^file:/[^[:cntrl:]]*$ ]] ||
    die "--trigger must be cpu:PCT, rss:MB, gcpause:MS, or file:/ABSOLUTE/PATH (got '$t')."
done
for log in ${extra_gc_logs[@]+"${extra_gc_logs[@]}"}; do [[ -n "$log" && -f "$log" ]] || die "--gc-log file not found: $log"; done
max_bytes=$((max_mb * 1024 * 1024))
vendor_bytes=0
for artifact in ${vendor_artifacts[@]+"${vendor_artifacts[@]}"}; do
  [[ -n "$artifact" && -e "$artifact" && ! -L "$artifact" ]] || die "--vendor-artifact must be an existing non-symlink path: $artifact"
  vendor_bytes=$(( vendor_bytes + $(du -sb -- "$artifact" | awk '{print $1}') ))
done
(( vendor_bytes <= max_bytes / 4 )) ||
  die "Vendor artifacts total $((vendor_bytes / 1048576)) MB, more than a quarter of --max-mb $max_mb; raise --max-mb (up to 4096) or copy them separately."

# ---------------------------------------------------------------------------
# Host-only preflight (--check without --pid) and target identity.
check_line() { printf 'check.%s=%s\n' "$1" "$2"; }
check_failed=0
host_checks() {
  local cmd missing=()
  for cmd in awk sed grep tar gzip sha256sum timeout stat df du find sort xargs date split readlink id getconf tr head tail cut; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  if (( ${#missing[@]} )); then check_line commands "missing(${missing[*]})"; check_failed=1; else check_line commands ok; fi
  if (( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 2) )); then check_line bash "ok($BASH_VERSION)"
  else check_line bash "too-old($BASH_VERSION; need 4.2+)"; check_failed=1; fi
  if [[ "$(du -sb -- "$kit_dir" 2>/dev/null | awk '{print $1}')" =~ ^[0-9]+$ ]]; then check_line du-bytes ok; else check_line du-bytes "unsupported(du -b)"; check_failed=1; fi
  if [[ "$(date -u +%N 2>/dev/null)" =~ ^[0-9]+$ ]]; then check_line date-nanoseconds ok; else check_line date-nanoseconds "unsupported(timestamps less precise)"; fi
  if printf 'b\0a\0' | sort -z >/dev/null 2>&1 && printf 'x\0' | xargs -0 true 2>/dev/null; then check_line nul-separated ok
  else check_line nul-separated "unsupported(sort -z/xargs -0)"; check_failed=1; fi
  if timeout --kill-after=1s 1s true 2>/dev/null; then check_line timeout ok; else check_line timeout "unsupported(--kill-after)"; check_failed=1; fi
  command -v python3 >/dev/null 2>&1 && check_line python3 "ok(optional: GC summary in --digest)" || check_line python3 "missing(optional: GC summary in --digest)"
  if [[ -n "$asprof_bin" ]]; then check_line async-profiler "ok($asprof_bin)"
  else check_line async-profiler "missing(optional${asprof_note:+; $asprof_note})"; fi
}
if [[ -z "$pid" ]]; then
  host_checks
  (( check_failed )) && { printf 'check=failed\n'; exit 3; }
  printf 'check=ok (add --pid PID to check the target JVM too)\n'
  exit 0
fi

[[ -r "/proc/$pid/status" ]] || die "PID $pid is not visible to this user." 4
target_uid=$(awk '/^Uid:/ {print $2; exit}' "/proc/$pid/status")
if [[ "$target_uid" != "$(id -u)" ]]; then
  die "PID $pid belongs to $(user_name "$target_uid"). Re-run as that user, for example:
  sudo -u $(id -nu "$target_uid" 2>/dev/null || printf '#%s' "$target_uid") bash $self --pid $pid ..." 4
fi
target_exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
[[ ${target_exe##*/} == java ]] || die "PID $pid is not a visible Java process (exe: ${target_exe:-unknown})." 4
start_time() { local raw rest; read -r raw < "/proc/$pid/stat" || return 1; rest=${raw##*) }; read -ra f <<< "$rest"; printf '%s' "${f[19]}"; }
target_start=$(start_time) || die "Cannot read PID $pid identity." 4
clk_tck=$(getconf CLK_TCK 2>/dev/null || printf 100)

# A target in another mount namespace (a container seen from a debug container or
# the node) is reached through /proc/PID/root; the JVM writes files on its side.
target_root=; target_ns=same
if [[ "$(readlink "/proc/$pid/ns/mnt" 2>/dev/null)" != "$(readlink /proc/self/ns/mnt 2>/dev/null)" ]]; then
  target_ns=different; target_root=/proc/$pid/root
  [[ -r "$target_root/tmp" ]] || die "PID $pid is in another mount namespace and $target_root is not readable (needs the same user and ptrace access)." 4
fi

# Tools: the target JVM's own jcmd/jfr, then PATH, then async-profiler's built-in attach.
jvm_bin=$(dirname "$target_exe")
find_tool() { # name
  local own=$jvm_bin/$1
  [[ -n "$target_root" ]] && own=$target_root$jvm_bin/$1
  if [[ -z "$target_root" && -x "$own" ]]; then printf '%s' "$own"
  elif command -v "$1" >/dev/null 2>&1; then command -v "$1"
  elif [[ -x "$own" ]]; then printf '%s' "$own"
  fi
}
jcmd_bin=$(find_tool jcmd); jfr_bin=$(find_tool jfr)
jcmd_source=jdk
[[ -n "$jcmd_bin" && -n "$target_root" ]] && jcmd_source=jdk-other-namespace
if [[ -z "$jcmd_bin" && -n "$asprof_bin" ]]; then jcmd_source=async-profiler
elif [[ -z "$jcmd_bin" ]]; then jcmd_source=none
fi
[[ -z "$jfr_bin" ]] || PATH="${jfr_bin%/*}:$PATH"
[[ -z "$jcmd_bin" ]] || PATH="${jcmd_bin%/*}:$PATH"
shim_dir=
make_jcmd_shim() { # jcmd substitute backed by async-profiler's attach, for JRE-only runtimes
  shim_dir=$(mktemp -d "${TMPDIR:-/tmp}/jvmcap-shim.XXXXXX") || die "Cannot create a temporary directory." 4
  cat > "$shim_dir/jcmd" <<EOF
#!/usr/bin/env bash
# jcmd PID COMMAND... through async-profiler (collector shim)
[[ \${1:-} =~ ^[0-9]+\$ ]] || { printf 'shim supports only: jcmd PID COMMAND...\\n' >&2; exit 2; }
out=\$("$asprof_bin" jcmd "\$@" 2>&1); rc=\$?
printf '%s\\n' "\$out" | sed -e '1{/^Connected to remote JVM\$/d;}' -e '2{/^JVM response code = 0\$/d;}'
exit \$rc
EOF
  chmod 700 "$shim_dir/jcmd"
  jcmd_bin=$shim_dir/jcmd
  export PATH="$shim_dir:$PATH"
}
trap '[[ -z "$shim_dir" ]] || rm -rf -- "$shim_dir"' EXIT
jc() { timeout --kill-after=5s "${jcmd_timeout}s" "$jcmd_bin" "$pid" "$@"; }
if [[ "$jcmd_source" == async-profiler ]] && (( check || ! dry_run )); then make_jcmd_shim; fi
export JCMD_TIMEOUT_SECONDS=$jcmd_timeout

target_path() { # path as the JVM names it -> path readable here
  local p=$1
  if [[ "$p" != /* ]]; then printf '/proc/%s/cwd/%s' "$pid" "$p"
  else printf '%s%s' "$target_root" "$p"
  fi
}
jfr_has_view() { # `jfr view` exists from JDK 21; without arguments it lists views and exits non-zero
  local views
  [[ -n "$jfr_bin" ]] || return 1
  views=$("$jfr_bin" view 2>&1)
  [[ "$views" == *hot-methods* ]]
}
gc_log_candidates() { # VM.log list output on stdin -> one log path per line
  grep -oE 'file=[^ ]+' | cut -d= -f2- | sed 's/^"//; s/"$//'
}
cmdline_gc_logs() { # log files named by -Xlog/-Xloggc on the JVM command line (read here, never stored)
  local arg output
  while IFS= read -r -d '' arg; do
    case "$arg" in
      -Xloggc:*) printf '%s\n' "${arg#-Xloggc:}" ;;
      -Xlog:*:*)
        output=${arg#-Xlog:*:}
        output=${output#file=}
        if [[ "$output" == \"* ]]; then output=${output#\"}; output=${output%%\"*}; else output=${output%%:*}; fi
        [[ -z "$output" || "$output" == stdout || "$output" == stderr ]] || printf '%s\n' "$output" ;;
    esac
  done 2>/dev/null < "/proc/$pid/cmdline"
}

if (( check )); then
  host_checks
  check_line target "ok(pid=$pid user=$(id -nu) java=$target_exe mount_ns=$target_ns)"
  if [[ "$jcmd_source" == none ]]; then
    check_line attach "unavailable(no jcmd next to the JVM or on PATH, and no async-profiler; JVM diagnostics and JFR will be skipped)"
  elif version=$(jc VM.version 2>&1); then
    check_line attach "ok(via $jcmd_source: $(printf '%s\n' "$version" | grep -m 1 ' version '))"
    check_line jfr-control "$(jc JFR.check >/dev/null 2>&1 && printf ok || printf unavailable)"
    if jc VM.native_memory summary scale=KB 2>/dev/null | grep -q '^Total:'; then check_line nmt ok
    else check_line nmt "off(optional: -XX:NativeMemoryTracking=summary at launch)"; fi
    logs=$(jc VM.log list 2>/dev/null | gc_log_candidates | tr '\n' ' ')
    check_line gc-log "${logs:-none(optional: -Xlog:gc*,safepoint:file=... at launch)}"
    jc JFR.check 2>/dev/null | grep -q 'name=' && check_line continuous-jfr "running(--jfr dump available)" || check_line continuous-jfr "none(--jfr dump unavailable)"
  else
    check_line attach "failed($(printf '%s' "$version" | tail -n 1); attach may be disabled with -XX:+DisableAttachMechanism)"
    check_failed=1
  fi
  if [[ -z "$jfr_bin" ]]; then check_line jfr-scrub "unavailable(no jfr tool: dumped recordings cannot be scrubbed; new recordings disable sensitive events at source)"
  elif "$jfr_bin" help scrub >/dev/null 2>&1; then check_line jfr-scrub ok
  else check_line jfr-scrub "unsupported(jfr tool older than JDK 19)"; fi
  if jfr_has_view; then check_line jfr-view "ok(used by --digest)"
  else check_line jfr-view "unavailable(--digest omits JFR views)"; fi
  (( check_failed )) && { printf 'check=failed\n'; exit 3; }
  printf 'check=ok\n'
  exit 0
fi

host=$(uname -n 2>/dev/null || printf unknown)
host_label=$host
if (( redact_host )); then host_label=host-$(printf '%s' "$host" | sha256sum | cut -c1-8); fi
jfr_max_mb=$(( max_mb / 2 < 256 ? max_mb / 2 : 256 ))
sensitive_events=jdk.InitialEnvironmentVariable,jdk.InitialSystemProperty,jdk.InitialSecurityProperty,jdk.SystemProcess,jdk.JVMInformation,jdk.ProcessStart
waiting=0; [[ -n "$start_at" ]] || (( ${#triggers[@]} )) && waiting=1

# Plan
printf 'JVM capture plan (kit %s)\n' "$kit_version"
printf '  target      pid=%s user=%s java=%s%s\n' "$pid" "$(id -nu)" "$target_exe" "$([[ $target_ns == different ]] && printf ' (other mount namespace)')"
if (( waiting )); then
  printf '  start       %s%s%s (give up after %s s)\n' "${start_at:+at $start_at $(date +%Z)}" \
    "$([[ -n "$start_at" ]] && (( ${#triggers[@]} )) && printf ', then ')" \
    "$( (( ${#triggers[@]} )) && printf 'when %s' "${triggers[*]}")" "$max_wait"
else
  printf '  start       now\n'
fi
printf '  window      %s seconds\n' "$duration"
printf '  jfr         %s' "$jfr_mode"
[[ "$jfr_mode" == new ]] && printf ' (settings=%s, maxsize=%sM)' "$jfr_settings" "$jfr_max_mb"
[[ "$jfr_mode" != none && "$jcmd_source" == none ]] && printf ' -> SKIPPED: no jcmd next to the target JVM or on PATH, and no async-profiler'
printf '\n'
printf '  jvm info    %s\n' "$([[ "$jcmd_source" != none ]] && printf 'jcmd diagnostics via %s (version, flags, heap, metaspace, code cache, log config), %ss timeout each' "$jcmd_source" "$jcmd_timeout" || printf 'skipped (no jcmd)')"
printf '  gc logs     %s%s\n' "$gc_logs" "$( (( ${#extra_gc_logs[@]} )) && printf ' + %s' "${extra_gc_logs[*]}")"
printf '  threads     %s thread dump(s)%s%s\n' "$thread_dumps" "$( (( json_dumps )) && printf ' + JSON dumps')" "$( (( histogram )) && printf '; class histogram at start and end')"
printf '  sampling    %s\n' "$( (( sample_interval )) && printf 'every %s s' "$sample_interval" || printf off)"
printf '  asprof      %s\n' "${asprof_event:-no}$([[ -n "$asprof_event" && -z "$asprof_bin" ]] && printf ' -> SKIPPED: async-profiler not available%s' "${asprof_note:+ ($asprof_note)}")"
printf '  host        read-only readiness report and jitter audit%s; /proc and cgroup counters at start and end\n' "${cpus:+ (cpus $cpus)}"
printf '  privacy     %s; hostname %s\n' "$( (( keep_cmdline )) && printf 'command lines KEPT' || printf 'env vars, properties, command lines, child and other processes removed from JFR')" "$( (( redact_host )) && printf 'redacted' || printf 'kept')"
printf '  output      %s/jvmcap-%s-%s-<UTC time>.tar.gz (budget %s MB)%s%s\n' "$out_parent" "${host_label//[^A-Za-z0-9._-]/_}" "$pid" "$max_mb" \
  "$( (( digest )) && printf ' + .digest.txt')" "$( (( split_mb )) && printf ', split into %s MB parts' "$split_mb")"
printf '  overhead    JFR %s settings typically low single-digit %% CPU; thread dumps pause the JVM briefly\n' "$jfr_settings"
if (( dry_run )); then printf 'dry_run=1: nothing collected.\n'; exit 0; fi
if (( ! assume_yes )); then
  [[ -t 0 ]] || die "Not interactive: re-run with --yes after reviewing the plan (or --dry-run)."
  read -r -p 'Proceed? [y/N] ' answer
  [[ "$answer" =~ ^[Yy]$ ]] || die "Cancelled." 1
fi

alive() { [[ "$(start_time 2>/dev/null)" == "$target_start" ]]; }

# ---------------------------------------------------------------------------
# Optional wait for a start time or trigger. Nothing is written while waiting.
proc_ticks() { local raw rest; read -r raw < "/proc/$pid/stat" || return 1; rest=${raw##*) }; read -ra f <<< "$rest"; printf '%s' "$(( f[11] + f[12] ))"; }
uptime_cs() { local up; read -r up _ < /proc/uptime; printf '%s' "$(( 10#${up//./} ))"; }
rss_kb() { awk '/^VmRSS:/ {print $2; exit}' "/proc/$pid/status" 2>/dev/null; }
trigger_fired=; waited_s=0
if (( waiting )); then
  trap 'die "Interrupted while waiting; nothing was collected." 130' INT TERM HUP
  wait_started=$SECONDS
  if [[ -n "$start_at" ]]; then
    read -r hh mm ss <<< "$(date +'%H %M %S')"
    delay=$(( ((10#${start_at%:*} * 3600 + 10#${start_at#*:} * 60) - (10#$hh * 3600 + 10#$mm * 60 + 10#$ss) + 86400) % 86400 ))
    (( delay <= max_wait )) || die "--start-at $start_at is $delay s away, beyond --max-wait $max_wait." 6
    printf 'Waiting %s s until %s %s.\n' "$delay" "$start_at" "$(date +%Z)"
    while (( SECONDS - wait_started < delay )); do
      alive || die "PID $pid exited while waiting; nothing was collected." 4
      sleep 1
    done
    trigger_fired="start-at $start_at"
  fi
  if (( ${#triggers[@]} )); then
    declare -a gc_watch=()
    declare -A gc_offset=()
    for t in "${triggers[@]}"; do
      [[ "$t" == gcpause:* ]] || continue
      [[ "$jcmd_source" != none ]] && while read -r path; do [[ -n "$path" ]] && gc_watch+=("$(target_path "$path")"); done \
        < <(jc VM.log list 2>/dev/null | gc_log_candidates)
      gc_watch+=(${extra_gc_logs[@]+"${extra_gc_logs[@]}"})
      (( ${#gc_watch[@]} )) || die "--trigger gcpause needs a GC log: the JVM has none configured (or jcmd is unavailable); pass --gc-log PATH." 2
      for path in "${gc_watch[@]}"; do gc_offset[$path]=$(stat -c %s "$path" 2>/dev/null || printf 0); done
      break
    done
    printf 'Armed: %s (up to %s s).\n' "${triggers[*]}" "$((max_wait - (SECONDS - wait_started)))"
    cpu_prev_ticks=$(proc_ticks); cpu_prev_cs=$(uptime_cs)
    trigger_fired=
    while [[ -z "$trigger_fired" ]]; do
      (( SECONDS - wait_started < max_wait )) || die "No trigger fired within $max_wait s; nothing was collected." 6
      alive || die "PID $pid exited while waiting; nothing was collected." 4
      sleep 1
      for t in "${triggers[@]}"; do
        value=${t#*:}
        case "$t" in
          file:*) [[ -e "$value" ]] && trigger_fired="file $value exists" ;;
          rss:*) rss=$(rss_kb); (( ${rss:-0} >= value * 1024 )) && trigger_fired="RSS $(( rss / 1024 )) MB >= $value MB" ;;
          cpu:*)
            now_cs=$(uptime_cs)
            if (( now_cs - cpu_prev_cs >= 500 )); then
              now_ticks=$(proc_ticks) || continue
              pct=$(( (now_ticks - cpu_prev_ticks) * 10000 / (clk_tck * (now_cs - cpu_prev_cs)) ))
              (( pct >= value )) && trigger_fired="process CPU ${pct}% >= ${value}%"
              cpu_prev_ticks=$now_ticks; cpu_prev_cs=$now_cs
            fi ;;
          gcpause:*)
            for path in "${gc_watch[@]}"; do
              size=$(stat -c %s "$path" 2>/dev/null || printf 0)
              (( size >= ${gc_offset[$path]} )) || gc_offset[$path]=0
              (( size > ${gc_offset[$path]} )) || continue
              hit=$(tail -c +"$(( gc_offset[$path] + 1 ))" "$path" | head -c "$(( size - gc_offset[$path] ))" |
                awk -v t="$value" '/Pause/ && $NF ~ /^[0-9.]+ms$/ { v = $NF; sub(/ms$/, "", v); if (v + 0 >= t) { print; exit } }')
              gc_offset[$path]=$size
              [[ -n "$hit" ]] && { trigger_fired="GC pause >= $value ms: ${hit:0:160}"; break; }
            done ;;
        esac
        [[ -n "$trigger_fired" ]] && break
      done
    done
  fi
  waited_s=$((SECONDS - wait_started))
  printf 'Starting: %s (after %s s).\n' "$trigger_fired" "$waited_s"
  trap - INT TERM HUP
fi

# ---------------------------------------------------------------------------
stamp=$(date -u +%Y%m%dT%H%M%SZ)
bundle_name=jvmcap-${host_label//[^A-Za-z0-9._-]/_}-$pid-$stamp

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
(( ${#vendor_artifacts[@]} )) && mkdir -m 700 -- "$bundle/vendor"
(( sample_interval )) && mkdir -m 700 -- "$bundle/samples"

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
  if (( rc == 0 )); then step_status "$name" ok
  elif (( rc == 124 || rc == 137 )); then step_status "$name" "timeout(${jcmd_timeout}s)"
  else step_status "$name" "failed(rc=$rc)"; fi
  return "$rc"
}
run_jc() { run_step "$1" "$2" timeout --kill-after=5s "${jcmd_timeout}s" "$jcmd_bin" "$pid" "${@:3}"; }
jvm_file() { # bundle path -> path the JVM should write (its own /tmp when in another namespace)
  if [[ -n "$target_root" ]]; then printf '/tmp/jvmcap-%s-%s' "$$" "${1##*/}"; else printf '%s' "$1"; fi
}
fetch_jvm_file() { # bundle path: move a file the JVM wrote in its namespace into the bundle
  [[ -n "$target_root" ]] || return 0
  local src
  src=$target_root$(jvm_file "$1")
  [[ -f "$src" ]] || return 1
  cp -- "$src" "$1" && rm -f -- "$src"
}

{
  printf 'bundle_format=1\n'
  printf 'kit_version=%s\n' "$kit_version"
  printf 'bundle=%s\n' "$bundle_name"
  printf 'host=%s\n' "$host_label"
  printf 'kernel=%s\n' "$(uname -r)"
  printf 'arch=%s\n' "$(uname -m)"
  printf 'pid=%s\n' "$pid"
  printf 'target_start_ticks=%s\n' "$target_start"
  printf 'target_mount_ns=%s\n' "$target_ns"
  printf 'clk_tck=%s\n' "$clk_tck"
  printf 'logical_cpus=%s\n' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf unknown)"
  printf 'duration_s=%s\n' "$duration"
  printf 'start_at=%s\ntriggers=%s\ntrigger_fired=%s\nwaited_s=%s\n' "${start_at:-none}" "${triggers[*]:-none}" "${trigger_fired:-immediate}" "$waited_s"
  printf 'jfr_mode=%s\njfr_settings=%s\nthread_dumps=%s\njson_thread_dumps=%s\nclass_histogram=%s\n' "$jfr_mode" "$jfr_settings" "$thread_dumps" "$json_dumps" "$histogram"
  printf 'gc_logs=%s\nasprof_event=%s\nsample_interval_s=%s\n' "$gc_logs" "${asprof_event:-none}" "$sample_interval"
  printf 'max_mb=%s\nredact_hostname=%s\nkeep_command_line=%s\ndigest=%s\nsplit_mb=%s\n' "$max_mb" "$redact_host" "$keep_cmdline" "$digest" "$split_mb"
  printf 'vendor_artifacts=%s\n' "${#vendor_artifacts[@]}"
  printf 'jcmd=%s\njcmd_source=%s\njcmd_timeout_s=%s\njfr_tool=%s\n' "${jcmd_bin:-missing}" "$jcmd_source" "$jcmd_timeout" "${jfr_bin:-missing}"
} > "$manifest"

declare -a bg_pids=()
interrupted=0
on_interrupt() {
  interrupted=1
  printf 'Interrupted: stopping captures and packaging what was collected.\n' >&2
  local p
  for p in ${bg_pids[@]+"${bg_pids[@]}"}; do kill -TERM "$p" 2>/dev/null || true; done
}
trap on_interrupt INT TERM HUP
bg_step() { # rc_file out_file err_file command... : run in the background, forwarding TERM so helpers clean up
  local rc_file=$1 out=$2 err=$3
  shift 3
  (
    "$@" > "$out" 2> "$err" &
    child=$!
    trap 'kill -TERM "$child" 2>/dev/null' INT TERM HUP
    wait "$child"; rc=$?
    if (( rc > 128 )) && kill -0 "$child" 2>/dev/null; then wait "$child"; rc=$?; fi
    printf '%s' "$rc" > "$rc_file"
  ) &
  bg_pids+=($!)
}

cgroup_dir=
cgroup_rel=$(awk -F: '$1 == "0" {print $3; exit}' "/proc/$pid/cgroup" 2>/dev/null)
[[ -n "$cgroup_rel" && "$cgroup_rel" != *..* && -d "/sys/fs/cgroup$cgroup_rel" ]] && cgroup_dir=/sys/fs/cgroup${cgroup_rel%/}
snapshot_proc() { # dir
  local dir=$1 f task tid comm stat_raw rest vol invol rundelay wchan
  for f in interrupts softirqs vmstat meminfo stat loadavg diskstats net/snmp net/netstat pressure/cpu pressure/io pressure/memory; do
    [[ -r /proc/$f ]] && cat "/proc/$f" > "$dir/${f//\//_}" 2>/dev/null
  done
  for f in status stat io schedstat limits cgroup sched_autogroup smaps_rollup; do
    [[ -r /proc/$pid/$f ]] && cat "/proc/$pid/$f" > "$dir/pid_$f" 2>/dev/null
  done
  if [[ -n "$cgroup_dir" ]]; then
    for f in cpu.stat cpu.max cpu.pressure memory.current memory.max memory.high memory.events memory.pressure io.pressure; do
      [[ -r "$cgroup_dir/$f" ]] && cat "$cgroup_dir/$f" > "$dir/cgroup_$f" 2>/dev/null
    done
  fi
  printf 'tid\tcomm\tutime\tstime\tvoluntary_ctxt\tnonvoluntary_ctxt\trun_delay_ns\tprocessor\tstate\twchan\n' > "$dir/threads.tsv"
  for task in /proc/"$pid"/task/*; do
    tid=${task##*/}
    read -r stat_raw 2>/dev/null < "$task/stat" || continue
    read -r comm 2>/dev/null < "$task/comm" || comm="?"
    rest=${stat_raw##*) }
    read -ra fields <<< "$rest"
    vol=; invol=; rundelay=
    while read -r key value _; do
      case "$key" in voluntary_ctxt_switches:) vol=$value ;; nonvoluntary_ctxt_switches:) invol=$value ;; esac
    done 2>/dev/null < "$task/status"
    read -r _ rundelay _ 2>/dev/null < "$task/schedstat"
    wchan=; read -r wchan 2>/dev/null < "$task/wchan"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$tid" "${comm//$'\t'/ }" "${fields[11]}" "${fields[12]}" \
      "${vol:-}" "${invol:-}" "${rundelay:-}" "${fields[36]}" "${fields[0]}" "${wchan:-}" >> "$dir/threads.tsv"
  done
  date -u +%Y-%m-%dT%H:%M:%S.%NZ > "$dir/timestamp"
  awk '{print $1}' /proc/uptime > "$dir/uptime_s" 2>/dev/null
}

# Time series for the window: host CPU, process CPU and RSS, pressure, cgroup
# throttling, and per-thread CPU (a thread row only when its CPU time changed).
sampler() { # deadline (bash SECONDS)
  local deadline=$1 hfile=$bundle/samples/host.tsv tfile=$bundle/samples/threads.tsv
  local up raw rest rss key value kind line total psi_cpu psi_io psi_mem nr thr task tid ticks comm
  local -a f
  local -A last=()
  printf 'uptime_s\tcpu_user\tcpu_nice\tcpu_system\tcpu_idle\tcpu_iowait\tcpu_irq\tcpu_softirq\tcpu_steal\tproc_utime\tproc_stime\trss_kb\tpsi_cpu_some_us\tpsi_io_some_us\tpsi_memory_some_us\tcg_nr_throttled\tcg_throttled_usec\n' > "$hfile"
  printf 'uptime_s\ttid\tcomm\tcpu_ticks\n' > "$tfile"
  while (( SECONDS < deadline )); do
    read -r up _ < /proc/uptime
    read -r _ c_user c_nice c_system c_idle c_iowait c_irq c_softirq c_steal _ < /proc/stat
    read -r raw 2>/dev/null < "/proc/$pid/stat" || break
    rest=${raw##*) }; read -ra f <<< "$rest"
    rss=
    while read -r key value _; do [[ "$key" == VmRSS: ]] && { rss=$value; break; }; done < "/proc/$pid/status"
    psi_cpu=; psi_io=; psi_mem=
    for kind in cpu io memory; do
      read -r line 2>/dev/null < "/proc/pressure/$kind" || continue
      total=${line##*total=}
      case "$kind" in cpu) psi_cpu=$total ;; io) psi_io=$total ;; memory) psi_mem=$total ;; esac
    done
    nr=; thr=
    if [[ -n "$cgroup_dir" && -r "$cgroup_dir/cpu.stat" ]]; then
      while read -r key value; do
        case "$key" in nr_throttled) nr=$value ;; throttled_usec) thr=$value ;; esac
      done < "$cgroup_dir/cpu.stat"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$up" "$c_user" "$c_nice" "$c_system" "$c_idle" \
      "$c_iowait" "$c_irq" "$c_softirq" "$c_steal" "${f[11]}" "${f[12]}" "$rss" "$psi_cpu" "$psi_io" "$psi_mem" "$nr" "$thr" >> "$hfile"
    for task in /proc/"$pid"/task/*; do
      read -r raw 2>/dev/null < "$task/stat" || continue
      tid=${task##*/}; rest=${raw##*) }; read -ra f <<< "$rest"
      ticks=$(( f[11] + f[12] ))
      [[ "${last[$tid]:-}" == "$ticks" ]] && continue
      last[$tid]=$ticks
      comm=${raw#*(}; comm=${comm%)*}
      printf '%s\t%s\t%s\t%s\n' "$up" "$tid" "${comm//$'\t'/ }" "$ticks" >> "$tfile"
    done
    sleep "$sample_interval"
  done
}

scrub_jfr() { # file
  local file=$1 tmp
  if (( keep_cmdline )); then man "jfr_scrub.${file##*/}" "skipped(--keep-command-line)"; return 0; fi
  if [[ -z "$jfr_bin" ]]; then
    if [[ "${file##*/}" == recording.jfr ]]; then
      man "jfr_scrub.${file##*/}" "source-disabled(no jfr tool; sensitive events were switched off when recording started)"
    else
      man "jfr_scrub.${file##*/}" "NOT_SCRUBBED(no jfr tool; recording may contain env vars and command lines)"
      printf 'WARNING: no jfr tool; %s was not scrubbed of environment variables and command lines.\n' "${file##*/}" >&2
    fi
    return 0
  fi
  tmp=${file%.jfr}.scrubbed.jfr
  if "$jfr_bin" scrub --exclude-events "$sensitive_events" "$file" "$tmp" >> "$cmdlog" 2>&1; then
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
if [[ "$jcmd_source" != none ]] && ! run_jc jcmd-VM.version "$bundle/jvm/VM.version.txt" VM.version; then
  # A JVM that cannot answer VM.version will not answer the rest either; keep the
  # window on time and rely on /proc evidence (thread states and wait channels).
  jcmd_source=none
  man jvm_unresponsive 1
  step_status jvm-info "skipped(JVM did not answer VM.version; /proc evidence only)"
elif [[ "$jcmd_source" != none ]]; then
  for cmd in VM.uptime VM.flags GC.heap_info VM.metaspace Compiler.codecache VM.log; do
    args=("$cmd"); [[ "$cmd" == VM.log ]] && args=(VM.log list)
    run_jc "jcmd-$cmd" "$bundle/jvm/$cmd.txt" "${args[@]}"
  done
  if jc VM.native_memory summary scale=KB 2>/dev/null | grep '^Total:' >/dev/null; then
    run_step nmt-start "$bundle/jvm/nmt-start.log" bash "$kit_dir/lib/native-memory-snapshot.sh" "$pid" "$bundle/jvm/nmt-start"
  else
    step_status nmt "skipped(NMT not enabled; add -XX:NativeMemoryTracking=summary at launch)"
  fi
  (( histogram )) && run_jc class-histogram-start "$bundle/jvm/class-histogram-start.txt" GC.class_histogram -all
else
  step_status jvm-info "skipped(no jcmd: JRE-only runtime or tools not installed)"
fi

# Background captures for the window
window_start=$SECONDS
if [[ "$jfr_mode" == new && "$jcmd_source" != none ]]; then
  jfr_env=(JFR_MAXSIZE="${jfr_max_mb}M")
  (( keep_cmdline )) || jfr_env+=(JFR_DISABLE_EVENTS="$sensitive_events")
  [[ -z "$target_root" ]] || jfr_env+=(JFR_TARGET_TMP=/tmp)
  bg_step "$bundle/jvm/jfr-capture.rc" "$bundle/jvm/jfr-capture.log" "$bundle/jvm/jfr-capture.log" \
    env "${jfr_env[@]}" bash "$kit_dir/lib/jfr-capture.sh" "$pid" "$duration" "$bundle/jvm/recording.jfr" "$jfr_settings"
elif [[ "$jfr_mode" != none && "$jcmd_source" == none ]]; then
  step_status jfr "skipped(no usable jcmd)"
fi
if [[ -n "$asprof_event" && -n "$asprof_bin" ]]; then
  # Without a jfr tool the JFR output (JVM arguments, system properties) cannot be
  # scrubbed, so record plain collapsed stacks instead.
  asprof_ext=jfr
  [[ -n "$jfr_bin" ]] || (( keep_cmdline )) || asprof_ext=collapsed
  bg_step "$bundle/jvm/asprof.rc" "$bundle/jvm/asprof.log" "$bundle/jvm/asprof.log" \
    env ASYNC_PROFILER_HOME="$(dirname "$(dirname "$asprof_bin")")" bash "$kit_dir/lib/asprof-capture.sh" "$pid" "$duration" \
    "$asprof_event" "$bundle/jvm/asprof-$asprof_event.$asprof_ext"
elif [[ -n "$asprof_event" ]]; then
  step_status asprof "skipped(async-profiler not available)"
fi
audit_args=(--pid "$pid")
[[ -n "$cpus" ]] && audit_args+=(--cpus "$cpus" --sample-seconds "$(( duration / 4 < 30 ? duration / 4 : 30 ))")
bg_step "$bundle/host/audit.rc" "$bundle/host/audit.txt" "$bundle/host/audit.stderr" \
  bash "$kit_dir/lib/latency-host-audit.sh" "${audit_args[@]}"
if (( sample_interval )); then
  ( trap - INT TERM HUP; sampler "$((window_start + duration))" ) &
  bg_pids+=($!)
fi

# Thread dumps spread across the window, then wait for the window to end
if (( thread_dumps > 0 )) && [[ "$jcmd_source" != none ]]; then
  gap=$(( duration / (thread_dumps + 1) ))
  for (( i = 1; i <= thread_dumps && ! interrupted; i++ )); do
    while (( SECONDS - window_start < gap * i && ! interrupted )); do sleep 1; done
    alive || break
    printf -v tfile '%s/jvm/thread-dump-%02d.txt' "$bundle" "$i"
    run_jc "thread-dump-$i" "$tfile" Thread.print -l
    if (( json_dumps )); then
      jfile=${tfile%.txt}.json
      run_jc "thread-dump-json-$i" "$bundle/jvm/.thread-dump-json-$i.log" Thread.dump_to_file -format=json "$(jvm_file "$jfile")" &&
        { fetch_jvm_file "$jfile" || step_status "thread-dump-json-$i" "failed(file not readable from the target)"; }
      rm -f -- "$bundle/jvm/.thread-dump-json-$i.log"
    fi
  done
fi
while (( SECONDS - window_start < duration && ! interrupted )); do
  alive || { step_status target "exited during window"; break; }
  sleep 1
done
for p in "${bg_pids[@]}"; do wait "$p" 2>/dev/null; done
(( sample_interval )) && step_status samples "$([[ -s "$bundle/samples/host.tsv" ]] && printf 'rows=%s' "$(( $(wc -l < "$bundle/samples/host.tsv") - 1 ))" || printf failed)"
[[ -f "$bundle/jvm/jfr-capture.rc" ]] && step_status jfr-new "$([[ $(<"$bundle/jvm/jfr-capture.rc") == 0 ]] && printf ok || printf 'failed(see jvm/jfr-capture.log)')"
[[ -f "$bundle/jvm/asprof.rc" ]] && step_status asprof "$([[ $(<"$bundle/jvm/asprof.rc") == 0 ]] && printf ok || printf 'failed(see jvm/asprof.log)')"
[[ -f "$bundle/host/audit.rc" ]] && step_status host-audit "$([[ $(<"$bundle/host/audit.rc") == 0 ]] && printf ok || printf 'failed(see host/audit.stderr)')"
rm -f -- "$bundle"/jvm/*.rc "$bundle"/host/*.rc
[[ -s "$bundle/host/audit.stderr" ]] || rm -f -- "$bundle/host/audit.stderr"

# Context after the window
snapshot_proc "$bundle/proc-end"; step_status proc-end ok
if alive && [[ "$jcmd_source" != none ]]; then
  run_jc jcmd-heap-end "$bundle/jvm/GC.heap_info-end.txt" GC.heap_info
  if [[ -d "$bundle/jvm/nmt-start" ]]; then
    run_step nmt-end "$bundle/jvm/nmt-end.log" bash "$kit_dir/lib/native-memory-snapshot.sh" "$pid" "$bundle/jvm/nmt-end"
  fi
  (( histogram )) && run_jc class-histogram-end "$bundle/jvm/class-histogram-end.txt" GC.class_histogram -all
  if [[ "$jfr_mode" == dump ]]; then
    cont=$bundle/jvm/continuous.jfr
    if run_jc jfr-dump "$bundle/jvm/jfr-dump.log" JFR.dump "filename=$(jvm_file "$cont")"; then
      fetch_jvm_file "$cont" || true
    fi
    [[ -s "$cont" ]] || step_status jfr-dump "failed(no continuous recording? start the JVM with -XX:StartFlightRecording)"
  fi
fi
for jfr_file in "$bundle"/jvm/*.jfr; do [[ -f "$jfr_file" ]] && scrub_jfr "$jfr_file"; done

# GC logs, newest first, within a quarter of the size budget
gc_budget=$(( max_bytes / 4 ))
declare -a gc_candidates=()
if [[ "$gc_logs" == auto ]]; then
  if [[ -s "$bundle/jvm/VM.log.txt" ]]; then
    logs=$(gc_log_candidates < "$bundle/jvm/VM.log.txt")
  else
    logs=$(cmdline_gc_logs)
  fi
  while read -r path; do
    [[ -n "$path" ]] && gc_candidates+=("$(target_path "$path")")
  done <<< "$logs"
fi
gc_candidates+=(${extra_gc_logs[@]+"${extra_gc_logs[@]}"})
copied=0; copied_bytes=0
for base in ${gc_candidates[@]+"${gc_candidates[@]}"}; do
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
for artifact in ${vendor_artifacts[@]+"${vendor_artifacts[@]}"}; do
  name=${artifact##*/}
  if [[ -z "$name" || -e "$bundle/vendor/$name" ]]; then
    step_status "vendor-$name" "failed(duplicate name)"; continue
  fi
  if ! cp -R -- "$artifact" "$bundle/vendor/$name"; then
    rm -rf -- "${bundle:?}/vendor/$name"; step_status "vendor-$name" "failed(copy)"; continue
  fi
  if find "$bundle/vendor/$name" -type l -print -quit | grep -q .; then
    rm -rf -- "${bundle:?}/vendor/$name"; step_status "vendor-$name" "failed(contains symlinks)"; continue
  fi
  vendor_copied=$((vendor_copied + 1))
done
(( ${#vendor_artifacts[@]} )) && step_status vendor-artifacts "copied=$vendor_copied"

man finished_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
man interrupted "$interrupted"
man target_alive_at_end "$(alive && printf yes || printf no)"

# A short text summary, readable without any tools, for channels that only take text.
write_digest() {
  local d=$bundle/DIGEST.txt limit=262144 elapsed view f
  elapsed=$(awk 'NR == FNR {s = $1; next} {print $1 - s}' "$bundle/proc-start/uptime_s" "$bundle/proc-end/uptime_s" 2>/dev/null)
  section() { printf '\n## %s\n\n' "$1"; }
  {
    printf '# JVM capture digest: %s (kit %s)\n\n' "$bundle_name" "$kit_version"
    grep -E '^(host|kernel|arch|pid|logical_cpus|duration_s|started_utc|finished_utc|trigger_fired|jcmd_source|target_mount_ns|interrupted|target_alive_at_end)=' "$manifest"
    grep -E '^step\.' "$manifest" | grep -vE '=(ok|copied=.*|rows=.*)$' | sed 's/^/not_ok /'
    grep -m 1 ' version ' "$bundle/jvm/VM.version.txt" 2>/dev/null
    section "Threads by CPU over ${elapsed:-?} s (top 15)"
    printf 'cpu_pct\trun_delay_ms\tthread (tid)\n'
    awk -F'\t' -v clk="$clk_tck" -v el="${elapsed:-0}" 'FNR == 1 {next}
      NR == FNR {s[$1] = $3 + $4; d[$1] = $7; next}
      ($1 in s) && el > 0 {printf "%.1f\t%.1f\t%s (%s)\n", ($3 + $4 - s[$1]) * 100 / clk / el, ($7 - d[$1]) / 1e6, $2, $1}' \
      "$bundle/proc-start/threads.tsv" "$bundle/proc-end/threads.tsv" | sort -t$'\t' -k1,1 -rn | head -n 15
    section "Host CPU over the window"
    awk '$1 == "cpu" {n++; for (i = 2; i <= 9; i++) v[n, i] = $i}
      END {for (i = 2; i <= 9; i++) {d[i] = v[2, i] - v[1, i]; t += d[i]}
           if (t > 0) printf "user %.1f%% system %.1f%% iowait %.1f%% irq+softirq %.1f%% steal %.1f%% idle %.1f%%\n",
             (d[2] + d[3]) * 100 / t, d[4] * 100 / t, d[6] * 100 / t, (d[7] + d[8]) * 100 / t, d[9] * 100 / t, d[5] * 100 / t}' \
      "$bundle/proc-start/stat" "$bundle/proc-end/stat" 2>/dev/null
    for f in cpu io memory; do
      [[ -f "$bundle/proc-start/pressure_$f" ]] || continue
      awk -v k="$f" -v el="${elapsed:-0}" '/^some/ {sub(/.*total=/, ""); v[++n] = $1}
        END {if (n == 2 && el > 0) printf "pressure %s some %.2f%% of the window\n", k, (v[2] - v[1]) / 1e4 / el}' \
        "$bundle/proc-start/pressure_$f" "$bundle/proc-end/pressure_$f"
    done
    awk '/^nr_throttled|^throttled_usec/ {v[$1, ++n[$1]] = $2}
      END {if (n["nr_throttled"] == 2) printf "cgroup throttled %d times, %.1f ms during the window\n",
             v["nr_throttled", 2] - v["nr_throttled", 1], (v["throttled_usec", 2] - v["throttled_usec", 1]) / 1000}' \
      "$bundle/proc-start/cgroup_cpu.stat" "$bundle/proc-end/cgroup_cpu.stat" 2>/dev/null
    if [[ -s "$bundle/samples/host.tsv" ]]; then
      section "Busiest sample intervals (process CPU % of one core)"
      awk -F'\t' -v clk="$clk_tck" 'NR == 1 {next}
        {tot = $2 + $3 + $4 + $5 + $6 + $7 + $8 + $9}
        NR > 2 && $1 > pu && tot > ptot {cpu = ($10 + $11 - pt) * 100 / clk / ($1 - pu)
          printf "%.1f\t%.1f-%.1f s host uptime: process %.0f%%, host steal %.1f%%, iowait %.1f%%\n", cpu, pu, $1, cpu,
            ($9 - ps) * 100 / (tot - ptot), ($6 - pw) * 100 / (tot - ptot)}
        {pu = $1; pt = $10 + $11; ps = $9; pw = $6; ptot = tot}' "$bundle/samples/host.tsv" |
        sort -t$'\t' -k1,1 -rn | head -n 5 | cut -f2-
    fi
    section "Host audit findings"
    grep '^finding=' "$bundle/host/audit.txt" 2>/dev/null || printf 'none recorded\n'
    section "GC during the window"
    if compgen -G "$bundle/logs/*" >/dev/null; then
      if command -v python3 >/dev/null 2>&1 && [[ -n "$elapsed" ]]; then
        local jvm_up
        jvm_up=$(awk -v s="$target_start" -v c="$clk_tck" '{printf "%.3f", $1 - s / c}' "$bundle/proc-start/uptime_s")
        timeout 60s python3 "$kit_dir/lib/gc-log-summary.py" --from-uptime "$jvm_up" \
          --to-uptime "$(awk -v a="$jvm_up" -v e="$elapsed" 'BEGIN {printf "%.3f", a + e}')" "$bundle"/logs/* 2>&1 |
          sed "s|$bundle/||g" | head -n 40
      else
        grep -h 'Pause' "$bundle"/logs/* | tail -n 20
      fi
    else
      printf 'no GC logs\n'
    fi
    for f in "$bundle"/jvm/*.jfr; do
      [[ -f "$f" ]] && jfr_has_view || continue
      for view in hot-methods allocation-by-site contention-by-site gc-pauses thread-cpu-load; do
        section "JFR ${f##*/}: $view"
        timeout 60s "$jfr_bin" view --width 140 "$view" "$f" 2>&1 | head -n 25
      done
    done
    for f in "$bundle"/jvm/thread-dump-*.txt; do
      [[ -f "$f" ]] || continue
      section "Thread dump ${f##*/}"
      grep -o 'java.lang.Thread.State: [A-Z_]*' "$f" | sort | uniq -c
      grep -A 12 -E '^Found (one|[0-9]+) Java-level deadlock' "$f"
    done
  } > "$d.tmp" 2>/dev/null
  if (( $(stat -c %s "$d.tmp") > limit )); then
    head -c "$limit" "$d.tmp" > "$d"; printf '\n[digest truncated at %s bytes]\n' "$limit" >> "$d"
  else
    mv -- "$d.tmp" "$d"
  fi
  rm -f -- "$d.tmp"
  chmod 600 "$d"
}
(( digest )) && { write_digest; step_status digest "bytes=$(stat -c %s "$bundle/DIGEST.txt")"; }

# Seal: size check, checksums, archive
content_bytes=$(du -sb "$bundle" | awk '{print $1}')
man content_bytes "$content_bytes"
if (( content_bytes > max_bytes )); then
  man size_warning "contents exceed --max-mb; largest files listed in commands.log"
  du -ab "$bundle" | sort -rn | head -5 >> "$cmdlog"
  printf 'WARNING: bundle contents are %s MB, over the %s MB budget.\n' "$((content_bytes / 1048576))" "$max_mb" >&2
fi
( cd "$bundle" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
archive=$out_parent/$bundle_name.tar.gz
tar -C "$out_parent" --owner=0 --group=0 --numeric-owner -czf "$archive" "$bundle_name" || die "Archiving failed; the directory $bundle is intact." 5
chmod 600 "$archive"
if (( digest )); then install -m 600 "$bundle/DIGEST.txt" "$out_parent/$bundle_name.digest.txt"; fi
rm -rf -- "$bundle"
archive_sha=$(sha256sum "$archive" | awk '{print $1}')
archive_bytes=$(stat -c %s "$archive")
printf '\nbundle=%s\nsize_bytes=%s\nsha256=%s\n' "$archive" "$archive_bytes" "$archive_sha"
(( digest )) && printf 'digest=%s (text; paste or attach it if the bundle cannot be sent quickly)\n' "$out_parent/$bundle_name.digest.txt"
if (( split_mb && archive_bytes > split_mb * 1048576 )); then
  split -b "${split_mb}M" -d -a 3 -- "$archive" "$archive.part-" || die "Splitting failed; $archive is intact." 5
  chmod 600 "$archive".part-*
  rm -f -- "$archive"
  printf 'parts:\n'
  for part in "$archive".part-*; do printf '  %s  %s\n' "$(sha256sum "$part" | awk '{print $1}')" "${part##*/}"; done
  printf 'Send every part. Rejoin with: cat %s.part-* > %s   (then check sha256 %s)\n' "${archive##*/}" "${archive##*/}" "$archive_sha"
else
  printf 'Copy it to the analysis machine (scp, kubectl cp, or your file-transfer process) and check the sha256 there.\n'
fi
printf 'The bundle may still contain class names, thread names, file paths, and host details: handle it as confidential.\n'
(( interrupted )) && exit 130
exit 0
