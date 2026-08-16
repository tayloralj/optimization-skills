---
name: java-performance-patterns
description: Convert measured JVM bottlenecks into evidence-backed Java changes involving allocation, atomics, locks, queues, batching, data layout, clocks, copying, I/O, or locality. Use after profiling or a production-faithful benchmark identifies a bottleneck, especially when native C recipes, blanket lock replacements, per-CPU counters, or confident gain estimates would not fit Java thread ownership and GC semantics.
---

# Java Performance Patterns

Select a pattern from evidence and ownership semantics, not from source-code
appearance. Read `references/patterns.md` after identifying a hot operation.

## Workflow

1. State the measured bottleneck, workload type, affected service metric, and
   evidence limitations.
2. Confirm the production concurrency contract and benchmark fidelity.
3. Select the smallest matching Java pattern. Reject patterns whose ownership,
   read/write ratio, ordering, memory-visibility, or failure semantics differ.
4. Write correctness tests for ordering, visibility, overflow, backpressure,
   shutdown, recovery, and error paths before changing the hot path.
5. Benchmark the isolated mechanism and run a representative integration/load
   test. Report raw evidence and variance; do not promise a generic speedup.
6. Retain a rollback and re-profile. If the original bottleneck does not move,
   revert or revise the hypothesis.

## Guardrails

- `LongAdder` is useful for contended multi-writer statistics, not automatically
  for a single-writer exact sequence or strongly consistent gauge.
- A read-write lock is not a universal replacement for a short, write-heavy
  `synchronized` section. An immutable subscriber snapshot may fit read-mostly
  publication better.
- `@Contended` requires compatible JVM flags for application classes and changes
  memory footprint; confirm with JOL and a controlled false-sharing test.
- Pools reduce allocation only when lifecycle, clearing, capacity, and ownership
  are correct. They can retain large objects and increase tail latency.
- Off-heap/direct buffers trade GC pressure for explicit lifetime, bounds,
  native-memory, and observability risks.
- Per-thread or striped counters trade contention for delayed aggregation and
  weaker instantaneous consistency. Document that contract.
