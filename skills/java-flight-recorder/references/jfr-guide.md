# JFR guide

Checked against JDK 25 (Temurin 25.0.2). Confirm event names on the target
with `jfr metadata` and options with `jfr configure` (no arguments lists them).

## Settings

| Settings | Use | Notes |
| --- | --- | --- |
| `default` | Always-on production recording | Low overhead; thresholds of 20 ms for locks and I/O |
| `profile` | Time-boxed investigation | More sampling and allocation data; higher overhead |
| Custom `.jfc` | A specific question | Build with `jfr configure`; version-control it |

Low-latency investigation settings (lower thresholds so short stalls appear):

```bash
jfr configure --input profile \
  gc=detailed locking-threshold=1ms \
  jdk.FileWrite#threshold=1ms jdk.FileRead#threshold=1ms \
  jdk.SocketRead#threshold=1ms jdk.SocketWrite#threshold=1ms \
  --output latency.jfc
```

`jfr configure` options on JDK 25 include `gc`, `allocation-profiling`,
`compiler`, `method-profiling`, `thread-dump`, `exceptions`, `memory-leaks`,
`locking-threshold`, `method-timing`, `method-trace`, and `class-loading`. Any
event setting can be passed as `event#setting=value`.

## Control a running JVM

```bash
jcmd PID JFR.start name=inv settings=profile duration=120s maxsize=256M filename=/abs/inv.jfr
jcmd PID JFR.check                 # list recordings
jcmd PID JFR.dump name=inv filename=/abs/snapshot.jfr   # copy data so far
jcmd PID JFR.stop name=inv
jcmd PID JFR.view gc-pauses        # JDK 21+: query the live in-memory recording
```

A continuous `default` recording with `maxage` (for example 30 m) plus
`JFR.dump` after an incident gives "flight data" from before the problem.

## Event map

| Question | Events | `jfr view` |
| --- | --- | --- |
| GC pauses | `jdk.GarbageCollection`, `jdk.GCPhasePause`, `jdk.GCHeapSummary` | `gc-pauses`, `gc`, `gc-pause-phases` |
| Safepoints / VM operations | `jdk.SafepointBegin`, `jdk.ExecuteVMOperation` | `safepoints`, `vm-operations` |
| Lock contention | `jdk.JavaMonitorEnter`, `jdk.JavaMonitorWait`, `jdk.ThreadPark` | `contention-by-site`, `contention-by-class` |
| Slow I/O | `jdk.FileRead/Write`, `jdk.FileForce`, `jdk.SocketRead/Write` | `latencies-by-type`, `file-writes-by-path`, `socket-reads-by-host` |
| CPU hot spots | `jdk.ExecutionSample`, `jdk.CPUTimeSample` (JDK 25) | `hot-methods`, `cpu-time-hot-methods` |
| Allocation | `jdk.ObjectAllocationSample` | `allocation-by-site`, `allocation-by-class` |
| Leak candidates | `jdk.OldObjectSample` | `memory-leaks-by-site` |
| JIT | `jdk.Compilation`, `jdk.Deoptimization`, `jdk.CodeCacheFull` | `deoptimizations-by-reason`, `longest-compilations` |
| Virtual threads | `jdk.VirtualThreadPinned` | `pinned-threads` |
| Containers | `jdk.ContainerCPUThrottling`, `jdk.ContainerMemoryUsage` | `container-cpu-throttling` |
| Native memory (NMT on) | `jdk.NativeMemoryUsage` | `native-memory-committed` |
| Method timing (JDK 25) | `jdk.MethodTiming`, `jdk.MethodTrace` | `method-timing`, `method-calls` |

## Custom events for request latency

```java
@Name("app.OrderAck")
@Label("Order ack")
@Threshold("1 ms")          // only record slow operations
@StackTrace(false)
final class OrderAckEvent extends jdk.jfr.Event {
    @Label("Order id") long orderId;
}

OrderAckEvent event = new OrderAckEvent();
event.begin();
// ... handle the order ...
event.orderId = id;
event.commit();             // cheap when disabled or below threshold
```

On a hot path, check `event.shouldCommit()` before filling expensive fields,
and verify the steady-state cost with JMH `-prof gc` (event objects can be
scalar-replaced, but confirm).

## Streaming

`jdk.jfr.consumer.RecordingStream` (in-process) and `EventStream.openRepository`
(out-of-process, same host) deliver events with roughly one-second latency, for
live dashboards or alerting on long pauses. Keep handlers cheap and off the
latency-critical threads.

## Reading results correctly

- Views summarise the whole recording; use `jfr print --events TYPE` with
  timestamps to align a specific spike.
- Sampled events show where time is likely spent, not exact counts.
- A quiet `contention-by-site` at 20 ms thresholds does not mean no contention;
  lower the threshold.
- Recording start and stop add small safepoints; do not read them as
  application behaviour.
