#!/usr/bin/env bash
set -uo pipefail

# Read-only preflight. It never uses sudo, attaches to another process, installs
# software, or persists configuration. Smoke tests launch only short child
# processes owned by the current user and write temporary evidence under TMPDIR.
export LC_ALL=C
umask 077

usage() { printf 'Usage: %s [--no-smoke-test]\n' "${0##*/}"; }
run_smoke=1
case "${1:-}" in
  "") ;;
  --no-smoke-test) run_smoke=0 ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

have() { command -v "$1" >/dev/null 2>&1; }
read_value() {
  local path=$1
  if [[ -r "$path" ]]; then tr -d '\n' < "$path"; else printf 'unavailable'; fi
}
tool_state() { if have "$1"; then printf 'available'; else printf 'missing'; fi; }
one_line() { tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g; s/^ //; s/ $//' | cut -c1-240; }
version_line() {
  local command_name=$1
  shift
  if have "$command_name"; then "$@" 2>&1 | one_line; else printf 'unavailable'; fi
}

os_name=$(uname -s 2>/dev/null || printf unknown)
kernel=$(uname -r 2>/dev/null || printf unknown)
arch=$(uname -m 2>/dev/null || printf unknown)
vendor=unknown
model=unknown
logical_cpus=unknown
cores=unknown
sockets=unknown
numa_nodes=unknown
threads_per_core=unknown
if have lscpu; then
  vendor=$(lscpu | awk -F: '/Vendor ID:/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')
  model=$(lscpu | awk -F: '/Model name:/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')
  logical_cpus=$(lscpu | awk -F: '/^CPU\(s\):/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')
  cores=$(lscpu | awk -F: '/Core\(s\) per socket:/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')
  sockets=$(lscpu | awk -F: '/Socket\(s\):/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')
  numa_nodes=$(lscpu | awk -F: '/NUMA node\(s\):/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')
  threads_per_core=$(lscpu | awk -F: '/Thread\(s\) per core:/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')
fi

effective_cpus=$(awk '/^Cpus_allowed_list:/ {print $2}' /proc/self/status 2>/dev/null || printf unavailable)
effective_mems=$(awk '/^Mems_allowed_list:/ {print $2}' /proc/self/status 2>/dev/null || printf unavailable)
cap_eff=$(awk '/^CapEff:/ {print $2}' /proc/self/status 2>/dev/null || printf unavailable)
no_new_privs=$(awk '/^NoNewPrivs:/ {print $2}' /proc/self/status 2>/dev/null || printf unavailable)
seccomp=$(awk '/^Seccomp:/ {print $2}' /proc/self/status 2>/dev/null || printf unavailable)
pid_namespace=$(readlink /proc/self/ns/pid 2>/dev/null || printf unavailable)
microcode=$(read_value /sys/devices/system/cpu/cpu0/microcode/version)
smt_active=$(read_value /sys/devices/system/cpu/smt/active)
thread_sibling_lists=unavailable
if compgen -G '/sys/devices/system/cpu/cpu0/topology/thread_siblings_list' >/dev/null; then
  thread_sibling_lists=$(sort -u /sys/devices/system/cpu/cpu*/topology/thread_siblings_list 2>/dev/null | paste -sd';' -)
fi

llc_level=unknown
llc_domains=unknown
llc_cpu_lists=unavailable
if compgen -G '/sys/devices/system/cpu/cpu0/cache/index*/level' >/dev/null; then
  llc_level=$(for index_dir in /sys/devices/system/cpu/cpu0/cache/index*; do
    [[ $(read_value "$index_dir/type") == Unified ]] && read_value "$index_dir/level" && printf '\n'
  done | sort -n | tail -n 1)
  if [[ -n "$llc_level" ]]; then
    llc_cpu_lists=$(for cpu_dir in /sys/devices/system/cpu/cpu[0-9]*; do
      for index_dir in "$cpu_dir"/cache/index*; do
        [[ $(read_value "$index_dir/type") == Unified ]] || continue
        [[ $(read_value "$index_dir/level") == "$llc_level" ]] || continue
        read_value "$index_dir/shared_cpu_list"
        printf '\n'
      done
    done | sort -u | sed '/^$/d' | paste -sd';' -)
    llc_domains=$(printf '%s\n' "$llc_cpu_lists" | tr ';' '\n' | sed '/^$/d' | wc -l | tr -d ' ')
  fi
fi

governors=unavailable
if compgen -G '/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor' >/dev/null; then
  governors=$(sort -u /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | paste -sd, -)
fi
energy_preferences=unavailable
if compgen -G '/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference' >/dev/null; then
  energy_preferences=$(sort -u /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference 2>/dev/null | paste -sd, -)
fi
frequency_min_khz=$(read_value /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq)
frequency_max_khz=$(read_value /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq)
jvm_default_ergonomics=unavailable
if have java; then
  jvm_default_ergonomics=$(java -XX:+PrintFlagsFinal -version 2>&1 | \
    awk '/ActiveProcessorCount|CICompilerCount|ParallelGCThreads|ConcGCThreads|Use[A-Za-z0-9]+GC/ {printf "%s=%s;", $2, $4}' | cut -c1-1000)
fi

perf_smoke=not_run
perf_reason=not_run
if (( run_smoke )) && have perf && [[ "$os_name" == Linux ]]; then
  perf_error=$(mktemp "${TMPDIR:-/tmp}/profiling-readiness-perf.XXXXXX") || exit 2
  if perf stat -e task-clock -- true >/dev/null 2>"$perf_error"; then
    perf_smoke=passed
    perf_reason=none
  else
    perf_smoke=failed
    perf_reason=$(one_line < "$perf_error")
    [[ -n "$perf_reason" ]] || perf_reason=unknown
  fi
  rm -f -- "$perf_error"
elif (( run_smoke )); then
  perf_smoke=unavailable
  perf_reason=perf_or_linux_missing
fi

jfr_smoke=not_run
jfr_reason=not_run
if (( run_smoke )) && have java && have jfr; then
  jfr_file=$(mktemp "${TMPDIR:-/tmp}/profiling-readiness.XXXXXX.jfr") || exit 2
  jfr_error=$(mktemp "${TMPDIR:-/tmp}/profiling-readiness-jfr.XXXXXX") || { rm -f -- "$jfr_file"; exit 2; }
  rm -f -- "$jfr_file"
  if java -XX:StartFlightRecording=duration=1s,filename="$jfr_file",settings=profile -version \
      >/dev/null 2>"$jfr_error" && [[ -s "$jfr_file" ]] && jfr summary "$jfr_file" >/dev/null 2>&1; then
    jfr_smoke=passed_launch_time
    jfr_reason=none
  else
    jfr_smoke=failed
    jfr_reason=$(one_line < "$jfr_error")
    [[ -n "$jfr_reason" ]] || jfr_reason=unknown
  fi
  rm -f -- "$jfr_file" "$jfr_error"
elif (( run_smoke )); then
  jfr_smoke=unavailable
  jfr_reason=java_or_jfr_missing
fi

asprof_state=missing
asprof_bin=
if have asprof; then
  asprof_state=available_unverified
  asprof_bin=$(command -v asprof)
elif [[ -n "${ASYNC_PROFILER_HOME:-}" && -x "${ASYNC_PROFILER_HOME}/bin/asprof" ]]; then
  asprof_state=available_unverified
  asprof_bin=${ASYNC_PROFILER_HOME}/bin/asprof
fi
asprof_version=unavailable
asprof_smoke=not_run_requires_target
if [[ -n "$asprof_bin" ]]; then
  if asprof_version=$("$asprof_bin" --version 2>&1 | one_line); then :; else asprof_version=version_check_failed; fi
fi

jol_state=missing
if have jol; then
  jol_state=available
elif [[ -n "${JOL_CLI_JAR:-}" && -r "${JOL_CLI_JAR}" ]]; then
  jol_state=available_via_jol_cli_jar
fi

status=BLOCKED_PERMISSION_OR_TOOLING
if (( ! run_smoke )); then
  status=TOOLS_PRESENT_NOT_TESTED
elif [[ "$perf_smoke" == passed ]]; then
  status=READY_PERF_SOFTWARE_EVENT
elif [[ "$jfr_smoke" == passed_launch_time ]]; then
  status=DEGRADED_VERIFIED_JFR_FALLBACK
elif [[ "$asprof_state" == available_unverified ]]; then
  status=FALLBACK_TOOL_PRESENT_UNVERIFIED
fi

report_file=$(mktemp "${TMPDIR:-/tmp}/profiling-readiness-report.XXXXXX") || exit 2
cleanup_report() { rm -f -- "$report_file"; }
trap cleanup_report EXIT HUP INT TERM
{
printf 'schema_version=2\n'
printf 'status=%s\n' "$status"
printf 'os=%s\n' "$os_name"
printf 'kernel=%s\n' "$kernel"
printf 'architecture=%s\n' "$arch"
printf 'cpu_vendor=%s\n' "${vendor:-unknown}"
printf 'cpu_model=%s\n' "${model:-unknown}"
printf 'microcode=%s\n' "$microcode"
printf 'logical_cpus=%s\n' "${logical_cpus:-unknown}"
printf 'cores_per_socket=%s\n' "${cores:-unknown}"
printf 'threads_per_core=%s\n' "${threads_per_core:-unknown}"
printf 'sockets=%s\n' "${sockets:-unknown}"
printf 'smt_active=%s\n' "$smt_active"
printf 'thread_sibling_lists=%s\n' "$thread_sibling_lists"
printf 'numa_nodes=%s\n' "${numa_nodes:-unknown}"
printf 'llc_level=%s\n' "${llc_level:-unknown}"
printf 'llc_domains=%s\n' "${llc_domains:-unknown}"
printf 'llc_cpu_lists=%s\n' "${llc_cpu_lists:-unavailable}"
printf 'effective_cpus=%s\n' "${effective_cpus:-unavailable}"
printf 'effective_mems=%s\n' "${effective_mems:-unavailable}"
printf 'governors=%s\n' "$governors"
printf 'energy_preferences=%s\n' "$energy_preferences"
printf 'frequency_min_khz=%s\n' "$frequency_min_khz"
printf 'frequency_max_khz=%s\n' "$frequency_max_khz"
printf 'perf_event_paranoid=%s\n' "$(read_value /proc/sys/kernel/perf_event_paranoid)"
printf 'kptr_restrict=%s\n' "$(read_value /proc/sys/kernel/kptr_restrict)"
printf 'cap_eff=%s\n' "${cap_eff:-unavailable}"
printf 'no_new_privs=%s\n' "${no_new_privs:-unavailable}"
printf 'seccomp=%s\n' "${seccomp:-unavailable}"
printf 'pid_namespace=%s\n' "${pid_namespace:-unavailable}"
printf 'perf=%s\n' "$(tool_state perf)"
printf 'perf_version=%s\n' "$(version_line perf perf --version)"
printf 'perf_smoke=%s\n' "$perf_smoke"
printf 'perf_reason=%s\n' "$perf_reason"
printf 'java=%s\n' "$(tool_state java)"
printf 'java_version=%s\n' "$(version_line java java -version)"
printf 'jvm_default_ergonomics=%s\n' "$jvm_default_ergonomics"
printf 'jcmd=%s\n' "$(tool_state jcmd)"
printf 'jfr=%s\n' "$(tool_state jfr)"
printf 'jfr_smoke=%s\n' "$jfr_smoke"
printf 'jfr_reason=%s\n' "$jfr_reason"
printf 'async_profiler=%s\n' "$asprof_state"
printf 'async_profiler_version=%s\n' "$asprof_version"
printf 'async_profiler_smoke=%s\n' "$asprof_smoke"
printf 'jol=%s\n' "$jol_state"
printf 'numactl=%s\n' "$(tool_state numactl)"
printf 'bpftrace=%s\n' "$(tool_state bpftrace)"
bcc_tools=missing
if have offcputime-bpfcc || have offcputime || [[ -x /usr/share/bcc/tools/offcputime ]]; then bcc_tools=available; fi
printf 'bcc_tools=%s\n' "$bcc_tools"
printf 'ebpf_smoke=not_run_requires_root_or_cap_bpf\n'
printf 'lstopo=%s\n' "$(tool_state lstopo)"
printf 'vtune=%s\n' "$(tool_state vtune)"
printf 'vtune_version=%s\n' "$(version_line vtune vtune --version)"
printf 'amd_uprof_cli=%s\n' "$(tool_state AMDuProfCLI)"
printf 'amd_uprof_version=%s\n' "$(version_line AMDuProfCLI AMDuProfCLI --version)"
} > "$report_file"
cat "$report_file"
cleanup_report
trap - EXIT HUP INT TERM
