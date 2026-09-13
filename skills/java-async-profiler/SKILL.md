---
name: java-async-profiler
description: Capture and read async-profiler CPU, allocation, lock, and wall-clock profiles of a JVM safely and within bounds. Use to find where a Java service or JMH benchmark spends time, allocates, or blocks, including on hosts where perf access is restricted.
---

# Java Async Profiler

Capture a bounded, reproducible profile that answers one stated question. Run
the `profiling-readiness` skill first when host permissions are unknown.

## Workflow

1. State the symptom and choose one event:
   - CPU/PMU access available: `cpu`.
   - CPU access blocked: test `ctimer`; use `wall` for blocked, sleeping, and
     end-to-end thread time.
   - Allocation pressure: `alloc`.
   - Contention: `lock`.
2. Confirm the PID, workload phase, duration, output directory, disk budget,
   and data-handling policy. Never profile indefinitely by default.
3. Create an owner-only output directory, then run
   `scripts/capture.sh PID DURATION_SECONDS EVENT OUTPUT`. Use a representative
   steady-state interval and retain the exact command and application revision.
4. Inspect Java, JIT, native, GC, safepoint, and off-CPU frames. Separate
   inclusive time from self time and check whether `[unknown]` frames make the
   result inconclusive.
5. Form one source-level hypothesis, change one factor, and repeat the same
   workload. Do not claim an improvement from a flame graph alone.

## JMH integration

Quote the entire profiler argument because it contains semicolons:

```bash
java -jar benchmarks.jar 'BenchmarkPattern' -prof \
  'async:event=ctimer;output=flamegraph;dir=profiles'
```

Profiler overhead changes the run. Use profiling to locate work, then run an
unprofiled benchmark for the comparison. Artifact count depends on forks and
profiler configuration; do not assume one file per iteration.

## Production capture

Use `scripts/rotating-jfr.sh` only after agreeing a retention count and output
byte ceiling, free-space reserve, duration, and a new private output directory.
It refuses shared/existing directories and bounds both file count and retained
bytes. Its per-capture byte budget is also reserved before each interval and
monitored while the profiler runs. Stop it with `SIGINT`, `SIGTERM`, or `SIGHUP`.

PID attachment requires the profiler and target JVM to share a compatible PID
and filesystem namespace and for the JVM attach mechanism to be enabled. If
attachment fails, do not weaken the host blindly; inspect container namespaces,
`DisableAttachMechanism`, target ownership, and the JVM's attach socket. Prefer a
controlled startup integration when attachment is intentionally disabled.

The helpers accept integer seconds, cap an interval at one hour, refuse output
overwrites and symlinks, use mode `0600` artifacts, and verify the target UID,
Java executable, process start time, and inactive profiler state before starting.
On interruption they stop and verify the session they started; they refuse to
interfere with a pre-existing session. Advanced events and profiler flags stay
manual because they need version-specific validation. They pass a 128 MiB stack
trace-storage limit by default; set `ASPROF_MEMLIMIT_BYTES` to an approved value
up to 2 GiB. This is not a hard JFR file-size limit, so rotating capture also
enforces retained bytes and a free-space reserve. For wall-clock analysis,
consider the installed release's per-thread option (commonly `-t`) so attribution
is retained.

Read `references/events-and-symbols.md` for event fallbacks, JDK native-access
notes, symbols, and privacy. Do not install a downloaded profiler without a
version pin and publisher-provided integrity verification.
