---
name: java-performance-investigation
description: Start here for slow, stuck, crashing, or resource-hungry Java services on Linux. Use when the cause or next tool is unclear to define the problem, choose online or offline evidence, and route to a specialist.
---

# Java Performance Investigation

Route the problem; do not start optimising. The output of this skill is a short
investigation plan that names the next skill, the evidence it must produce, and
the decision that evidence will support. This is the collection's single entry
point for an unexplained JVM symptom. When the user already supplies a specific
artifact or asks for a particular profiler, use that specialist directly.

The `linux-jvm-debug` skill supplies supporting report and target-check helpers;
it does not own a separate investigation workflow. Helper dependencies are
listed in `requires.txt` and installed automatically.

## Workflow

1. **Scope and objective.** Identify the affected service/JVM, incident window,
   environment, available access, and existing evidence. Discover the real PID
   when needed; example PIDs are not targets. For crashes, restarts, or hangs,
   establish the failure timeline and expected healthy behavior first; do not
   delay incident evidence gathering for a latency SLO. For performance, write
   the target as a measurable service-level statement:
   metric, percentile, offered load, and environment (for example "p99.9 order
   ack below 200 µs at 50k msg/s on the lab host"). If none exists, propose one
   and identify what the initial baseline needs to establish. Record the current
   value and how it was measured.
2. **Classify performance workloads** using `references/triage.md`: fixed-rate latency,
   maximum sustainable throughput, batch completion, startup/warmup, memory
   footprint, or recovery episodes (gap fill, replay, reconnect, catch-up).
   Different classes need different experiments; never derive one from another.
   For an incident, use its failure symptom to select evidence first.
3. **Choose the evidence path.** If the agent can work on the affected host,
   run the `profiling-readiness` skill there. Use the `linux-jvm-debug` skill
   when a guided report or target identity check is useful. If the agent cannot
   access that host, use the `java-offline-capture` skill to build an operator
   kit with check, dry-run, bounded capture, and retrieval steps. Local readiness
   is not evidence of production capabilities. If files or a bundle are already
   available, analyse them first and request only missing evidence. Include
   service journal, systemd, and crash evidence for restarts, OOMs, or crashes.
4. **Broad observation first.** Use existing evidence or collect one bounded,
   low-overhead baseline that separates the big buckets before narrowing:
   - on-CPU application work vs GC vs JIT compilation vs safepoints;
   - off-CPU waiting: locks, I/O, network, scheduler run-queue delay;
   - OS/hardware interference: interrupts, frequency, migrations, throttling;
   - memory: heap occupancy/allocation rate vs native RSS growth;
   - work amplification: requests, round trips, syscalls, or retries per
     logical operation. Count them; a protocol that repeats work is invisible
     to CPU and GC profiles.
   - completeness: operations finished versus operations offered. A stalled
     system can produce good-looking latency for the operations that did finish.
   For a running JVM, select a bounded capture supported by its permissions.
   Launch-time JFR with unified GC and safepoint logging is an alternative for
   a controlled launch on JDK 21 and 25; it is not a reason to restart production.
   For a dead or unresponsive JVM, preserve available logs and host evidence
   rather than requiring a successful attach before proceeding.
5. **Route** with the symptom map in `references/triage.md`. For services in
   containers or Kubernetes, check limits first with `references/containers.md`. Pick one skill and
   one question. Record what result would confirm or reject the hypothesis.
6. **Experiment discipline.** Change one factor, repeat on the same host and
   load, compare against a control, and verify the service metric without
   profiler overhead. Keep an evidence log (`references/evidence-log.md`).
7. **Close.** For a plan, show the leading action, evidence supporting it,
   uncertainty, and the experiment that would confirm or reject the hypothesis.
   Routing hints are not diagnoses. After an investigation, report the confirmed
   cause or an inconclusive result, any change, before/after distributions with
   variance where measured, residual risks, and the rollback. If the
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

When perf or eBPF access is unavailable, use the `java-flight-recorder` skill
if same-user JVM attachment is permitted. If attachment is also blocked, use
existing recordings/logs or plan launch-time JFR on an approved future launch;
do not assume JFR bypasses attachment restrictions.

## Guardrails

- Verify process ownership and start time before and after attachment using
  the selected capture helper; follow its approval and capture limits.
- Never treat missing tools or failed captures as evidence that a problem is absent.
- Do not tune from a single run, an average, or a flame graph alone.
- Do not change production launch flags, kernel settings, or affinity as part
  of triage. Specialised skills own those experiments and their approvals.
- Keep throughput and tail-latency conclusions separate.
- A JMH win is a hypothesis about the service, not proof — verify end to end.
