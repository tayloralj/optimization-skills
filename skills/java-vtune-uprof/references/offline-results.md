# Vendor results from an agent-free host

Use the `java-offline-capture` skill for JVM/OS context. Vendor results remain
separate companion artifacts: the current bundle format and analyser do not
parse VTune, uProf, Intel PCM, or AMDuProfPcm output. Do not insert a CSV and
claim that bundle integrity establishes collection or attribution success.

## Operator handoff

1. Confirm tool licensing, installed version, CPU support, and permissions on
   the capture host. The JVM kit does not install or redistribute vendor tools.
2. Prepare a concrete, bounded command from that installed version's help,
   including PID identity checks, collection window, private result directory,
   and finalization deadline. Confirm which launched processes may outlive the
   collector and how the operator will stop only those test processes.
3. Keep the native vendor session intact with JIT mappings and symbol metadata.
   Use the vendor's export/import facility when required. CSV is a readable
   summary, not a replacement for the native result.
4. Include a small companion manifest: tool/version, CPU and JDK, command,
   target identity/start time, UTC boundaries, JVM uptime boundaries if known,
   workload hash, exit codes, completeness, and checksums. Link the companion
   manifest to the JVM bundle checksum; do not imply clock alignment without
   checking time origins and overlapping intervals.
5. Treat classes, source, symbols, command lines, paths, and native result
   metadata as potentially sensitive. The JVM kit's JFR scrubbing and hostname
   redaction do not sanitize vendor artifacts. Review them before transfer.
6. Transfer through the operator's approved channel, verify checksums, and open
   with a compatible vendor analysis tool. Check samples and Java attribution
   before drawing conclusions; an intact failed capture is still failed.

Run profiler-overhead experiments separately from combined JVM-kit captures.
Concurrent JFR, thread dumps, and system counters add overhead and can contend
for PMU resources. A combined diagnostic run cannot serve as an unprofiled control.
