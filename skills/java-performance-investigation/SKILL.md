---
name: java-performance-investigation
description: Start here for a Java performance problem on Linux. Turns a symptom (slow, jittery, p99 spikes, high CPU, memory growth, OOM kill, slow startup) into a goal, a workload type, and a plan naming the next skill. Use when the cause or the right tool is not yet known.
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
   maximum sustainable throughput, batch completion, startup/warmup, memory
   footprint, or recovery episodes (gap fill, replay, reconnect, catch-up). Different classes need different experiments; never derive one
   from another.
3. **Readiness.** Run the `profiling-readiness` skill. Its report decides which
   evidence paths (perf, JFR, async-profiler, eBPF) are actually available.
4. **Broad observation first.** Before any narrow tool, collect one bounded,
   low-overhead baseline that separates the big buckets:
   - on-CPU application work vs GC vs JIT compilation vs safepoints;
   - off-CPU waiting: locks, I/O, network, scheduler run-queue delay;
   - OS/hardware interference: interrupts, frequency, migrations, throttling;
   - memory: heap occupancy/allocation rate vs native RSS growth;
   - work amplification: requests, round trips, syscalls, or retries per
     logical operation. Count them; a protocol that repeats work is invisible
     to CPU and GC profiles.
   - completeness: operations finished versus operations offered. A stalled
     system can produce good-looking latency for the operations that did finish.
   Launch-time JFR with unified GC and safepoint logging covers most of this on
   JDK 21 and 25 without host privileges.
5. **Route** with the symptom map in `references/triage.md`. For services in
   containers or Kubernetes, check limits first with `references/containers.md`. Pick one skill and
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
6. Code shape: allocation-free hot paths, single writers, wait strategies —
   `java-low-latency-patterns`.

When perf, eBPF, or attach access is not available, start with the
`java-flight-recorder` skill: JFR needs no privileges and covers GC, locks,
I/O, allocation, and CPU samples.

## Guardrails

- Do not tune from a single run, an average, or a flame graph alone.
- Do not change production launch flags, kernel settings, or affinity as part
  of triage. Specialised skills own those experiments and their approvals.
- Keep throughput and tail-latency conclusions separate.
- A JMH win is a hypothesis about the service, not proof — verify end to end.
