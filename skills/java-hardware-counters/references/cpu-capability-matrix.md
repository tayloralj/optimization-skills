# Intel and AMD CPU capability matrix

Use this matrix to choose an experiment, not to assume that a family name
guarantees an event. Record the exact CPUID family/model/stepping, microcode,
kernel, perf version, topology, and whether the host is virtualized. Then query
the installed tool (`perf list`, VTune help, or `AMDuProfCLI info --system`) and
smoke-test each event.

| Platform shape | Useful routing | Boundary |
| --- | --- | --- |
| Intel client hybrid (P/E cores) | Keep P-core and E-core samples separate; record CPU affinity and migration; use events listed for each PMU | IPC, frequency, and top-down metrics are not interchangeable across core types |
| Intel homogeneous client/server | Start with cycles/instructions/branches when listed, then model-specific cache or PEBS events | Event names and precise attribution vary by generation and errata |
| AMD Zen client (CCD/CCX and L3 domains) | Record CCD/CCX and LLC placement; use core PMCs or IBS only when the detected tool lists them | L3 and Data Fabric traffic are not per-Java-method measurements |
| AMD EPYC (CCD, NUMA, Data Fabric, UMC) | Separate core, L3, DF, and memory-channel scope; use AMDuProfPcm only for supported platform metrics | Socket/channel traffic includes other processes and needs a controlled host |
| KVM or another VM | Compare guest CPUID with exposed `/sys/bus/event_source/devices`; record vPMU availability | Guest model strings do not prove physical silicon; missing vPMU cannot be fixed by a guest sysctl |

## Minimum evidence

Capture these read-only fields before selecting events:

```bash
lscpu -J
uname -a
cat /sys/devices/system/cpu/cpu0/microcode/version 2>/dev/null || true
find /sys/bus/event_source/devices -maxdepth 1 -mindepth 1 -printf '%f\n' | sort
perf list
```

On Intel, record hybrid PMU names separately when present. Treat PEBS, top-down,
and uncore availability as model-specific. On AMD, record the uProf system
report's Core PMC, L3 PMC, Data Fabric, UMC, and IBS availability independently.
IBS sampling and PMC counting answer different questions and can have different
permission requirements.

For every selected event, preserve its displayed name, unit, scope, sampling or
counting mode, time enabled/running, and the authoritative vendor description.
Do not copy a raw encoding or a threshold from another CPU generation. A zero,
unsupported, or permission-denied event is a failed measurement, not evidence
that the workload has no stalls.

## Java and placement

Record JDK build, collector, heap size, compilation state, CPU affinity, cgroup
effective CPUs, SMT siblings, NUMA nodes, LLC domains, and frequency policy.
Keep Java method attribution in a JIT-aware profiler; hardware counters alone
cannot identify a Java method. Keep core-local counts separate from shared L3,
Data Fabric, memory-channel, and package counters. Do not combine unlike core
types, CCDs, sockets, or VMs into one unexplained average.
