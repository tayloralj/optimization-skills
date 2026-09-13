#!/usr/bin/env bash
set -uo pipefail
export LC_ALL=C

# Read-only low-latency host audit. Reads /proc, /sys, and /etc only; never
# writes, never uses sudo, never attaches to a process. Optional sampling just
# reads /proc/interrupts twice. HOST_ROOT prefixes every path (tests use a fake
# tree); leave it unset on a real host.
usage() {
  cat <<EOF
Usage: ${0##*/} [--cpus LIST] [--pid PID] [--sample-seconds N]
  --cpus LIST          intended latency-critical CPUs, e.g. 2-5,14-17
  --pid PID            check that process's affinity and cgroup CPU limits
  --sample-seconds N   measure per-CPU interrupt rates on LIST for N seconds (1-60)
Output: key=value facts, then finding=<severity>:<id>:<detail> lines.
EOF
}

hot_list=
pid=
sample=0
while (( $# )); do
  case "$1" in
    --cpus) hot_list=${2:-}; shift ;;
    --pid) pid=${2:-}; shift ;;
    --sample-seconds) sample=${2:-}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done
[[ -z "$hot_list" || "$hot_list" =~ ^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$ ]] || { printf 'Invalid --cpus list.\n' >&2; exit 2; }
[[ -z "$pid" || "$pid" =~ ^[1-9][0-9]*$ ]] || { printf 'Invalid --pid.\n' >&2; exit 2; }
[[ "$sample" =~ ^[0-9]+$ ]] && (( sample <= 60 )) || { printf 'Invalid --sample-seconds.\n' >&2; exit 2; }
(( sample == 0 )) || [[ -n "$hot_list" ]] || { printf '--sample-seconds requires --cpus.\n' >&2; exit 2; }

root=${HOST_ROOT:-}
sys=$root/sys
proc=$root/proc
declare -a findings=()

val() { if [[ -r "$1" ]]; then tr -d '\n' < "$1"; else printf 'unavailable'; fi; }
selected() { local v; v=$(val "$1"); if [[ "$v" =~ \[([^]]+)\] ]]; then printf '%s' "${BASH_REMATCH[1]}"; else printf '%s' "$v"; fi; }
fact() { printf '%s=%s\n' "$1" "$2"; }
finding() { findings+=("finding=$1:$2:$3"); }

