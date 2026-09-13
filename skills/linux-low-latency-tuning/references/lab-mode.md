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

## Why root and a hostname acknowledgement

- **Root**: every allowlisted knob is a root-owned kernel file. The script never
  escalates by itself, so a person consciously runs `sudo`.
- **`LAB_HOST_ACK=$(hostname)`**: plans are host-specific (CPU numbers, IRQ
  numbers, current values). The acknowledgement stops a copied command from
  being run on the wrong machine, for example over SSH on a production host.

## Plan templates

Generate a plan from this host's current values instead of writing paths by hand:

```bash
scripts/make-lab-plan.py benchmark-host --cpus 4-5,16-17 > bench.plan
scripts/make-lab-plan.py irq-isolation  --cpus 4-5,16-17 --housekeeping 0-1,12-13 > irq.plan
scripts/make-lab-plan.py quiet-watchdogs --cpus 4-5,16-17 --housekeeping 0-1,12-13 > wd.plan
```

| Profile | Changes (only where the value differs) |
| --- | --- |
| `benchmark-host` | `performance` governor and idle states with ≥50 µs exit latency disabled on hot CPUs; THP `madvise`; NUMA balancing, KSM, and timer migration off; `vm.stat_interval` 10 |
| `irq-isolation` | Every IRQ whose affinity touches a hot CPU moved to housekeeping CPUs; unbound workqueue mask and softlockup watchdog on housekeeping CPUs |
| `quiet-watchdogs` | NMI watchdog off; softlockup watchdog on housekeeping CPUs |

Each emitted line has a comment with the reason and the current value, and
the footer lists what was skipped. Energy performance preference is not
planned: under the `performance` governor, `amd-pstate-epp` and
`intel_pstate` force it and reject other values. After rollback, re-run the
audit and check EPP, because some drivers reset it to the default rather than
the previous value.

Kernel-managed IRQs (NVMe queues, multiqueue NICs) refuse affinity changes;
`apply` reports them as `skipped`, leaves them out of the rollback record, and
continues.

## Procedure

```bash
scripts/make-lab-plan.py benchmark-host --cpus 4-5,16-17 > plan.txt   # agent, read-only
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
