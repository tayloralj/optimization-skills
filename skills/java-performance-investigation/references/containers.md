# JVMs in containers and Kubernetes

Most "the JVM is slow in the container" problems are resource limits, not code.
Check these before profiling.

## What the JVM sees

HotSpot detects cgroup v1/v2 limits (`-XX:+UseContainerSupport`, on by default):

| Limit | JVM effect | Check |
| --- | --- | --- |
| Memory limit (`memory.max`) | Default max heap = `MaxRAMPercentage` (25%) of the limit | `java -XX:+PrintFlagsFinal -version \| grep -E 'MaxHeapSize\|MaxRAMPercentage'` inside the container |
| CPU quota (`cpu.max`, Kubernetes CPU limit) | `availableProcessors()` derived from the quota, which sizes GC threads, JIT threads, and `ForkJoinPool.commonPool` | `jcmd PID VM.info`, `java -XshowSettings:system -version` |
| cpuset (`cpuset.cpus`, static CPU manager) | Processor count equals pinned CPUs | `/proc/self/status` `Cpus_allowed_list` |

`-XshowSettings:system` prints the detected container limits on Linux.
Override detection explicitly when it is wrong: `-XX:ActiveProcessorCount=N`,
`-XX:MaxRAMPercentage=…` or `-Xmx`.

## CPU limits and latency

A CFS quota (`cpu.max`, Kubernetes `limits.cpu`) lets a container use its
allowance early in each 100 ms period and then throttles it for the rest of the
period. Multi-threaded JVMs (GC, JIT, parallel work) exhaust it quickly, which
produces periodic stalls of tens of milliseconds that look like GC or network
problems.

Evidence: `nr_throttled` and `throttled_usec` in `cpu.stat`, JFR
`jdk.ContainerCPUThrottling` (`jfr view container-cpu-throttling`), and the
`linux-low-latency-tuning` audit (`--pid`).

Options (operator decisions):

- Remove CPU limits and keep requests (common for latency services).
- Kubernetes static CPU manager with Guaranteed QoS and integer CPUs gives
  exclusive cpusets instead of quotas.
- Reduce parallel GC/JIT thread counts to fit the quota, as a measured change.

## Memory limits and OOM kills

The container memory limit must cover the whole native memory ledger, not just
the heap: metaspace, code cache, thread stacks, GC structures, direct and
mapped buffers, and native libraries (the `java-native-memory` skill). A
`MaxRAMPercentage` of 75% is a common starting point for heap-light services;
buffer- and thread-heavy services need more headroom. Check
`memory.events` `oom_kill` and the kernel log for kills; the JVM itself
reports nothing when the kernel kills it.

## Profiling inside containers

- `jcmd`, JFR, and async-profiler need the same PID and mount namespace as the
  JVM: run them inside the container (`kubectl exec`) or use a sidecar that
  shares the process namespace.
- Recordings are written inside the container filesystem; copy them out
  (`kubectl cp`).
- perf and eBPF usually need host access or privileged debugging pods; that is
  an operator decision (see the `profiling-readiness` skill).

## Kubernetes checklist

- [ ] Requests and limits recorded; CPU limit present? throttling observed?
- [ ] Final JVM flags from inside the pod (`jcmd PID VM.flags`)
- [ ] `availableProcessors`, GC and JIT thread counts as the JVM sees them
- [ ] Heap max versus memory limit, with a native-memory ledger for the rest
- [ ] Node noisy neighbours, CPU manager policy, and pod QoS class
- [ ] Readiness gated on JVM warmup for latency services
