---
name: java-flight-recorder
description: Record and analyse JDK Flight Recorder data with no extra tools and no root - recording settings, jcmd control, jfr view reports, custom events, and streaming. Use for low-overhead evidence on any JVM, when perf or eBPF is not permitted, or to correlate latency with GC, locks, I/O, and allocation.
---

# Java Flight Recorder

JFR ships with every JDK 11+ build, runs inside the JVM, needs no privileges,
and is designed for production overhead. It is the default evidence source
when nothing else is allowed, and a good first look even when everything is.

## Workflow

1. **Choose how to start the recording.**
   - New launch (or restart a replica):
     `-XX:StartFlightRecording=settings=profile,filename=app.jfr,maxsize=512m,maxage=30m`
   - Running JVM owned by you, same host namespace:
     `scripts/jfr-capture.sh PID 120 ./jfr/run1.jfr [profile|default|file.jfc]`
     (bounded duration and retained data; verifies the target and attempts cleanup
     on interruption, reporting any unconfirmed stop). Each `jcmd` has a timeout
     (`JCMD_TIMEOUT_SECONDS`, default 10). A failed check is not proof of completion.
   - Inside a container: run `jcmd` inside the container, then copy the file out.
2. **Pick settings for the question** (`references/jfr-guide.md`): `default`
   for always-on, `profile` for investigations, or a custom `.jfc` built with
   `jfr configure` (for example 1 ms lock and park thresholds for latency work).
3. **Record the right interval**: warmed-up steady state under representative
   load, long enough to include the rare events you care about (GC cycles,
   spikes). Note the wall-clock time of any incident.
4. **Report**: `scripts/jfr-report.sh run1.jfr ./jfr/report --focus latency|cpu|memory|all`
   renders curated `jfr view` tables (JDK 21+ tool) and an index. Missing views
   are listed; failed views or no usable views return non-zero. Inspect the
   index before drawing conclusions from absent events. On older tools
   use `jfr summary` and `jfr print --events TYPE`.
5. **Interpret** with the event map in the reference: pauses (GC, safepoints,
   VM operations), waiting (monitors, parks, sockets, files), CPU (execution
   and CPU-time samples), allocation, deoptimization, and container throttling.
   `allocation-by-site` names only the allocating method. To see which thread
   and call path allocate, run
   `scripts/jfr-alloc-stacks.py run1.jfr --thread '^main$' --depth 5`; it
   separates per-message garbage on a hot thread from start-up or background
   allocation in the same method.
6. **Go deeper or hand off**: GC details to the `java-gc-tuning` skill, JIT to
   `java-jit-codegen`, off-heap to `java-native-memory`, kernel waiting to
   `linux-ebpf-io-network`, and verified latency numbers to
   `java-latency-measurement`.

## JDK 21 vs 25

- JDK 21: `jfr view` and `jcmd PID JFR.view` exist; `jfr configure` exists.
- JDK 25 adds experimental Linux CPU-time sampling
  (`jdk.CPUTimeSample#enabled=true`, view `cpu-time-hot-methods`) that counts
  CPU time, including in native code, rather than execution samples; and method
  timing and tracing without code changes
  (`jdk.MethodTiming#enabled=true,jdk.MethodTiming#filter=com.example.Foo::bar`,
  view `method-timing`).
- Analyse with a `jfr` tool at least as new as the recording JVM.

## Guardrails

- Recordings contain class and method names, thread names, file paths, host
  details, environment variables, and system properties (possibly secrets).
  Store privately; strip before sharing.
- `profile` settings and low thresholds add overhead and file volume; always
  set `maxsize`/`maxage` or a duration.
- Execution samples are biased toward safepoint-friendly locations less than
  classic profilers but still miss time in native code; use CPU-time samples
  (JDK 25) or async-profiler for native-heavy work.
- Starting a recording on production needs approval like any other attach.
