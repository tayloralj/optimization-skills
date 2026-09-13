---
name: linux-low-latency-tuning
description: Audit a Linux host for jitter that hurts low-latency Java (IRQs, timer ticks, C-states, frequency, THP, swap, CPU quotas) and plan CPU isolation and thread pinning. Read-only, with an opt-in lab mode for reversible changes. Use when tail latency is not explained by GC or JIT.
---

# Linux Low-Latency Tuning

Tuning removes interference; it cannot fix a slow algorithm or a JVM pause.
Prove the hot thread is being interrupted, preempted, throttled, or stalled
before changing the host, and measure every change.

## Modes

- **Default (read-only)**: audit, explain, and produce an operator-owned plan
  with rollback. Never change the host.
- **Lab mode**: only when the user has explicitly stated, in this conversation,
  that the target is a lab/benchmark host (not production). Follow
  `references/lab-mode.md`: generate a host-specific plan with
  `scripts/make-lab-plan.py` (profiles `benchmark-host`, `irq-isolation`,
  `quiet-watchdogs`), show it, get approval, and have the operator apply it as
  root with `scripts/lab-tune.sh` and a hostname acknowledgement. Boot parameters and persistent configuration remain
  operator-owned in both modes.

## Workflow

1. **Readiness and topology**: run the `profiling-readiness` skill; record CPU
   model, sockets, NUMA nodes, cache domains, SMT siblings, and cgroup limits.
2. **Choose CPUs**: pick latency-critical CPUs from topology (whole cores, one
   cache domain, away from CPU 0 and device-IRQ-heavy CPUs); reserve
   housekeeping CPUs for the OS, IRQs, JVM GC/JIT threads, and logging.
3. **Audit**:

   ```bash
   scripts/latency-host-audit.sh --cpus 4-7,16-19 --pid "$JAVA_PID" --sample-seconds 10
   ```

   It reports boot parameters, isolation and tick state, clocksource,
   governor/EPP/idle states, THP and swap, NUMA balancing, watchdogs, KSM,
   IRQs routed to the chosen CPUs, per-CPU interrupt rates, and the target's
   cgroup CPU quota/throttling, then prints `finding=` lines.
4. **Prioritise** with `references/os-tuning.md`. Typical order: CFS quota
   throttling → swap/THP compaction → IRQs and kernel threads on hot CPUs →
   frequency/idle exits → timer tick (nohz_full) → SMT sibling noise.
5. **Plan one change** with expected effect, validation command, and rollback.
   Runtime knobs can be trialled in lab mode; boot parameters need a reboot
   and a bootloader rollback entry owned by the operator.
6. **Measure** before and after with the same load: application latency
   histogram (the `java-latency-measurement` skill), per-CPU interrupt deltas,
   run-queue latency and off-CPU time (the `linux-ebpf-io-network` skill), and
   power/thermal behaviour.
7. **Pin JVM threads deliberately** (see reference): hot threads onto isolated
   CPUs, everything else (GC, JIT, JFR, logging) onto housekeeping CPUs. Record
   final `ParallelGCThreads`, `ConcGCThreads`, `CICompilerCount`.
8. **Roll back** anything that did not measurably help. Hand persistent
   changes to the operator as a reviewed change with its rollback.

## Guardrails

- Never modify production hosts, bootloader entries, `/etc/sysctl.d`, systemd
  units, tuned profiles, or IRQ daemons from this skill; produce the plan.
- Do not disable CPU vulnerability mitigations (`mitigations=off`) without an
  explicit security decision; record it as a separate risk.
- Busy-spinning threads on isolated CPUs raise power and heat and can starve
  anything else scheduled there; `SCHED_FIFO` busy loops can hang a CPU.
- `isolcpus` removes CPUs from scheduler load balancing: threads not explicitly
  pinned will never run there, and pinned threads there are not rebalanced.
- Container runtimes and Kubernetes CPU managers own affinity inside pods;
  coordinate rather than overriding with `taskset`.
