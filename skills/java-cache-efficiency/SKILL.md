---
name: java-cache-efficiency
description: Diagnose and verify Java cache locality, false sharing, object and array layout, queue placement, buffer copying, and LLC or CCD effects with JOL, JMH, perf c2c, PMU counters, and topology evidence. Use when a JVM workload appears memory-latency or coherence bound and C structs, compiler builtins, or native padding examples would not describe Java objects and GC behaviour.
---

# Java Cache Efficiency

Do not recommend a cache fix until evidence exists. If evidence is absent,
design a faithful benchmark or collection first; source adjacency is not proof.

## Workflow

1. Record object ownership, writers/readers, update rate, allocation lifecycle,
   queue/buffer capacity, payload distribution, and CPU/LLC topology.
2. Inspect actual layout with JOL on the same JDK configuration. If JOL is not
   available, report layout verification as blocked and use an organisation-approved,
   project-scoped dependency; do not estimate offsets. Account for
   object headers, compressed references, alignment, inheritance, arrays, and
   JVM flags. Do not infer offsets from source order alone.
3. Establish evidence with a production-faithful JMH test, hardware counters,
   or `perf c2c`. For Java c2c, combine addresses with allocation/layout and
   thread-ownership evidence because GC can move objects.
4. Select one candidate from `references/java-layout-patterns.md` and preserve
   memory-visibility, ordering, capacity, and backpressure semantics.
5. Verify layout again, run repeated benchmarks, and then test the service-level
   throughput/tail-latency metric. Include memory-footprint and GC effects.

## Topology

One NUMA node can contain multiple last-level-cache domains, such as AMD CCDs.
Cross-domain hand-off can matter even when remote NUMA memory is impossible.
Use sibling/core/cache CPU lists rather than a numeric `taskset 0-N` range.

## Guardrails

- `@Contended` is not active for arbitrary application classes unless the JVM
  configuration permits it. Verify the layout and footprint.
- Manual padding is JVM-layout dependent and can be defeated by inheritance or
  future changes; test it rather than counting source fields.
- Prefetching, off-heap buffers, and huge pages are specialised experiments,
  not default fixes. Java has no direct equivalent of blindly copying a C
  `__builtin_prefetch` recipe.
- A larger ring or pool can retain tens or hundreds of MiB. Calculate capacity
  times per-slot footprint and maximum payload before changing it.
