---
name: java-vtune-uprof
description: Vendor-aware Java profiling with Intel VTune or AMD uProf, including tool and permission preflight, JVM warmup, JIT symbols, GC and safepoint context, bounded collection, and portable interpretation. Use when a JVM workload needs vendor profiler evidence and CPU-specific analysis names, top-down thresholds, roofline assumptions, or download commands must not be copied across Intel and AMD systems.
---

# Java VTune and uProf

Choose the tool from the actual CPU and installed software. Do not force Intel
analysis terminology onto AMD PMUs or vice versa.

## Workflow

1. Run the `profiling-readiness` skill. Record CPU vendor/model, kernel, tool version,
   permissions, topology, JDK, JVM flags, and workload revision.
2. Select Intel VTune for a supported Intel host and AMD uProf for a supported
   AMD host. If neither tool is installed, do not invent a download URL or CLI;
   use the vendor's current official documentation and organisation package
   policy.
3. If neither vendor tool is installed, route to a verified JFR or
   async-profiler workflow rather than blocking the whole investigation. Query
   an installed tool's help and available analysis types. Names and
   options vary by release:

   ```bash
   vtune --version
   vtune -help
   AMDuProfCLI --version
   AMDuProfCLI --help
   ```

4. Start with a broad hotspot/CPU assessment that the installed tool lists.
   Use memory, cache, branch, or concurrency analysis only when the broad run
   supports that question. Roofline is appropriate for compute kernels, not by
   default for network, journal, queue, or latency services.
5. Confirm whether the selected analysis supports launch or attach in this
   release. Set an explicit duration and private result directory, then capture
   JDK/JVM/workload metadata.
6. Warm the JVM, collect a bounded steady-state interval, and preserve JIT,
   GC, safepoint, thread, and native symbol context. Prefer a replica or
   controlled load; obtain approval before attaching to production.
7. Verify artifact completeness and representative Java/native symbol resolution.
   Reject unresolved captures before source changes.
8. Interpret vendor metrics relative to a same-host baseline and workload.
   Fixed “healthy” thresholds are not portable across microarchitectures.
9. Apply one change and verify with an unprofiled representative test.

## Java-specific checks

Confirm that hot Java methods resolve rather than collapsing into anonymous JIT
code. Separate compilation/startup, GC, safepoints, native downcalls, blocking,
and application work. Record collector, heap sizing, compilation state, and
container CPU/memory limits. Read `references/vendor-and-jvm.md` before using a
model-specific metric.
