JVM PERFORMANCE COLLECTOR - OPERATOR GUIDE
===========================================

What this does
--------------
Collects a bounded, checksummed bundle of performance evidence about ONE Java
process, so it can be analysed on another machine. It does not change the
host, does not use sudo, and does not restart anything. It attaches to the
chosen JVM (the same way `jcmd` and JDK Flight Recorder do) for a fixed time.

Requirements on this host
-------------------------
- Linux, bash 4+, coreutils, tar, gzip, sha256sum.
- Run as the SAME user as the Java process (for example: sudo -u appuser ...).
- JDK tools (jcmd, jfr) next to the JVM give the richest bundle. On a JRE-only
  runtime the collector still gathers host and /proc evidence and GC logs.
- Free disk space of about 3x --max-mb (default 512 MB, so ~1.5 GB).

Steps
-----
Do steps 2-6 AS THE APPLICATION USER (for example: sudo -u appuser -i), so
that user can read the kit and attach to its own JVM.

1. Verify the kit you received (the sender gives you the sha256):
     sha256sum jvm-collector-*.tar.gz
2. Unpack it somewhere private that the application user owns:
     mkdir -p ~/jvmcap && tar -xzf /path/to/jvm-collector-*.tar.gz -C ~/jvmcap
     cd ~/jvmcap/jvm-collector-*/ && sha256sum -c SHA256SUMS
3. Find the process:
     bash collect.sh --list
4. Preview (collects nothing):
     bash collect.sh --pid 12345 --duration 120 --dry-run
5. Run during the problem window (use the exact options you were given):
     bash collect.sh --pid 12345 --duration 120 --yes
6. Send back the printed bundle file and its sha256. Delete local copies when
   the analysis is done.

Kubernetes / containers
-----------------------
The collector must run inside the container, as the application user:
  kubectl cp jvm-collector-X.tar.gz  NS/POD:/tmp/
  kubectl exec -n NS POD -- sh -c 'cd /tmp && tar -xzf jvm-collector-X.tar.gz'
  kubectl exec -n NS POD -- bash /tmp/jvm-collector-X/collect.sh --list
  kubectl exec -n NS POD -- bash /tmp/jvm-collector-X/collect.sh --pid 1 --duration 120 --out /tmp/jvmcap --yes
  kubectl cp NS/POD:/tmp/jvmcap/jvmcap-....tar.gz ./
Images without bash (distroless, some Alpine) cannot run it. Instead, start the
JVM with continuous JFR and GC logging (see "Always-on recording" below) and
copy those files out.

What is collected
-----------------
- /proc counters at start and end: per-thread CPU and scheduling delay,
  interrupts, softirqs, vmstat, memory, disk, network protocol counters, pressure.
- Read-only host readiness report and latency jitter audit.
- jcmd: JVM version, uptime, -XX flags, heap, metaspace, code cache, log configuration.
- A JDK Flight Recorder recording of the window (or a dump of an existing
  continuous recording), size-capped.
- Native Memory Tracking snapshots at start and end, if NMT is enabled.
- GC log files the JVM is writing (newest first, size-capped).
- Optional: thread dumps, async-profiler recording.

What is removed or never collected
----------------------------------
- JFR events with environment variables, system properties, security
  properties, JVM and application command lines, and other processes are
  scrubbed from recordings (needs the `jfr` tool; the manifest says if not).
- No heap dumps, no class histograms, no application data files, no
  `jcmd VM.command_line` or `VM.system_properties`.
Still present and possibly sensitive: class, method, and thread names; file
paths; host details; GC log contents. Handle the bundle as confidential.

Overhead
--------
JFR with the "profile" settings typically costs low single-digit percent CPU;
"default" is lower. Thread dumps pause the JVM briefly (longer with many
threads). Starting and stopping a recording causes short safepoints. If the
service is at its limit, use --jfr-settings default and --thread-dumps 0.

Always-on recording (optional, needs a restart once)
----------------------------------------------------
Add to the JVM launch so evidence exists before an incident:
  -Xlog:gc*,safepoint:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=10,filesize=50m
  -XX:StartFlightRecording=name=continuous,settings=default,maxage=30m,maxsize=512m,disk=true
Then after an incident: bash collect.sh --pid PID --jfr dump --duration 10 --yes

Exit codes
----------
0 ok, 1 cancelled, 2 bad option, 4 target/permission/space problem,
5 archiving failed, 130 interrupted (a partial bundle is still written).
