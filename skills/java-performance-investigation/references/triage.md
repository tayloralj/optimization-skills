# Triage: workload classes and symptom routing

## Workload classes

| Class | Question | Load model | Primary metric |
| --- | --- | --- | --- |
| Fixed-rate latency | Is latency acceptable at the expected rate? | Open loop, constant or recorded arrival schedule | Latency percentiles from intended start time, error rate |
| Max sustainable throughput | What rate still meets the SLO? | Stepped open-loop rates until the SLO breaks | Highest rate meeting SLO; saturation point |
| Batch completion | How long does fixed work take? | Run to completion | Wall time, CPU time, variance |
| Startup / warmup | How fast to first useful work / steady state? | Repeated cold starts | Time to first request, time to p99 stability |
| Footprint | How much memory/CPU at steady state? | Representative load | RSS, heap after GC, native categories, CPU |
| Recovery episodes | Does recovery from faults (loss, disconnect, restart) finish, and what does it cost live traffic? | Open-loop live feed plus a seeded fault schedule, including back-to-back faults; sweep rate and RTT | Stalled episodes, requests per episode, detection and repair time per fault size, live latency during episodes |

A closed-loop "as fast as possible" run is neither a latency test nor a
sustainable-throughput test: its latencies hide queueing (coordinated omission)
and its throughput ignores the SLO.

## Baseline capture (no host privileges)

JDK 21 and 25, controlled launch or restart of a replica:

```bash
-Xlog:gc*,safepoint:file=gc.log:time,uptime,level,tags:filecount=5,filesize=50m
-XX:StartFlightRecording=settings=profile,filename=baseline.jfr,maxsize=512m,maxage=30m
```

For an already-running JVM owned by the same user, `jcmd PID JFR.start
settings=profile duration=120s filename=...` avoids a restart, subject to the
attach checks in the `java-async-profiler` skill. Summarise with
`jfr summary` and `jfr print --events <event>`; the `java-gc-tuning` skill ships
a GC and safepoint log summariser.

## Symptom map

| Symptom / first evidence | Next skill | First question |
| --- | --- | --- |
| p99/p99.9 spikes, periodic stalls | `java-latency-measurement` then `java-gc-tuning` | Are spikes real (CO-free) and do they align with GC/safepoint pauses? |
| Spikes not aligned with JVM pauses | `linux-low-latency-tuning`, `linux-ebpf-io-network` | Is the hot thread off-CPU, preempted, interrupted, or waiting on I/O? |
| High CPU, throughput plateau | `java-async-profiler` (cpu/ctimer) | Which frames own on-CPU time at the saturation point? |
| High `jdk.ExecutionSample` in GC threads, high allocation rate | `java-gc-tuning`, `java-async-profiler` (alloc) | Which sites allocate, and is the collector sized for the rate? |
| Performance drops after minutes/hours, or after a deploy | `java-jit-codegen` | Deoptimization, code cache full, megamorphic call sites, or profile pollution? |
| Slow warmup / startup | `java-jit-codegen` | Class loading/linking vs interpretation vs compilation queue? |
| RSS grows while heap is flat; container OOM kill | `java-native-memory` | Which NMT category or non-NMT mapping grows? |
| Heap after GC grows | `java-gc-tuning` (retention section) | What retains it? Heap histogram/dump under approval |
| Crash, restart, or exited JVM | `java-offline-capture` | What do the service journal, OOM records, and JVM crash files establish about the failure window? |
| Hung or unresponsive JVM | `java-offline-capture`, then `java-async-profiler` if attach works | What do bounded thread dumps and host wait states show without requiring a responsive JVM? |
| Lock contention, many threads blocked | `java-async-profiler` (lock, wall) | Which monitor, what hold time, at what load? |
| fsync/journal/disk latency, page faults | `linux-ebpf-io-network` | Which syscalls or block I/O dominate tail latency? |
| Network latency, UDP loss, retransmits | `linux-ebpf-io-network` | Drops, buffer overflow, interrupt coalescing, or application backlog? |
| IPC low, cache/branch misses suspected | `java-hardware-counters`, `java-cache-efficiency` | Which PMU evidence supports a memory-bound hypothesis? |
| Scaling stops beyond N threads | `java-numa-affinity`, `java-async-profiler` (lock) | Contention, SMT, cache domains, or GC/JIT thread starvation? |
| No perf/eBPF/root access at all | `java-flight-recorder` | What do a `profile` recording's latency, CPU, and memory views show? |
| Garbage or contention on a latency-critical hot path | `java-low-latency-patterns` | Which allocation or shared write does the evidence point to, and which pattern removes it? |
| Periodic stalls in containers | `java-performance-investigation` (`references/containers.md`) | Is the CFS quota throttling the JVM? |
| Client stops delivering or falls behind after message loss | `java-latency-measurement` (its recovery-episodes reference) | Does every episode complete? Count delivered versus sent before reading any percentile |
| Recovery slow, or repair traffic grows with rate or RTT | `java-latency-measurement` (its recovery-episodes reference) | How many requests or round trips does one episode take, and does it change with RTT? |
| Micro-optimisation proposal | `java-jmh-benchmarking`, `java-performance-patterns` | Does a production-faithful benchmark show it, and does the service agree? |

## USE-style checklist for the host

For CPU, memory, disk, network, and the JVM's own resources (heap, metaspace,
code cache, thread pools, queues), check Utilisation, Saturation, and Errors
before profiling code. Saturation signals include run-queue length and delay,
`cpu.stat` throttling in cgroups, swap/major faults, disk queue depth, socket
buffer overflow, and bounded-queue rejections.
