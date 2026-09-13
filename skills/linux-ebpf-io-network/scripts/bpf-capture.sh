#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

# Bounded wrapper around maintained BCC tools for JVM latency questions. It
# resolves the tool, builds a fixed argument list, enforces a duration and a
# new private output file, and checks Java symbol prerequisites. It never calls
# sudo: print the command with --dry-run and let the operator run it as root
# (or with CAP_BPF+CAP_PERFMON where the tool supports that).
usage() {
  cat <<EOF
Usage: ${0##*/} [--dry-run] [--pid PID] [--threshold N] TOOL DURATION_SECONDS OUTPUT

TOOL (PID scope)            question answered
  offcputime  (pid)         where do threads block? folded off-CPU stacks
  profile     (pid)         where is CPU spent? folded on-CPU stacks, 49 Hz
  runqlat     (pid)         how long do runnable threads wait for a CPU?
  runqslower  (pid)         which wake-ups waited longer than --threshold us (default 1000)?
  cpudist     (pid)         off-CPU interval distribution
  syscount    (pid)         which syscalls dominate count and latency?
  fileslower  (pid)         which file reads/writes exceed --threshold ms (default 1)?
  biolatency  (system)      block device I/O latency per disk
  hardirqs    (system)      hard IRQ time distribution
  softirqs    (system)      soft IRQ time distribution
  tcpretrans  (system)      TCP retransmissions and tail-loss probes

DURATION 1-600 seconds. OUTPUT must not exist; its directory must be private.
EOF
}

dry_run=0; pid=; threshold=
while (( $# )); do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --pid) pid=${2:-}; shift ;;
    --threshold) threshold=${2:-}; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) usage >&2; exit 2 ;;
    *) break ;;
  esac
  shift
done
[[ $# -eq 3 ]] || { usage >&2; exit 2; }
tool=$1; duration=$2; output=$3

[[ "$duration" =~ ^[1-9][0-9]*$ ]] && (( duration <= 600 )) || { printf 'DURATION must be 1-600.\n' >&2; exit 2; }
[[ -z "$pid" || "$pid" =~ ^[1-9][0-9]*$ ]] || { printf 'Invalid --pid.\n' >&2; exit 2; }
[[ -z "$threshold" || "$threshold" =~ ^[1-9][0-9]{0,6}$ ]] || { printf 'Invalid --threshold.\n' >&2; exit 2; }

pid_scoped=1
case "$tool" in
  offcputime|profile|runqlat|runqslower|cpudist|syscount|fileslower) ;;
  biolatency|hardirqs|softirqs|tcpretrans) pid_scoped=0 ;;
  *) printf 'Unsupported tool: %s\n' "$tool" >&2; usage >&2; exit 2 ;;
esac
if (( pid_scoped )); then
  [[ -n "$pid" ]] || { printf '%s needs --pid (system-wide capture is deliberately not offered here).\n' "$tool" >&2; exit 2; }
else
  [[ -z "$pid" ]] || { printf '%s is system-wide; omit --pid.\n' "$tool" >&2; exit 2; }
fi

