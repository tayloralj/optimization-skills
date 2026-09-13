---
name: java-performance-patterns
description: Turn a measured JVM bottleneck into a verified code change involving allocation, locks, atomics, queues, batching, copying, clocks, or I/O. Use after profiling or a faithful benchmark has identified the hot spot.
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

## Related skills

Route GC- and allocation-rate problems to the `java-gc-tuning` skill,
inlining and deoptimization to `java-jit-codegen`, off-heap and RSS growth to
`java-native-memory`, and latency verification to `java-latency-measurement`.

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
