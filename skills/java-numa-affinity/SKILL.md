---
name: java-numa-affinity
description: Design safe NUMA, CPU-pinning, SMT, and cache-domain placement experiments for Java. Use when testing thread pinning, numactl, UseNUMA, or scaling across cores, including single-socket AMD machines with several cache domains.
---

# Java NUMA and Affinity

Do not start with `numactl`. First determine whether the host has multiple NUMA
nodes and how cores, SMT siblings, and LLC domains map to CPU IDs.

## Workflow

1. Run the `profiling-readiness` skill; then inspect `lscpu -e` and `lstopo` when
   available. Record cgroup/cpuset limits because visible host CPUs may not be
   usable by the process.
2. If there is one NUMA node, stop the remote-memory experiment. Reframe the
   question as core, SMT-sibling, migration, or LLC/CCD placement.
3. Classify the workload. For fixed-rate load, compare latency, CPU, and
   scheduling at the same offered rate. For scaling, measure maximum sustainable
   throughput and saturation independently.
4. Build topology-aware CPU sets from actual core/sibling/cache lists. Do not
   assume `0-N` selects physical cores before SMT siblings or stays within one
   cache domain.
5. Record `Runtime.availableProcessors`, `ActiveProcessorCount`,
   `CICompilerCount`, `ParallelGCThreads`, `ConcGCThreads`, collector, and
   compilation state for every placement. Process-wide affinity at JVM startup
   can change JVM ergonomics and confound a locality result.
6. Establish a control, then change one factor: thread affinity, memory policy,
   first touch, or JVM NUMA/GC behaviour. Obtain operator approval before
   changing a service launch or host policy.
7. Warm the JVM and memory, run multiple repetitions, and measure application
   output plus migrations, context switches, GC, counters, and variance.
8. Verify recovery/failover and operational deployment: affinity must degrade
   safely when CPU IDs or container limits differ.

## Correct command semantics

Use `numactl --localalloc`, not the invalid `--membind=local`. Numeric binding
requires a node ID, for example `--membind=0`. Query `numactl --hardware` and the
installed help before composing a command. Read `references/java-numa.md` for
first touch and JVM caveats.

## Related skills

CPU isolation, IRQ placement, idle states, and the jitter audit live in the
`linux-low-latency-tuning` skill; measure placement effects with the
`java-latency-measurement` skill.

## Guardrails

- Do not quote a universal remote-memory penalty; measure this CPU and workload.
- Do not use `clock()` or one short run as a latency benchmark. Use JMH or a
  steady monotonic service benchmark with warmup and repetitions.
- NUMA counter names are model-specific. List and validate events on the host.
- Pinning can worsen pauses, interrupt handling, failover, and co-tenancy.
  Always retain an unpinned rollback configuration.
