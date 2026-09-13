---
type: llm
weight: 2
---

The response should give a path that works without root and without a restart: attach JFR to the running JVM with jcmd
(JFR.start with a bounded duration/maxsize and a filename), then read allocation data (for example `jfr view allocation-by-site`
or jdk.ObjectAllocationSample events). It may mention async-profiler alloc mode as an alternative if permitted.
It should note that attaching needs the same user and namespace, and that recordings can contain sensitive data.
Fail if the first recommendation is to lower perf_event_paranoid, use sudo, or restart the JVM.
