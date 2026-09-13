#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

# Lab-mode runtime tuning with recorded rollback. Changes ONLY allowlisted,
# non-persistent /sys and /proc/sys knobs (lost on reboot). Never edits
# bootloader, sysctl.d, systemd units, or services, and never calls sudo:
# the operator runs `apply`/`rollback` as root on a host they declared a lab.
usage() {
  cat <<EOF
Usage:
  ${0##*/} plan PLAN_FILE                 validate and show current -> requested (read-only)
  ${0##*/} apply PLAN_FILE NEW_STATE_DIR  apply as root; requires LAB_HOST_ACK=\$(hostname)
  ${0##*/} rollback STATE_DIR             restore recorded originals (reverse order), as root
  ${0##*/} status STATE_DIR               compare live values with the recorded state

PLAN_FILE lines:  set <absolute-path> <value>     ('#' comments allowed)
Allowed paths and values are listed by: ${0##*/} allowlist
EOF
}

test_root=${LAB_TUNE_TEST_ROOT:-}

# path-regex <TAB> value-regex <TAB> note
allowlist() {
  cat <<'EOF'
^/sys/devices/system/cpu/cpu[0-9]+/cpufreq/scaling_governor$	^(performance|powersave|schedutil|ondemand|conservative|userspace)$	per-CPU governor
^/sys/devices/system/cpu/cpu[0-9]+/cpufreq/energy_performance_preference$	^(performance|balance_performance|default|balance_power|power)$	per-CPU EPP (amd-pstate-epp/intel_pstate)
^/sys/devices/system/cpu/cpu[0-9]+/cpuidle/state[0-9]+/disable$	^[01]$	disable one idle state on one CPU
^/sys/devices/system/cpu/cpufreq/boost$	^[01]$	global frequency boost
^/sys/devices/system/cpu/intel_pstate/no_turbo$	^[01]$	Intel turbo disable
^/sys/devices/system/cpu/smt/control$	^(on|off)$	SMT runtime control (forceoff is not reversible and is refused)
^/sys/kernel/mm/transparent_hugepage/enabled$	^(always|madvise|never)$	THP mode
^/sys/kernel/mm/transparent_hugepage/defrag$	^(always|defer|defer\+madvise|madvise|never)$	THP defrag policy
^/sys/kernel/mm/transparent_hugepage/khugepaged/defrag$	^[01]$	khugepaged collapse
^/sys/kernel/mm/ksm/run$	^[01]$	KSM scanning (2 would unmerge and is refused)
^/sys/devices/virtual/workqueue/cpumask$	^[0-9a-fA-F,]+$	unbound workqueue CPU mask
^/proc/sys/kernel/numa_balancing$	^[0-3]$	automatic NUMA balancing
^/proc/sys/kernel/timer_migration$	^[01]$	timer migration
^/proc/sys/kernel/nmi_watchdog$	^[01]$	NMI watchdog
^/proc/sys/kernel/watchdog_cpumask$	^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$	softlockup watchdog CPUs
^/proc/sys/vm/stat_interval$	^[1-9][0-9]{0,3}$	vmstat update interval seconds
^/proc/sys/vm/swappiness$	^([0-9]|[1-9][0-9]|1[0-9][0-9]|200)$	swappiness
^/proc/sys/vm/nr_hugepages$	^[0-9]{1,7}$	persistent-pool huge pages (may allocate fewer)
^/proc/sys/vm/compaction_proactiveness$	^([0-9]|[1-9][0-9]|100)$	proactive compaction
^/proc/irq/[0-9]+/smp_affinity_list$	^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$	IRQ affinity
EOF
}

die() { printf '%s\n' "$1" >&2; exit "${2:-2}"; }
real_path() { printf '%s%s' "$test_root" "$1"; }

# Current value; bracketed selection for multi-choice sysfs files.
read_value() {
  local file raw
  file=$(real_path "$1")
  [[ -r "$file" ]] || return 1
  raw=$(tr -d '\n' < "$file")
  if [[ "$raw" =~ \[([^]]+)\] ]]; then printf '%s' "${BASH_REMATCH[1]}"; else printf '%s' "$raw"; fi
}

check_entry() {
  local path=$1 value=$2 path_re value_re note
  [[ "$path" != *..* && "$path" == /* ]] || return 1
  while IFS=$'\t' read -r path_re value_re note; do
    if [[ "$path" =~ $path_re ]]; then
      [[ "$value" =~ $value_re ]] && return 0
      printf 'value %q not allowed for %s (%s)\n' "$value" "$path" "$note" >&2
      return 1
    fi
  done < <(allowlist)
  printf 'path not allowlisted: %s\n' "$path" >&2
  return 1
}

declare -a plan_paths=() plan_values=()
load_plan() {
  local file=$1 line_no=0 verb path value extra
  [[ -f "$file" && ! -L "$file" ]] || die "PLAN_FILE must be a regular file."
  declare -A seen=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_no=$((line_no + 1))
    line=${line%%#*}
    [[ -z "${line//[[:space:]]/}" ]] && continue
    read -r verb path value extra <<< "$line"
    [[ "$verb" == set && -n "${path:-}" && -n "${value:-}" && -z "${extra:-}" ]] || die "line $line_no: expected 'set PATH VALUE'"
    check_entry "$path" "$value" || die "line $line_no rejected"
    [[ -z "${seen[$path]:-}" ]] || die "line $line_no: duplicate path $path"
    seen[$path]=1
    [[ -e "$(real_path "$path")" ]] || die "line $line_no: $path does not exist on this host" 3
    plan_paths+=("$path"); plan_values+=("$value")
  done < "$file"
  (( ${#plan_paths[@]} )) || die "PLAN_FILE contains no entries."
}

require_lab_and_root() {
  local host
  host=$(hostname 2>/dev/null || uname -n)
  [[ "${LAB_HOST_ACK:-}" == "$host" ]] || die "Refusing: set LAB_HOST_ACK=$host to confirm this is a lab/benchmark host (never production)." 5
  if [[ -z "$test_root" ]]; then
    [[ $(id -u) -eq 0 ]] || die "apply/rollback must run as root (the operator runs it; this script never calls sudo)." 5
  fi
}

write_value() {
  local path=$1 value=$2 file
  file=$(real_path "$path")
  printf '%s' "$value" > "$file"
}

verify_value() {
  local path=$1 expected=$2 actual
  actual=$(read_value "$path") || return 1
  [[ "$actual" == "$expected" ]] && return 0
  # nr_hugepages can legitimately allocate fewer pages than requested.
  if [[ "$path" == /proc/sys/vm/nr_hugepages ]]; then
    printf 'note: nr_hugepages requested %s, allocated %s\n' "$expected" "$actual" >&2
    return 0
  fi
  printf 'verify failed: %s expected %s got %s\n' "$path" "$expected" "$actual" >&2
  return 1
}

cmd_plan() {
  load_plan "$1"
  local i current
  printf 'host=%s kernel=%s\n' "$(hostname 2>/dev/null || uname -n)" "$(uname -r)"
  for i in "${!plan_paths[@]}"; do
    current=$(read_value "${plan_paths[$i]}" || printf unreadable)
    printf '%-70s %s -> %s%s\n' "${plan_paths[$i]}" "$current" "${plan_values[$i]}" \
      "$([[ "$current" == "${plan_values[$i]}" ]] && printf '  (no change)')"
  done
  printf 'plan_ok entries=%s (read-only; nothing changed)\n' "${#plan_paths[@]}"
}

declare -a applied_paths=() applied_originals=()
state_dir=
rollback_applied() {
  local i status=0
  for (( i = ${#applied_paths[@]} - 1; i >= 0; i-- )); do
    if write_value "${applied_paths[$i]}" "${applied_originals[$i]}" 2>/dev/null && \
       verify_value "${applied_paths[$i]}" "${applied_originals[$i]}"; then
      printf 'restored %s=%s\n' "${applied_paths[$i]}" "${applied_originals[$i]}"
    else
      printf 'FAILED to restore %s=%s\n' "${applied_paths[$i]}" "${applied_originals[$i]}" >&2
      status=1
    fi
  done
  applied_paths=(); applied_originals=()
  return "$status"
}

cmd_apply() {
  local plan=$1 i original
  state_dir=$2
  require_lab_and_root
  load_plan "$plan"
  [[ -n "$state_dir" && ! -e "$state_dir" && ! -L "$state_dir" ]] || die "NEW_STATE_DIR must not exist."
  declare -a originals=()
  for i in "${!plan_paths[@]}"; do
    original=$(read_value "${plan_paths[$i]}") || die "cannot read ${plan_paths[$i]}; nothing changed" 6
    check_entry "${plan_paths[$i]}" "$original" || die "current value of ${plan_paths[$i]} is outside the allowlist, so rollback could not restore it; nothing changed" 6
    originals+=("$original")
  done

  mkdir -m 700 -- "$state_dir"
  {
    printf 'created_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'host=%s\nkernel=%s\n' "$(hostname 2>/dev/null || uname -n)" "$(uname -r)"
    printf 'plan_sha256=%s\n' "$(sha256sum "$plan" | awk '{print $1}')"
  } > "$state_dir/meta.txt"
  cp -- "$plan" "$state_dir/plan.txt"
  : > "$state_dir/rollback.tsv"

  on_interrupt() {
    printf 'interrupted: rolling back applied entries\n' >&2
    rollback_applied || true
    printf 'status=rolled_back_after_interrupt\n' >> "$state_dir/meta.txt"
    exit 130
  }
  trap on_interrupt HUP INT TERM

  for i in "${!plan_paths[@]}"; do
    original=${originals[$i]}
    # Record before writing so a crash leaves a usable rollback file.
    printf '%s\t%s\n' "${plan_paths[$i]}" "$original" >> "$state_dir/rollback.tsv"
    applied_paths+=("${plan_paths[$i]}"); applied_originals+=("$original")
    if ! write_value "${plan_paths[$i]}" "${plan_values[$i]}" 2>"$state_dir/last-error.txt" || \
       ! verify_value "${plan_paths[$i]}" "${plan_values[$i]}"; then
      printf 'apply failed at %s: %s\n' "${plan_paths[$i]}" "$(tr '\n' ' ' < "$state_dir/last-error.txt")" >&2
      if [[ "$(read_value "${plan_paths[$i]}" 2>/dev/null)" == "$original" ]]; then
        unset 'applied_paths[-1]' 'applied_originals[-1]'
      fi
      rollback_applied || { printf 'status=partial_rollback_failure\n' >> "$state_dir/meta.txt"; exit 7; }
      printf 'status=rolled_back_after_failure\n' >> "$state_dir/meta.txt"
      exit 6
    fi
    printf 'applied %s: %s -> %s\n' "${plan_paths[$i]}" "$original" "${plan_values[$i]}"
  done
  trap - HUP INT TERM
  printf 'status=applied\n' >> "$state_dir/meta.txt"
  printf 'state=%s\nrollback: %s rollback %s\n' "$state_dir" "${0##*/}" "$state_dir"
}

load_state() {
  local dir=$1 path original
  [[ -d "$dir" && ! -L "$dir" && -f "$dir/rollback.tsv" ]] || die "not a lab-tune state directory: $dir"
  while IFS=$'\t' read -r path original; do
    [[ -n "$path" ]] || continue
    check_entry "$path" "$original" 2>/dev/null || die "state entry fails allowlist: $path=$original"
    applied_paths+=("$path"); applied_originals+=("$original")
  done < "$dir/rollback.tsv"
}

cmd_rollback() {
  require_lab_and_root
  grep -q '^status=rolled_back' "$1/meta.txt" 2>/dev/null && die "state already rolled back: $1" 0
  load_state "$1"
  if rollback_applied; then
    printf 'status=rolled_back\n' >> "$1/meta.txt"
    printf 'rollback complete\n'
  else
    printf 'status=rollback_incomplete\n' >> "$1/meta.txt"
    exit 7
  fi
}

cmd_status() {
  local i current requested
  load_state "$1"
  declare -A requested_by_path=()
  if [[ -f "$1/plan.txt" ]]; then
    while read -r _ path value; do [[ -n "${path:-}" ]] && requested_by_path[$path]=$value; done < <(grep -E '^set ' "$1/plan.txt")
  fi
  grep '^status=' "$1/meta.txt" | tail -n 1 || true
  for i in "${!applied_paths[@]}"; do
    current=$(read_value "${applied_paths[$i]}" || printf unreadable)
    requested=${requested_by_path[${applied_paths[$i]}]:-?}
    printf '%-70s original=%s requested=%s live=%s\n' "${applied_paths[$i]}" "${applied_originals[$i]}" "$requested" "$current"
  done
}

case "${1:-}" in
  plan) [[ $# -eq 2 ]] || { usage >&2; exit 2; }; cmd_plan "$2" ;;
  apply) [[ $# -eq 3 ]] || { usage >&2; exit 2; }; cmd_apply "$2" "$3" ;;
  rollback) [[ $# -eq 2 ]] || { usage >&2; exit 2; }; cmd_rollback "$2" ;;
  status) [[ $# -eq 2 ]] || { usage >&2; exit 2; }; cmd_status "$2" ;;
  allowlist) allowlist | awk -F'\t' '{printf "%-62s %-40s %s\n", $1, $2, $3}' ;;
  -h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
