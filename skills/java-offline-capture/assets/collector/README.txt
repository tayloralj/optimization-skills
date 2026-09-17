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
- Linux, bash 4.2+, coreutils (including timeout), tar, gzip, sha256sum.
- Run as the SAME user as the Java process (for example: sudo -u appuser ...).
- JDK tools (jcmd, jfr) next to the JVM give the richest bundle. On a JRE-only
  runtime the collector uses the kit's bundled async-profiler if it has one
  (kit name ends in -asprof), and otherwise still gathers host and /proc
  evidence and GC logs.
- Free disk space of about 3x --max-mb (default 512 MB, so ~1.5 GB).
- `bash collect.sh --check` tells you what is missing.

Steps
-----
Do steps 2-7 AS THE APPLICATION USER (for example: sudo -u appuser -i), so
that user can read the kit and attach to its own JVM.

1. Verify the kit you received (the sender gives you the sha256):
     sha256sum jvm-collector-*.tar.gz
   (Single-file kit: sha256sum the .run file, then `bash jvm-collector-*.run DIR`,
   which unpacks and checks itself.)
2. Unpack it somewhere private that the application user owns:
     mkdir -p ~/jvmcap && tar -xzf /path/to/jvm-collector-*.tar.gz -C ~/jvmcap
     cd ~/jvmcap/jvm-collector-*/ && sha256sum -c SHA256SUMS
3. Find the process (the EXAMINE column says which user to run as):
     bash collect.sh --list
4. Check this host and the JVM (collects nothing):
     bash collect.sh --check --pid 12345
5. Preview (collects nothing):
     bash collect.sh --pid 12345 --duration 120 --dry-run
6. Run during the problem window (use the exact options you were given):
     bash collect.sh --pid 12345 --duration 120 --yes
7. Send back the printed bundle file and its sha256 (and every .part file, or
   the .digest.txt, if you were asked for those). Delete local copies when the
   analysis is done.

Unattended runs
---------------
The collector can wait for a time or a condition, writing nothing until then.
Start it detached so it survives logging out:
  nohup bash collect.sh --pid 12345 --start-at 17:55 --duration 600 --yes > ~/jvmcap/collect.log 2>&1 &
  nohup bash collect.sh --pid 12345 --trigger cpu:350 --duration 120 --yes > ~/jvmcap/collect.log 2>&1 &
Triggers: cpu:PCT (process CPU, 100 = one core), rss:MB, gcpause:MS (needs a
GC log), file:/PATH (create the file to start). --max-wait (default 86400 s)
limits the wait. Check ~/jvmcap/collect.log for the result.

For a service restart, OOM, or crash, add `--systemd-unit UNIT`
`--journal-since '15 minutes ago'` and `--coredump`. These capture bounded,
read-only unit, journal, and coredump metadata when the operator can read it.

Several JVMs
------------
Repeat --pid: bash collect.sh --pid 111 --pid 222 --duration 120 --yes
Each JVM gets its own bundle. All must belong to the user running the command.

Kubernetes / containers
-----------------------
The collector runs inside the pod, as the application user:
  kubectl cp jvm-collector-X.tar.gz  NS/POD:/tmp/ -c APP
  kubectl exec -n NS POD -c APP -- sh -c 'cd /tmp && tar -xzf jvm-collector-X.tar.gz'
  kubectl exec -n NS POD -c APP -- bash /tmp/jvm-collector-X/collect.sh --list
  kubectl exec -n NS POD -c APP -- bash /tmp/jvm-collector-X/collect.sh --pid 1 --duration 120 --out /tmp/jvmcap --yes
  kubectl cp NS/POD:/tmp/jvmcap/jvmcap-....tar.gz ./ -c APP
Images without bash or tar (distroless): run the same commands in an ephemeral
debug container that targets the application container, uses a JDK image, and
runs as the application's user (kubectl debug --target=APP --custom=FILE ...;
the sender gives you the exact commands). The collector detects that it is
outside the JVM's filesystem and fetches files through /proc/PID/root.

What is collected
-----------------
- /proc and cgroup counters at start and end: per-thread CPU, scheduling delay,
  state and kernel wait channel; interrupts, softirqs, vmstat, memory, disk,
  network protocol counters, pressure; cgroup CPU throttling and memory events.
- Samples every 5 s (--sample-interval): host and process CPU, memory,
  pressure, throttling, and per-thread CPU.
- Read-only host readiness report and latency jitter audit.
- jcmd: JVM version, uptime, -XX flags, heap, metaspace, code cache, log configuration.
- A JDK Flight Recorder recording of the window (or a dump of an existing
  continuous recording), size-capped.
- Native Memory Tracking snapshots at start and end, if NMT is enabled.
- GC log files the JVM is writing (newest first, size-capped).
- Optional: thread dumps (text and JSON), class histograms, async-profiler
  recording, copies of vendor profiler results, a text digest.

What is removed or never collected
----------------------------------
- JFR events with environment variables, system properties, security
  properties, JVM and application command lines, child-process command lines,
  and other processes are switched off when recording and scrubbed afterwards
  (scrubbing needs the `jfr` tool; the manifest says if it was not possible).
- No heap dumps, no application data files, no `jcmd VM.command_line` or
  `VM.system_properties`. The JVM command line is read only to find GC log
  file names and is not stored.
Still present and possibly sensitive: class, method, and thread names; file
paths; host details; GC log contents. Handle the bundle and digest as
confidential; encrypt them if the transfer channel is not trusted, for example
  gpg --encrypt --recipient ANALYST_KEY jvmcap-....tar.gz

Transfer options
----------------
  --digest        also writes NAME.digest.txt (small text) to paste or attach
  --split-mb 20   splits the archive into 20 MB parts; the receiver rejoins them
                  with: cat NAME.tar.gz.part-* > NAME.tar.gz

Overhead
--------
JFR with the "profile" settings typically costs low single-digit percent CPU;
"default" is lower. Thread dumps and class histograms pause the JVM briefly
(longer with many threads or a large heap). Starting and stopping a recording
causes short safepoints. Sampling reads /proc every 5 s. If the service is at
its limit, use --jfr-settings default, --thread-dumps 0, and no histograms.
Each JVM command gives up after JCMD_TIMEOUT_SECONDS (default 30); a JVM that
does not answer is recorded as unresponsive and the capture continues.

Always-on recording (optional, needs a restart once)
----------------------------------------------------
Add to the JVM launch so evidence exists before an incident:
  -Xlog:gc*,safepoint:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=10,filesize=50m
  -XX:StartFlightRecording=name=continuous,settings=default,maxage=30m,maxsize=512m,disk=true
Then after an incident: bash collect.sh --pid PID --jfr dump --duration 10 --yes

Exit codes
----------
0 ok, 1 cancelled, 2 bad option, 3 --check found a blocking problem,
4 target/permission/space problem, 5 archiving failed, 6 no trigger fired
before --max-wait, 130 interrupted (a partial bundle is still written, except
while waiting, when nothing has been collected).