resolve_tool() {
  local name=$1 candidate
  for candidate in "$name-bpfcc" "/usr/sbin/$name-bpfcc" "/usr/share/bcc/tools/$name" "$name"; do
    if [[ "$candidate" == /* ]]; then
      [[ -x "$candidate" ]] && { printf '%s' "$candidate"; return 0; }
    elif command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"; return 0
    fi
  done
  return 1
}
tool_bin=$(resolve_tool "$tool") || {
  printf 'BCC tool %s not found (Debian/Ubuntu: bpfcc-tools; Fedora/RHEL: bcc-tools). Ask the operator to install a distribution package.\n' "$tool" >&2
  exit 3
}

case "$output" in *.txt|*.folded) ;; *) printf 'OUTPUT must end in .txt or .folded.\n' >&2; exit 2 ;; esac
[[ ! -e "$output" && ! -L "$output" ]] || { printf 'OUTPUT exists; refusing overwrite.\n' >&2; exit 4; }
output_dir=$(dirname "$output")
[[ -d "$output_dir" && ! -L "$output_dir" ]] || { printf 'Create a private output directory first (install -d -m 700 DIR).\n' >&2; exit 4; }
(( (8#$(stat -c %a "$output_dir") & 077) == 0 )) || { printf 'Output directory must not grant group/other access.\n' >&2; exit 4; }

declare -a cmd=()
timeout_wrap=0
case "$tool" in
  offcputime) cmd=("$tool_bin" -f -p "$pid" "$duration") ;;
  profile)    cmd=("$tool_bin" -f -F 49 -p "$pid" "$duration") ;;
  runqlat)    cmd=("$tool_bin" -p "$pid" "$duration" 1) ;;
  runqslower) cmd=("$tool_bin" -p "$pid" "${threshold:-1000}"); timeout_wrap=1 ;;
  cpudist)    cmd=("$tool_bin" -O -p "$pid" "$duration" 1) ;;
  syscount)   cmd=("$tool_bin" -L -p "$pid" -d "$duration") ;;
  fileslower) cmd=("$tool_bin" -p "$pid" "${threshold:-1}"); timeout_wrap=1 ;;
  biolatency) cmd=("$tool_bin" -D "$duration" 1) ;;
  hardirqs)   cmd=("$tool_bin" -d "$duration" 1) ;;
  softirqs)   cmd=("$tool_bin" -d "$duration" 1) ;;
  tcpretrans) cmd=("$tool_bin" -c); timeout_wrap=1 ;;
esac
(( timeout_wrap )) && cmd=(timeout -s INT "$duration" "${cmd[@]}")

if [[ -n "$pid" ]]; then
  proc_root=${PROC_ROOT:-/proc}
  [[ -r "$proc_root/$pid/status" ]] || { printf 'Target PID %s is not visible.\n' "$pid" >&2; exit 4; }
  exe=$(readlink "$proc_root/$pid/exe" 2>/dev/null || true)
  if [[ "${exe##*/}" == java ]]; then
    case "$tool" in
      offcputime|profile)
        if [[ ! -e "$proc_root/$pid/root/tmp/perf-$pid.map" ]]; then
          printf 'note: no /tmp/perf-%s.map in the target namespace; JIT frames will be [unknown]. Run: jcmd %s Compiler.perfmap\n' "$pid" "$pid" >&2
        fi
        printf 'note: complete Java user stacks need -XX:+PreserveFramePointer on the target JVM (restart required).\n' >&2
        ;;
    esac
  fi
fi

printf 'command:'; printf ' %q' "${cmd[@]}"; printf ' > %q\n' "$output"
if (( dry_run )); then
  printf 'dry_run=1 (nothing executed). The operator runs the command above as root.\n'
  exit 0
fi

if [[ $(id -u) -ne 0 ]]; then
  cap_eff=$(awk '/^CapEff:/ {print $2}' /proc/self/status)
  # CAP_PERFMON=38, CAP_BPF=39
  if (( ! ((16#$cap_eff >> 38) & 1) || ! ((16#$cap_eff >> 39) & 1) )); then
    printf 'Not root and missing CAP_PERFMON/CAP_BPF. Re-run with --dry-run and hand the command to the operator.\n' >&2
    exit 5
  fi
fi

partial=$output.partial.$$
cleanup() { rm -f -- "$partial"; }
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
status=0
{
  printf '# captured_utc=%s tool=%s duration_s=%s pid=%s kernel=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$tool" "$duration" "${pid:-system}" "$(uname -r)"
  "${cmd[@]}"
} > "$partial" 2>"$partial.err" || status=$?
# timeout(1) returns 124 when it ends a tool that has no duration argument.
if (( status != 0 && !(timeout_wrap && status == 124) )); then
  printf 'capture failed (exit %s): %s\n' "$status" "$(head -c 400 "$partial.err")" >&2
  rm -f -- "$partial.err"
  exit 6
fi
rm -f -- "$partial.err"
chmod 600 "$partial"
mv -n -- "$partial" "$output"
trap - EXIT
printf 'output=%s\n' "$output"
