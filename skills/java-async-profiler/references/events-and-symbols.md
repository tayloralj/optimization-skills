# Events, symbols, and evidence quality

## Event choice

- `cpu` normally uses perf-event CPU sampling on Linux and may be blocked by host
  policy; it is not automatically a hardware-counter experiment. Smoke-test it
  and do not infer access from `perf_event_paranoid` alone.
- `ctimer` is a useful CPU-time fallback on supported async-profiler releases.
- `wall` samples elapsed thread time and is appropriate for blocking or mixed
  on/off-CPU investigations. It answers a different question from CPU time.
- `alloc` samples allocation activity, not retained heap. Use a heap dump or
  GC/heap tooling for retention.
- `lock` points to contention; validate whether the sampled locks matter at the
  service-level load and latency target.

JDK 25 also offers experimental JFR CPU-time sampling on Linux
(`jdk.CPUTimeSample`), a JVM-native alternative when attaching a profiler is
not permitted; confirm with `jfr metadata` on the target JDK.

Run `asprof list PID` or the installed release's help to confirm event support.
Do not copy an event name from another CPU or profiler without checking it.

## Java and native symbols

Warm the workload before capture so interpreted startup code does not dominate.
Preserve debug packages or symbols for native libraries when native frames are
material. For JIT frames, async-profiler normally obtains JVM symbols directly;
Linux `perf` has a separate jitdump/perf-map workflow.

Recent JDKs can warn about restricted native access. Where the profiler's
documented integration requires it, add
`--enable-native-access=ALL-UNNAMED` to a controlled JVM launch and record that
change. Do not restart a production JVM solely to suppress a warning.

## Privacy

Profiles can reveal class names, tenants, SQL, file paths, native libraries,
host layout, and command-line data. Store artifacts with production diagnostic
data controls. Redact before sharing publicly.
