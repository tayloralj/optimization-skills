---
name: java-performance-investigation
description: Entry point for a Java/JVM performance problem on Linux. Turns a vague symptom (slow, jittery, p99 spikes, low throughput, high CPU, memory growth, OOM kill, slow startup) into a stated objective, a workload classification, and a routed plan across the specialised skills in this collection. Use when the user does not yet know which profiler, benchmark, GC, JIT, OS, or latency skill applies, or when an investigation spans several of them.
---

# Java Performance Investigation

Route the problem; do not start optimising. The output of this skill is a short
investigation plan that names the next skill, the evidence it must produce, and
the decision that evidence will support.

## Workflow

1. **Objective.** Write the target as a measurable service-level statement:
   metric, percentile, offered load, and environment (for example "p99.9 order
   ack below 200 µs at 50k msg/s on the lab host"). If none exists, agree one
   before measuring. Record the current value and how it was measured.
2. **Classify the workload** using `references/triage.md`: fixed-rate latency,
   maximum sustainable throughput, batch completion, startup/warmup, or memory
   footprint. Different classes need different experiments; never derive one
   from another.
3. **Readiness.** Run the `profiling-readiness` skill. Its report decides which
   evidence paths (perf, JFR, async-profiler, eBPF) are actually available.
4. **Broad observation first.** Before any narrow tool, collect one bounded,
   low-overhead baseline that separates the big buckets:
   - on-CPU application work vs GC vs JIT compilation vs safepoints;
   - off-CPU waiting: locks, I/O, network, scheduler run-queue delay;
   - OS/hardware interference: interrupts, frequency, migrations, throttling;
   - memory: heap occupancy/allocation rate vs native RSS growth.
   Launch-time JFR with unified GC and safepoint logging covers most of this on
   JDK 21 and 25 without host privileges.
5. **Route** with the symptom map in `references/triage.md`. Pick one skill and
   one question. Record what result would confirm or reject the hypothesis.
6. **Experiment discipline.** Change one factor, repeat on the same host and
   load, compare against a control, and verify the service metric without
   profiler overhead. Keep an evidence log (`references/evidence-log.md`).
7. **Close.** Report the confirmed cause, the change, before/after
   distributions with variance, residual risks, and the rollback. If the
   bottleneck did not move, say so and return to step 4.

## Low-latency first

For latency-sensitive systems (single-writer pipelines, Disruptor/Aeron-style
messaging, matching engines, market-data handlers) investigate in this order
unless evidence says otherwise, because each layer masks the next:

1. Measurement validity: coordinated omission, clock source, histogram
   resolution — `java-latency-measurement`.
2. JVM pauses: GC, safepoints/TTSP, deoptimization storms — `java-gc-tuning`,
   `java-jit-codegen`.
3. OS jitter on the hot threads: interrupts, timer ticks, run-queue delay,
   C-state exits, THP compaction — `linux-low-latency-tuning`,
   `linux-ebpf-io-network`.
4. Hot-path cost: allocation, locks, cache misses, branch misses —
   `java-async-profiler`, `java-hardware-counters`, `java-cache-efficiency`,
   `java-performance-patterns`.
5. Placement: cores, SMT siblings, cache domains, NUMA — `java-numa-affinity`.

## Guardrails

- Do not tune from a single run, an average, or a flame graph alone.
- Do not change production launch flags, kernel settings, or affinity as part
  of triage. Specialised skills own those experiments and their approvals.
- Keep throughput and tail-latency conclusions separate.
- A JMH win is a hypothesis about the service, not proof — verify end to end.