expand_cpus() {
  local list=$1 part lo hi i
  [[ -z "$list" || "$list" == unavailable || "$list" == "(null)" ]] && return 0
  IFS=, read -ra parts <<< "$list"
  for part in "${parts[@]}"; do
    [[ -z "$part" ]] && continue
    if [[ "$part" == *-* ]]; then
      lo=${part%-*}; hi=${part#*-}
      for (( i = lo; i <= hi; i++ )); do printf '%s\n' "$i"; done
    else
      printf '%s\n' "$part"
    fi
  done
}
declare -A hot=()
while read -r c; do [[ -n "$c" ]] && hot[$c]=1; done < <(expand_cpus "$hot_list")
overlap() {
  local c n=0
  while read -r c; do [[ -n "$c" && -n "${hot[$c]:-}" ]] && n=$((n + 1)); done < <(expand_cpus "$1")
  printf '%s' "$n"
}
missing_from() {
  local set_list=$1 c out=
  declare -A in_set=()
  while read -r c; do [[ -n "$c" ]] && in_set[$c]=1; done < <(expand_cpus "$set_list")
  for c in $(printf '%s\n' "${!hot[@]}" | sort -n); do [[ -n "${in_set[$c]:-}" ]] || out+="$c,"; done
  printf '%s' "${out%,}"
}

# Kernel and boot parameters
fact kernel "$(uname -r 2>/dev/null || printf unknown)"
kernel_version=$(uname -v 2>/dev/null || printf unknown)
preempt=none_or_voluntary
[[ "$kernel_version" == *PREEMPT_RT* ]] && preempt=PREEMPT_RT
[[ "$kernel_version" == *PREEMPT_DYNAMIC* ]] && preempt=PREEMPT_DYNAMIC
fact preempt_model "$preempt"
cmdline=$(val "$proc/cmdline")
for param in isolcpus nohz_full rcu_nocbs rcu_nocb_poll irqaffinity idle processor.max_cstate intel_idle.max_cstate \
             amd_pstate intel_pstate transparent_hugepage hugepages hugepagesz default_hugepagesz mitigations \
             skew_tick nosoftlockup nowatchdog tsc clocksource nmi_watchdog audit; do
  value='unset'
  for token in $cmdline; do
    [[ "$token" == "$param" ]] && value=present
    [[ "$token" == "$param="* ]] && value=${token#*=}
  done
  fact "boot_$param" "$value"
done
isolated=$(val "$sys/devices/system/cpu/isolated")
nohz_full=$(val "$sys/devices/system/cpu/nohz_full")
fact isolated_cpus "${isolated:-none}"
fact nohz_full_cpus "${nohz_full:-none}"
fact smt_control "$(val "$sys/devices/system/cpu/smt/control")"
fact hot_cpus "${hot_list:-not_specified}"

if (( ${#hot[@]} )); then
  miss=$(missing_from "$isolated"); [[ -z "$miss" ]] || finding info not_isolated "CPUs $miss not in isolcpus/isolated set; scheduler may place other tasks there (cpuset partitions are an alternative)"
  miss=$(missing_from "$nohz_full"); [[ -z "$miss" ]] || finding info tick_not_stopped "CPUs $miss not in nohz_full; expect periodic scheduler tick interrupts"
  siblings=
  for c in "${!hot[@]}"; do
    s=$(val "$sys/devices/system/cpu/cpu$c/topology/thread_siblings_list")
    for sib in $(expand_cpus "$s"); do
      [[ "$sib" != "$c" && -z "${hot[$sib]:-}" ]] && siblings+="$c~$sib,"
    done
  done
  [[ -z "$siblings" ]] || finding warn smt_sibling_shared "hot CPU~sibling pairs where the sibling is not reserved: ${siblings%,}"
fi

# Clock source
clocksource=$(val "$sys/devices/system/clocksource/clocksource0/current_clocksource")
fact clocksource "$clocksource"
fact clocksource_available "$(val "$sys/devices/system/clocksource/clocksource0/available_clocksource")"
arch=$(uname -m 2>/dev/null || printf unknown)
if [[ "$arch" == x86_64 && "$clocksource" != tsc && "$clocksource" != unavailable ]]; then
  finding warn clocksource_not_tsc "clocksource=$clocksource; System.nanoTime may use a slow syscall path instead of the vDSO"
fi

# Frequency and idle
driver=$(val "$sys/devices/system/cpu/cpu0/cpufreq/scaling_driver")
fact cpufreq_driver "$driver"
fact amd_pstate_status "$(val "$sys/devices/system/cpu/amd_pstate/status")"
fact intel_pstate_status "$(val "$sys/devices/system/cpu/intel_pstate/status")"
fact cpufreq_boost "$(val "$sys/devices/system/cpu/cpufreq/boost")"
fact intel_no_turbo "$(val "$sys/devices/system/cpu/intel_pstate/no_turbo")"
mapfile -t check_cpus < <(printf '%s\n' "${!hot[@]}" | sed '/^$/d' | sort -n)
(( ${#check_cpus[@]} )) || check_cpus=(0)
governors=; epps=
for c in "${check_cpus[@]}"; do
  governors+="$(val "$sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor"),"
  epps+="$(val "$sys/devices/system/cpu/cpu$c/cpufreq/energy_performance_preference"),"
done
governors=$(tr ',' '\n' <<< "${governors%,}" | sort -u | paste -sd, -)
epps=$(tr ',' '\n' <<< "${epps%,}" | sort -u | paste -sd, -)
fact governors_checked_cpus "$governors"
fact epp_checked_cpus "$epps"
[[ "$governors" == performance || "$governors" == unavailable ]] || finding info governor "governor(s) $governors on checked CPUs; frequency transitions add latency variance"
[[ "$epps" == performance || "$epps" == unavailable ]] || finding info energy_preference "EPP $epps on checked CPUs; favours power over response"
fact cpuidle_driver "$(val "$sys/devices/system/cpu/cpuidle/current_driver")"
deep_states=
for c in "${check_cpus[@]}"; do
  for state in "$sys/devices/system/cpu/cpu$c/cpuidle"/state*; do
    [[ -d "$state" ]] || continue
    latency=$(val "$state/latency"); disabled=$(val "$state/disable")
    [[ "$latency" =~ ^[0-9]+$ ]] || continue
    if (( latency >= 50 )) && [[ "$disabled" == 0 ]]; then
      deep_states+="cpu$c:$(val "$state/name")(${latency}us),"
    fi
  done
done
fact idle_states_ge_50us_enabled "${deep_states%,}"
[[ -z "$deep_states" ]] || finding info deep_idle_states "enabled idle states with exit latency >=50us on checked CPUs: ${deep_states%,}"

# Memory management
thp=$(selected "$sys/kernel/mm/transparent_hugepage/enabled")
thp_defrag=$(selected "$sys/kernel/mm/transparent_hugepage/defrag")
fact thp_enabled "$thp"
fact thp_defrag "$thp_defrag"
fact thp_khugepaged_defrag "$(val "$sys/kernel/mm/transparent_hugepage/khugepaged/defrag")"
[[ "$thp" != always ]] || finding warn thp_always "THP=always: khugepaged collapse and RSS inflation; prefer madvise with -XX:+UseTransparentHugePages"
[[ "$thp_defrag" != always ]] || finding warn thp_defrag_always "THP defrag=always: allocations can stall in direct compaction"
if [[ -r "$proc/meminfo" ]]; then
  fact hugepages_total "$(awk '/^HugePages_Total:/ {print $2}' "$proc/meminfo")"
  fact hugepages_free "$(awk '/^HugePages_Free:/ {print $2}' "$proc/meminfo")"
  fact hugepage_size_kb "$(awk '/^Hugepagesize:/ {print $2}' "$proc/meminfo")"
fi
swaps=0
[[ -r "$proc/swaps" ]] && swaps=$(( $(wc -l < "$proc/swaps") - 1 ))
fact swap_devices "$swaps"
swappiness=$(val "$proc/sys/vm/swappiness")
fact vm_swappiness "$swappiness"
(( swaps <= 0 )) || [[ ! "$swappiness" =~ ^[0-9]+$ ]] || (( swappiness <= 10 )) || \
  finding info swap_enabled "swap active with swappiness=$swappiness; paged-out JVM memory causes multi-ms stalls"
numa_balancing=$(val "$proc/sys/kernel/numa_balancing")
fact kernel_numa_balancing "$numa_balancing"
[[ "$numa_balancing" == 0 || "$numa_balancing" == unavailable ]] || finding info numa_balancing "automatic NUMA balancing on: hinting faults and page migration"
for knob in vm/zone_reclaim_mode vm/stat_interval vm/compaction_proactiveness vm/dirty_background_ratio \
            vm/dirty_background_bytes vm/dirty_ratio vm/dirty_bytes kernel/timer_migration kernel/sched_rt_runtime_us \
            kernel/watchdog kernel/nmi_watchdog kernel/watchdog_cpumask; do
  fact "sysctl_${knob//\//_}" "$(val "$proc/sys/$knob")"
done
fact ksm_run "$(val "$sys/kernel/mm/ksm/run")"
[[ $(val "$sys/kernel/mm/ksm/run") != 1 ]] || finding info ksm_running "KSM scanning active: background CPU and copy-on-write faults"
fact workqueue_cpumask "$(val "$sys/devices/virtual/workqueue/cpumask")"
[[ $(val "$proc/sys/kernel/timer_migration") != 1 ]] || (( ! ${#hot[@]} )) || finding info timer_migration "kernel.timer_migration=1: timers may migrate onto hot CPUs"
if (( ${#hot[@]} )); then
  wd=$(val "$proc/sys/kernel/watchdog_cpumask")
  [[ "$wd" == unavailable || $(overlap "$wd") -eq 0 ]] || finding info watchdog_on_hot_cpus "softlockup watchdog runs on hot CPUs (watchdog_cpumask=$wd)"
fi

# IRQs
irqbalance=inactive
if [[ -z "$root" ]] && pgrep -x irqbalance >/dev/null 2>&1; then irqbalance=running; fi
fact irqbalance "$irqbalance"
tuned_profile=$(val "$root/etc/tuned/active_profile")
fact tuned_profile "$tuned_profile"
if (( ${#hot[@]} )); then
  [[ "$irqbalance" != running ]] || finding warn irqbalance_running "irqbalance may move device IRQs onto hot CPUs unless IRQBALANCE_BANNED_CPULIST excludes them"
  hot_irqs=0; hot_irq_names=
  for irq_dir in "$proc"/irq/[0-9]*; do
    [[ -d "$irq_dir" ]] || continue
    aff=$(val "$irq_dir/effective_affinity_list")
    [[ "$aff" == unavailable || -z "$aff" ]] && aff=$(val "$irq_dir/smp_affinity_list")
    if (( $(overlap "$aff") > 0 )); then
      hot_irqs=$((hot_irqs + 1))
      (( hot_irqs <= 8 )) && hot_irq_names+="${irq_dir##*/},"
    fi
  done
  fact irqs_with_hot_cpu_affinity "$hot_irqs"
  (( hot_irqs == 0 )) || finding warn irqs_on_hot_cpus "$hot_irqs IRQ(s) may fire on hot CPUs (first: ${hot_irq_names%,}); set smp_affinity_list to housekeeping CPUs"
fi

# Per-CPU interrupt rate sample
if (( sample > 0 )); then
  snapshot() {
    awk -v cpus="$hot_list" '
      BEGIN { n = split(cpus, parts, ","); for (i = 1; i <= n; i++) { if (split(parts[i], r, "-") == 2) { for (c = r[1]; c <= r[2]; c++) want[c] = 1 } else want[parts[i]] = 1 } }
      NR == 1 { for (i = 1; i <= NF; i++) { sub(/CPU/, "", $i); col[i] = $i }; ncols = NF; next }
      { name = $1; sub(/:$/, "", name); for (i = 2; i <= ncols + 1 && i <= NF; i++) { if ($i !~ /^[0-9]+$/) break; if (col[i-1] in want) sum[name] += $i } }
      END { for (k in sum) print k, sum[k] }' "$proc/interrupts"
  }
  declare -A first=()
  while read -r name count; do first[$name]=$count; done < <(snapshot)
  sleep "$sample"
  rates=
  while read -r name count; do
    delta=$(( count - ${first[$name]:-0} ))
    (( delta > 0 )) && rates+="$name:$(( delta / sample ))/s,"
  done < <(snapshot | sort)
  fact interrupt_rates_hot_cpus "${rates%,}"
  loc_rate=$(tr ',' '\n' <<< "${rates%,}" | awk -F'[:/]' '$1 == "LOC" {print $2}')
  [[ -z "$loc_rate" ]] || (( loc_rate < 10 * ${#hot[@]} )) || finding info local_timer_rate "LOC ${loc_rate}/s summed over hot CPUs: tick not stopped or timers active"
fi

# Target process
if [[ -n "$pid" ]]; then
  if [[ -r "$proc/$pid/status" ]]; then
    allowed=$(awk '/^Cpus_allowed_list:/ {print $2}' "$proc/$pid/status")
    fact pid_cpus_allowed "$allowed"
    fact pid_threads "$(awk '/^Threads:/ {print $2}' "$proc/$pid/status")"
    cg=$(awk -F: '$1 == "0" {print $3; exit}' "$proc/$pid/cgroup" 2>/dev/null)
    cgdir=$sys/fs/cgroup$cg
    cpu_max=$(val "$cgdir/cpu.max")
    fact pid_cgroup_cpu_max "$cpu_max"
    fact pid_cgroup_cpuset_effective "$(val "$cgdir/cpuset.cpus.effective")"
    fact pid_cgroup_cpuset_partition "$(val "$cgdir/cpuset.cpus.partition")"
    throttled=$(awk '/^nr_throttled / {print $2}' "$cgdir/cpu.stat" 2>/dev/null)
    fact pid_cgroup_nr_throttled "${throttled:-unavailable}"
    [[ "$cpu_max" == unavailable || "$cpu_max" == max* ]] || finding warn cfs_quota "cgroup cpu.max=$cpu_max: CFS quota throttling causes periodic stalls; JVM sizes threads from the quota"
    [[ -z "$throttled" || "$throttled" == 0 ]] || finding warn cfs_throttled "cgroup reports nr_throttled=$throttled"
  else
    fact pid_status unavailable
  fi
fi

printf '%s\n' "${findings[@]}"
printf 'findings=%s\n' "${#findings[@]}"
