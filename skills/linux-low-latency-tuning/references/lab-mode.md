# Lab mode contract

Lab mode lets the agent drive reversible, runtime-only host experiments on a
machine the user has declared expendable for benchmarking. It never applies to
production, shared, or customer hosts.

## Preconditions (all required)

1. The user explicitly said in the current conversation that this host is a
   lab/benchmark host. Approval does not carry over to other hosts or sessions.
2. A read-only audit (`scripts/latency-host-audit.sh`) was captured and saved.
3. A plan file lists each change; `scripts/lab-tune.sh plan PLAN` was shown to
   the user and they approved that exact plan.
4. The operator runs `apply` and `rollback` as root with
   `LAB_HOST_ACK=$(hostname)`. The agent does not handle passwords, does not
   add sudoers rules, and does not wrap the script in `sudo` unattended.

## What the script can change

Only allowlisted runtime knobs (`lab-tune.sh allowlist`): per-CPU governor,
EPP, idle-state disable, boost/turbo, SMT on/off, THP mode/defrag/khugepaged,
KSM, workqueue cpumask, NUMA balancing, timer migration, NMI and softlockup
watchdog CPUs, vmstat interval, swappiness, huge page pool, proactive
compaction, and IRQ affinity. All are lost on reboot.

It refuses: unlisted paths, `..` paths, values outside per-knob patterns,
irreversible values (`smt/control=forceoff`, `ksm/run=2`), current values it
could not restore, existing state directories, and missing hostname
acknowledgement.

## Procedure

```bash
cat > plan.txt <<'EOF'
set /sys/kernel/mm/transparent_hugepage/defrag defer+madvise
set /proc/sys/kernel/timer_migration 0
set /proc/irq/123/smp_affinity_list 0-1
EOF
scripts/lab-tune.sh plan plan.txt                      # agent, read-only
LAB_HOST_ACK=$(hostname) scripts/lab-tune.sh apply plan.txt ./lab-state-1   # operator, root
scripts/lab-tune.sh status ./lab-state-1               # agent
# ... measure with the same load as the baseline ...
LAB_HOST_ACK=$(hostname) scripts/lab-tune.sh rollback ./lab-state-1         # operator, root
```

`apply` records every original value before writing, verifies each write by
reading it back, and on any failure or interrupt restores the entries already
changed in reverse order. `rollback` restores and verifies all recorded values
and marks the state directory so it cannot be replayed twice.

## Experiment record

For each state directory keep: audit before, plan, apply output, measurement
artifacts (histograms, interrupt deltas, runqlat), audit after, rollback
output, and the decision. Do not stack experiments: roll back before the next
plan unless the combination itself is the hypothesis.

## Out of scope for automation

Boot parameters (`isolcpus`, `nohz_full`, `rcu_nocbs`, `irqaffinity`, C-state
limits, `mitigations`), BIOS settings, tuned profiles, irqbalance
configuration, cgroup/systemd unit changes, NIC firmware or driver options, and
anything persistent. Produce an operator plan with a bootloader rollback entry.
