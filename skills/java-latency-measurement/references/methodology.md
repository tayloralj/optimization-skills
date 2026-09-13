# Latency methodology reference

## Coordinated omission

When a request stalls, a closed-loop client stops sending, so the samples that
would have observed the stall are never taken. Symptoms: p99 close to median
despite known pauses, max much larger than p99.9 with few samples between.

Fixes, best first:

1. Open-loop generation with a precomputed schedule; measure from intended
   start. Latency tools such as wrk2 (`-R`), k6 `constant-arrival-rate`, and
   Gatling open injection models follow this pattern; verify the version's
   semantics.
2. Inside a Java harness, send from a schedule and record `end - intended`.
3. As a fallback for recorded service times only, HdrHistogram
   `recordValueWithExpectedInterval` back-fills missing samples; it assumes a
   known constant interval and is an approximation.

## HdrHistogram usage

- Size `highestTrackableValue` above the worst plausible stall (for example
  one minute in ns) and choose 2–3 significant digits.
- Record into a per-thread or single-writer histogram; swap via interval
  recorders (`Recorder`/`SingleWriterRecorder`) to avoid locking the hot path.
- Persist interval logs (`HistogramLogWriter`) for time-series analysis and
  merge intervals with `add` for totals.
- Report the recorded count with every percentile.

## Sample size and percentiles

For a percentile p, the tail contains roughly `n × (1 − p)` samples:

| Percentile | Tail samples at n = 1e5 | at n = 1e6 | at n = 1e7 |
| --- | --- | --- | --- |
| p99 | 1,000 | 10,000 | 100,000 |
| p99.9 | 100 | 1,000 | 10,000 |
| p99.99 | 10 | 100 | 1,000 |

Treat any percentile with fewer than about 100 tail samples as indicative.
Longer runs also sample more rare events (GC cycles, cron jobs, compaction).

## Comparing runs

- Alternate or randomise baseline and candidate across several repetitions
  on the same host; thermal and background drift are real.
- Compare distributions per repetition, then the spread across repetitions.
  `latency-report.py` splits one run into equal-count blocks to expose
  episodic stalls versus a uniform shift.
- A uniform shift in all percentiles suggests code-path cost; a change only in
  the far tail suggests pauses or interference; a change in only a few blocks
  suggests an episodic event — align with GC, JIT, and OS timelines.
- Report effect size with its variability, not a single ratio.

## Throughput versus latency

Plot latency percentiles against offered rate. Maximum sustainable throughput
is the highest rate where the SLO holds for the full duration without queue
growth. Report the knee, not the saturation throughput of a closed loop.

## Clocks and timestamps

- `System.nanoTime` is monotonic within a JVM; its cost depends on the
  clocksource (TSC via vDSO is fast; HPET/ACPI PM are slow syscalls).
- Cross-process on one host: `CLOCK_MONOTONIC` is shared, so nanoTime values
  are comparable on Linux HotSpot, but verify for your JVM/OS before relying on
  it. Cross-host: PTP-disciplined clocks or hardware timestamps; state error.
- Timestamp as close to the wire as possible (kernel or NIC timestamps via
  `SO_TIMESTAMPING` are outside plain Java APIs; capture tools can supply them).

## Platform jitter meter notes

- `--mode spin` gaps include every preemption, interrupt, SMI, safepoint, and
  GC pause affecting that thread; compare pinned-isolated versus shared CPUs.
- `--mode sleep` overshoot includes timer slack (default 50 µs for normal
  threads; real-time threads have none) plus idle-state exit latency, so ~50 µs
  medians are expected on an untuned host.
- Percentiles are histogram bucket upper bounds (about 3% resolution).
- Worst events carry JVM uptime to align with `-Xlog` uptime decorators.

## JFR for latency correlation

Useful events: `jdk.GCPhasePause`, `jdk.SafepointBegin`, `jdk.Deoptimization`,
`jdk.ThreadPark`, `jdk.JavaMonitorEnter`, `jdk.SocketRead`/`jdk.SocketWrite`,
`jdk.FileWrite`/`jdk.FileForce`, `jdk.VirtualThreadPinned`. Define custom JFR
events around request stages with a threshold so only slow operations are
recorded. JDK 25 adds experimental Linux CPU-time sampling
(`jdk.CPUTimeSample`) and method timing/tracing events; check `jfr metadata`
on the target JDK.
