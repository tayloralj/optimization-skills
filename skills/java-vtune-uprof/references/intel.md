# Intel VTune: Java and hardware evidence

Documentation baseline: [VTune 2026.1 user guide](https://www.intel.com/content/www/us/en/docs/vtune-profiler/user-guide/2026-1/overview.html),
checked 2026-09-14. VTune 2026.4 CLI installation and software-sampling options
were checked on an Intel KVM guest; collection exited 1 because its
`ptrace_scope=1` policy blocks this collector. Java attribution remains unverified.
Confirm the installed release's CPU, kernel, driver, and JDK requirements.

## Choose an analysis

| Question | Starting analysis to verify in installed help | Evidence needed |
| --- | --- | --- |
| Which Java/native methods consume CPU? | Hotspots | Resolved JIT methods, stacks, representative interval |
| Why does hot code use the CPU inefficiently? | Microarchitecture Exploration | Supported PMU events, model-specific metric definitions, collection quality |
| Is memory access limiting the workload? | Memory Access | Hot loads/functions, relevant cache/DRAM metrics and workload scaling |
| Is this a system bandwidth or interconnect problem? | Intel PCM via the hardware-counters skill | Correct socket/channel scope and background traffic control |

Hotspots has user-mode and hardware sampling mechanisms. A user-mode result
does not validate PMU access. Hardware collection and stack collection have
additional requirements; driverless operation is not synonymous with permission
to collect. Do not install a driver or alter host policy just because an analysis
fails. On AMD, use the AMD runbook for microarchitecture evidence.

## Java collection

The [Java analysis guide](https://www.intel.com/content/www/us/en/docs/vtune-profiler/user-guide/2026-1/java-code-analysis.html)
describes JIT-aware attribution and mixed Java/native stacks. Preserve the JIT
mapping data and application classes/source when moving results between hosts.
Do not force native-only collection and then interpret unresolved Java addresses
as application hotspots.

The guide explicitly limits managed-code system-wide profiling and treats source
line attribution as approximate. Some examples suggest `-Xcomp` or historical
JVM flags: do not copy them blindly onto JDK 21/25. Verify availability locally
and keep any diagnostic-only flag changes out of performance comparisons unless
both arms use them. Compilation-mode changes can materially alter timing.

1. Start with a bounded launch of the synthetic fixture, compiled with debug
   information. Record JDK build and profiler release; test JDK 21 and 25
   independently. Read `references/validation.md` for the fixture protocol.
2. Check installed help for the selected analysis, duration, output directory,
   and launch/attach mode. Use a unique result directory under a private parent.
   Duration limits collection; include finalization in the outer deadline and
   check whether the launched JVM exits when collection stops.
3. Use the measured uptime window to exclude class loading, fixture setup,
   and warmup. A configured warmup duration alone does not prove C2 stability.
4. Confirm successful collection and finalization, nonempty samples, and Java
   methods or inline frames in the selected interval before interpreting metrics.
5. Run one hardware hypothesis at a time. Use documented event meanings for
   the detected family/model from [Intel PerfMon](https://perfmon-events.intel.com/).
   Do not apply raw encodings or top-down thresholds from another CPU.

On hybrid Intel processors, record the core type and placement. Do not pool
unlike core types into a single unexplained IPC or top-down comparison. Preserve
SMT, affinity, frequency, and workload settings across repetitions.

## Virtual machines

An Intel model string in a guest is not proof of host silicon identity or PMU
availability. Inspect virtualization type, `/sys/bus/event_source/devices`, and
the exact bounded event test. Core vPMU exposure and guest perf permissions are
separate prerequisites. Lowering `perf_event_paranoid` cannot create a missing
virtual PMU. The [KVM guide](https://www.intel.com/content/www/us/en/docs/vtune-profiler/user-guide/2023-0/on-kvm-project-system.html)
describes the host/guest requirements; check the installed release's equivalent.

User-mode Java hotspot validation may still be possible with a suitable JDK and
VTune installation. Keep that result distinct from hardware analysis. Intel
PCM's [VM guidance](https://github.com/intel/pcm/blob/master/doc/FAQ.md) limits
guest results to exposed vPMU metrics. Socket/channel/uncore claims require
their own host-side evidence, not merely successful guest core counters.

## Installed CLI trial (2026.4)

`vtune -help collect hotspots` lists `sampling-mode=sw` and
`enable-characterization-insights=false`. The latter avoids requesting additional
hardware counting in this software-only test. After compiling the fixture as in
`references/validation.md`, the checked command shape is:

```bash
timeout --kill-after=5s 60s "$VTUNE" -collect hotspots \
  -knob sampling-mode=sw -knob enable-characterization-insights=false \
  -result-dir "$vendor_run/vtune-result" -- "$JAVA_HOME/bin/java" \
  -Xms256m -Xmx256m -XX:+PreserveFramePointer \
  -cp "$vendor_run/classes" VendorWorkload chase 30000 2000 64
```

Set `VTUNE` to the installed absolute executable and `JAVA_HOME` to the tested
JDK. This is a verified invocation, **not a successful capture** on the tested
VM. VTune rejected the Yama ptrace policy before collecting. Read
`/proc/sys/kernel/yama/ptrace_scope` as well as perf policy; software sampling
still has access requirements. Do not automatically apply the sysctl changes
suggested in the error message. Stop and retain the failed log. Use a verified
JFR workflow while a separate operator-reviewed permission plan is considered.
