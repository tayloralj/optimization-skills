---
name: java-vtune-uprof
description: Profile Java with Intel VTune or AMD uProf, choosing the right tool for the CPU and keeping JIT symbols and GC context. Use when vendor-profiler evidence is wanted on an Intel or AMD host.
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
   policy. Read `references/tool-setup.md` for approved user-local setup and
   installation checks. Existing approval covers that setup; do not ask again.
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
   Read `references/intel.md` for VTune or `references/amd.md` for uProf before
   choosing collection mode: user-mode hotspots, timer sampling, and PMU/IBS
   collection have different requirements. A blocked perf test does not by
   itself prove user-mode sampling is unavailable.
5. Confirm whether the selected analysis supports launch or attach in this
   release. Set an explicit duration and private result directory, then capture
   JDK/JVM/workload metadata.
   Any PID shown in examples, including `12345`, is a placeholder. Never attach
   to it as a first step. Discover the real target on the current host (for
   example with `pgrep -a java` or the project's service status), ask the
   operator to identify the intended JVM when more than one candidate exists,
   then verify its owner, executable, start time, and namespace immediately
   before profiling. Prefer a self-owned launch for the first validation.
6. Warm the JVM, collect a bounded steady-state interval, and preserve JIT,
   GC, safepoint, thread, and native symbol context. Prefer a replica or
   controlled load; obtain approval before attaching to production.
7. Verify artifact completeness and representative Java/native symbol resolution.
   Reject unresolved captures before source changes.
8. Interpret vendor metrics relative to a same-host baseline and workload.
   Fixed “healthy” thresholds are not portable across microarchitectures.
9. Apply one change and verify with an unprofiled representative test.

## Validate a new host or tool version

Use `scripts/VendorWorkload.java`, a synthetic fixed-work fixture for allocation,
branching, streaming reads, and dependent memory reads. It runs with the JDK
source launcher and no dependencies. It is not a JMH replacement or a service
latency benchmark. Read `references/validation.md` for bounded commands,
measurement-window checks, overhead comparisons, and acceptance criteria.
For repeated fixed-work comparisons, use `scripts/profile-compare.py`; read
`references/comparison-runner.md` before using it.
Before interpreting a vendor or perf export, use `scripts/validate-symbols.py`
and read `references/symbol-validation.md` to check Java/JIT attribution.
For repeatable JDK coverage, run `scripts/compatibility-matrix.py` and read
`references/compatibility-matrix.md`; a verified fixture run does not certify
vendor-profiler or PMU support.

For a single preflight that does not invent vendor flags, run
`scripts/vendor-readiness.py [--json]`. It reports the detected CPU vendor,
kernel, PMU event sources, perf policy, and installed VTune/uProf/PCM binaries;
use the selected tool's own help before launching a capture.

For a bounded operator-approved vendor command, use
`scripts/vendor-capture.sh --tool NAME --out DIR --duration SEC -- COMMAND...`.
The wrapper records environment and tool version, enforces a wall-clock bound,
keeps output private, and preserves the vendor's own exit status without
guessing release-specific analysis flags.

For socket/channel bandwidth or other system counters, use the
`java-hardware-counters` skill. Intel PCM and AMD `AMDuProfPcm` are different
tools; neither supplies Java method attribution by itself.

For hosts without an agent, read `references/offline-results.md`: preserve the
vendor's native result and JIT metadata alongside the offline JVM bundle. The
existing bundle analyser does not parse or certify vendor profiler results.

## Java-specific checks

Confirm that hot Java methods resolve rather than collapsing into anonymous JIT
code. Separate compilation/startup, GC, safepoints, native downcalls, blocking,
and application work. Record collector, heap sizing, compilation state, and
container CPU/memory limits. Read `references/vendor-and-jvm.md` before using a
model-specific metric.
