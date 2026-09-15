# Intel PCM and AMD system counters

These complement Java method profiles. They do not replace them. The similarly
named tools are not interchangeable, and support is metric- and CPU-specific.
Documentation checked 2026-09-14. Intel PCM 202502-1build2 starts on the
tested KVM guest but exits 1: vPMU is disabled and MSR/PCI access is unavailable.
No successful PCM capture is validated. AMD lists Pcm as an EPYC feature in its
[5.3 feature table](https://www.amd.com/en/developer/uprof.html); Ryzen support
for the main uProf profiler does not establish Pcm support.

| Tool | Use | Do not infer |
| --- | --- | --- |
| Intel PCM / pcm-memory | Supported Intel system/core counters and memory-channel bandwidth | Every Intel client CPU exposes the Xeon uncore metrics |
| Intel pcm-numa / pcm-pcie / pcm-iio | Supported memory-locality or I/O questions | Availability or meaning is portable across Intel generations |
| AMD AMDuProfPcm | Supported AMD core, L3, Data Fabric and memory metrics | It is Intel PCM, or it attributes traffic to a Java method |
| AMD AMDuProfCLI | Sample-based CPU/IBS attribution | A successful CPU profile proves Pcm's system counters work |

Tool purposes and current support: [Intel PCM project](https://github.com/intel/pcm),
[AMD Pcm overview](https://docs.amd.com/r/en-US/57368-uProf-user-guide/4.1.-Overview).

## Minimal experiment

1. Identify CPU family/model and the exact question: bandwidth saturation,
   remote memory, cache contention, or frequency. Read installed help for the
   relevant executable and confirm its metric supports that hardware.
2. Identify the access mechanism (perf, MSR, PCI, or driver). Do not run vendor
   setup/capability scripts, load modules, disable Secure Boot, or write MSRs
   automatically. A tool advertised as non-root may require privileged setup.
   Do not use PCM's register-write utilities as profiling helpers.
3. Specify whether data covers a thread, core, socket, channel, or whole system.
   Record other workloads and sampling intervals. For uncore memory traffic,
   controlling background activity is required for a useful comparison; placing
   a JVM PID in a command does not isolate all observed bytes to the JVM.
4. Collect a short idle/control interval, then the fixed workload with the same
   interval and scope. Keep raw data, units, supported-counter status, and elapsed
   time. For rates, check byte-vs-cache-line and decimal-vs-binary conversions.
5. Compare measured bandwidth with a separately measured same-host sustainable
   baseline if saturation is the hypothesis. A percentage of theoretical DIMM
   bandwidth alone is not a performance diagnosis. Low bandwidth can coexist
   with latency-bound dependent reads.
6. Coordinate with perf/VTune/uProf: simultaneous collectors can compete for
   counters. Prefer separate matched runs unless coexistence was verified.

AMD's [MSR-mode non-root recipe](https://docs.amd.com/r/en-US/57368-uProf-user-guide/4.11.-Monitoring-Without-Root-Privileges)
uses capability setup; do not mistake that for unchanged host permissions.
Intel's [PCM FAQ](https://github.com/intel/pcm/blob/master/doc/FAQ.md) explains
hardware/access limitations. Stop at the specific unsupported metric rather
than weakening platform policy to chase an unavailable counter.

For transfer from an agent-free host, retain the original CSV/text, command,
version, scope, timestamps, and checksums alongside the JVM bundle. The
`java-offline-capture` analyser currently does not interpret these files.
