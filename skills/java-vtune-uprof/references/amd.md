# AMD uProf: choose the collection mechanism

Documentation baseline: AMD uProf 5.3, checked 2026-09-14. These are documented
workflows, not locally verified uProf commands. Before capture, check the
installed release's help for every option and configuration; retain that output.

## Compatibility and mode selection

- Confirm the exact CPU family/model and selected analysis, not just the AMD
  brand. Core, IBS, L3, and Data Fabric availability differ.
- The [Java limitations](https://docs.amd.com/r/en-US/57368-uProf-user-guide/8.2.4.-Limitations)
  state Java 11 and newer, Linux-only Java stacks, and one Java target per
  attached agent. This is a vendor support statement, not JDK 21/25 validation
  on our kernel. Do not use thread-ID attachment as a substitute for Java PID attachment.
- Match `JAVA_HOME` and the executable. Use absolute application, classpath,
  tool, and output paths for reliable agent loading, as required by the
  [Java CLI guide](https://docs.amd.com/r/en-US/57368-uProf-user-guide/8.2.2.2.-Using-CLI).
- Distinguish user-mode `hotspots` from perf-backed `tbp`, core PMC, and IBS.
  An installed user-mode collector can be investigated when perf is blocked;
  success must still include usable Java symbols. It does not produce IBS data.

The [perf policy table](https://docs.amd.com/r/en-US/57368-uProf-user-guide/7.1.-Profiling-Support-on-Linux-for-perf_event_paranoid-Values)
distinguishes launch from attach. For example, its IBS launch allowance at value
1 does not extend to IBS attach. Values 3/4 and distribution/container policies
need an actual test; do not extrapolate the table or silently broaden permissions.

## Capture and attribution

1. Inspect installed CLI help, supported configs, Java launch/attach prerequisites,
   and the [Hotspots limitations](https://docs.amd.com/r/en-US/57368-uProf-user-guide/7.5.6.-Limitations).
   Keep user-mode hotspots separate from hardware-counter validation.
2. Start with a self-owned synthetic JVM launch. Use a new private parent
   directory, a bounded collection interval, an outer timeout allowing for
   finalization, and the validation fixture's complete fixed-work output.
3. For an existing JVM, verify UID, executable, start time and namespace before
   and after capture. AMD's [Java stack guide](https://docs.amd.com/r/en-US/57368-uProf-user-guide/8.2.3.4.-Java-Call-Stack-and-Flame-Graph)
   requires `-XX:+PreserveFramePointer` at JVM launch for correct attached stacks.
   Do not restart production to add it without approval. Validate dynamic-agent
   loading for the actual JVM; do not blanket-enable it or assume launch and
   attach have equivalent overhead.
4. Preserve the session directory reported by the collector. Produce the report
   with the installed release's report command and application source path.
   Verify fixture methods, source lines or inline frames, sample counts, and
   the measured interval. Unknown JIT frames are an attribution failure, not
   evidence that Java is idle.
5. If proceeding to IBS, first verify that specific mode/event and record its
   units and denominator. Inspect sampled load latency, cache/TLB behavior, or
   branch data only when supported by that CPU and collection. Keep GC and
   native work separate from application methods.

## System counters

`AMDuProfPcm` is separate from `AMDuProfCLI` and from Intel PCM. Its perf/MSR
modes and supported core/L3/Data Fabric metrics need separate checks. AMD's
5.3 download-page feature table limits Pcm to EPYC processors; do not promise
Pcm support on a Ryzen host merely because AMDuProfCLI supports it. The
[non-root monitoring recipe](https://docs.amd.com/r/en-US/57368-uProf-user-guide/4.11.-Monitoring-Without-Root-Privileges)
uses capability setup for MSR mode; that setup changes privileges. Do not run
the capability script automatically. Route to the `java-hardware-counters`
skill for scope and interpretation.

Download and platform references: [official downloads](https://www.amd.com/en/developer/uprof.html),
[operating systems](https://docs.amd.com/r/en-US/57368-uProf-user-guide/2.2.-Operating-Systems).
Use operator-approved software; do not redistribute the vendor archive in a kit.
