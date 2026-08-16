# Java NUMA and affinity reference

## First touch

Linux commonly allocates physical pages according to the policy and CPU that
first faults them. A valid experiment controls which thread initializes memory,
warms every relevant page, and keeps placement stable long enough to measure.
Java heap allocation and GC can redistribute or touch pages, so document the
collector and validate placement rather than assuming application first touch
remains authoritative.

## JVM behaviour

`-XX:+UseNUMA` support and interaction vary by JDK, collector, platform, and
container. Query the installed JVM, for example with
`java -XX:+PrintFlagsFinal -version`, and use current JDK documentation before
changing it. Treat the flag as an experiment requiring a full restart,
representative heap, GC evidence, and rollback.

## CPU sets

Build sets from topology:

- avoid or deliberately pair SMT siblings depending on the hypothesis;
- keep producer/consumer hand-offs within one LLC domain for a locality control;
- compare a deliberate cross-domain placement separately;
- respect cgroup effective cpus and memory nodes;
- record IRQ and co-tenant interference where relevant.

Use `taskset` or service affinity only after resolving explicit CPU IDs. CPU
numbering can differ across machines, BIOS settings, VMs, and container limits.

Distinguish three different interventions:

- Starting the whole JVM under an affinity mask changes the processors visible
  during JVM ergonomics and can reduce GC and compiler thread counts.
- `taskset -a` changes all existing native thread IDs but may miss threads that
  are created or recreated later.
- Pinning named hot Java/native threads can isolate a queue hand-off hypothesis
  while leaving JVM service threads a controlled pool, but requires a maintained
  mapping from Java threads to native TIDs.

Even with `ActiveProcessorCount=-1`, startup affinity can affect ergonomic
choices. Capture final JVM flags, verify native TID affinity after warmup and
thread recreation, and avoid attributing changed GC/compiler parallelism to
cache placement. Useful flag discovery includes:

```bash
java -XX:+PrintFlagsFinal -version 2>&1 | \
  grep -E 'ActiveProcessorCount|CICompilerCount|ParallelGCThreads|ConcGCThreads|Use.*GC'
```

## Deployment

Encode affinity as a validated, host-specific configuration with an automatic
safe fallback when the expected topology is absent. Monitor rejected affinity,
CPU migrations, imbalance, throttling, and tail latency. Test restart,
rescheduling, failover, and capacity loss.
