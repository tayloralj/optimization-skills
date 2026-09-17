# Capture plans and operator runbooks

Fill in `PID`, `APPUSER`, host names, and paths. Always have the operator run
`--check --pid PID` and then `--dry-run` first; the printed plan is what will
happen. `VERSION` below is the kit version printed by `build-kit.sh`.

For a systemd service that is restarting or has been OOM-killed, include
`--systemd-unit UNIT --journal-since '15 minutes ago' --coredump`. The kit
captures bounded unit properties, recent journal lines, and target coredump
metadata when the operator's account can read them; failed permission checks
remain visible in the manifest. These options never restart or modify the
service.

| Situation | Plan |
| --- | --- |
| Latency spikes or jitter | A |
| High CPU or throughput plateau | B |
| Memory growth, OOM kills | C |
| Incident already over; JVM runs always-on JFR | D |
| Problem at a known time or unpredictable; nobody at the keyboard | E |
| JVM hung or not answering | F |
| Several JVMs on the host | G |
| Kubernetes, including distroless images | H |
| JRE-only runtime (no `jcmd`/`jfr`) | I |
| Slow, size-limited, text-only, or console-only transfer | J |

## Common preparation (VM or bare metal)

```bash
# analysis machine
scripts/build-kit.sh ./kits            # note kit path and sha256
scp ./kits/jvm-collector-VERSION.tar.gz ops@TARGET:/tmp/

# target host, as the application user
sudo -u APPUSER bash -c '
  mkdir -p ~/jvmcap && cd ~/jvmcap &&
  sha256sum /tmp/jvm-collector-VERSION.tar.gz &&          # compare with the sha256 you were given
  tar -xzf /tmp/jvm-collector-VERSION.tar.gz &&
  cd jvm-collector-VERSION && sha256sum -c --quiet SHA256SUMS &&
  bash collect.sh --list &&
  bash collect.sh --check --pid PID'
```

If the application user has no home directory, use a private directory it can
write, for example `install -d -o APPUSER -m 700 /var/tmp/jvmcap`.
`--list` shows every Java process, including ones the current user cannot
examine, with the user to run as. `--check` exits 3 when a required command is
missing or the JVM refuses attach, and reports optional gaps (no NMT, no GC
log, no continuous recording, no `jfr` tool for scrubbing or the digest).

Every run samples process, thread, and host CPU, memory, pressure, and cgroup
throttling every 5 s (`--sample-interval`, 0 to turn off), so bursts inside the
window are not averaged away.

## Plan A: latency spikes or jitter

```bash
sudo -u APPUSER bash ~/jvmcap/jvm-collector-VERSION/collect.sh \
  --pid PID --duration 300 --jfr-settings profile --sample-interval 2 --cpus HOT_CPUS \
  --out ~/jvmcap/bundles --dry-run      # then repeat with --yes
```

Run across the period when spikes happen. `--cpus` (optional) lists the CPUs
the latency-critical threads should run on and adds per-CPU interrupt rates to
the host audit. Ask for GC logging at launch if the JVM has none (see Plan D).
The analysis places GC pauses, steal, pressure, and throttling on the same
clock as the busiest sample intervals.

## Plan B: high CPU or throughput plateau

```bash
... collect.sh --pid PID --duration 120 --thread-dumps 3 --out ~/jvmcap/bundles --yes
# with async-profiler (installed on the host, or bundled with build-kit.sh --with-async-profiler):
... collect.sh --pid PID --duration 120 --asprof cpu --out ~/jvmcap/bundles --yes
# preserve a vendor session collected separately during the same window:
... collect.sh --pid PID --duration 120 --vendor-artifact /path/to/vtune-result \
  --vendor-artifact /path/to/perf.data --out ~/jvmcap/bundles --yes
```

Capture at peak load. Thread dumps let the analysis join the busiest OS
threads to their Java stacks and show lock owners and stuck threads. Use
`--asprof ctimer` when `perf_event_paranoid` blocks `cpu`. Loading
async-profiler into the JVM needs the owner's approval. Vendor artifacts are
copied unchanged under `vendor/` (at most a quarter of `--max-mb`),
checksum-verified, and left for the matching VTune, uProf, perf, or PCM release.

## Plan C: memory growth or OOM kills

Best evidence needs `-XX:NativeMemoryTracking=summary` at launch (restart).
Then take two captures hours apart and compare:

```bash
... collect.sh --pid PID --duration 60 --jfr-settings default --class-histogram --out ~/jvmcap/bundles --yes
```

Analyse each bundle, then `compare-bundles.py ANALYSIS_1 ANALYSIS_2`, and
compare the `jvm/nmt-end` directories with `nmt-compare.py` (the
`java-native-memory` skill). `--class-histogram` uses `GC.class_histogram -all`
(no forced GC; it walks the heap during a safepoint, so expect a pause that
grows with heap size). cgroup `memory.events` deltas show limit hits and OOM kills.

## Plan D: always-on recording for incidents

Ask for these launch flags once (change request), so evidence exists before the
next incident:

```text
-Xlog:gc*,safepoint:file=/var/log/APP/gc.log:time,uptime,level,tags:filecount=10,filesize=50m
-XX:StartFlightRecording=name=continuous,settings=default,maxage=30m,maxsize=512m,disk=true
-XX:NativeMemoryTracking=summary        # optional, small overhead
```

After an incident, within the 30-minute window:

```bash
... collect.sh --pid PID --jfr dump --duration 10 --out ~/jvmcap/bundles --yes
```

## Plan E: unattended capture at a time or on a trigger

The collector waits (writing nothing) and then captures. Run it detached so it
survives the operator logging out:

```bash
cd ~/jvmcap/jvm-collector-VERSION
# at a fixed local time (within --max-wait, default 24 h):
nohup bash collect.sh --pid PID --start-at 17:55 --duration 600 --out ~/jvmcap/bundles --yes > ~/jvmcap/collect.log 2>&1 &
# when the problem shows itself (any trigger fires); with Plan D flags, --jfr dump
# also contains the minutes before the trigger:
nohup bash collect.sh --pid PID --trigger cpu:350 --trigger gcpause:200 --jfr dump \
  --duration 120 --max-wait 86400 --out ~/jvmcap/bundles --yes > ~/jvmcap/collect.log 2>&1 &
# an external alert or a person creates a file to start it:
nohup bash collect.sh --pid PID --trigger file:/var/tmp/jvmcap/GO --duration 120 --out ~/jvmcap/bundles --yes > ~/jvmcap/collect.log 2>&1 &
```

| Trigger | Fires when |
| --- | --- |
| `cpu:PCT` | process CPU over 5 s is at least PCT % of one core (400 = four cores) |
| `rss:MB` | resident memory reaches MB |
| `gcpause:MS` | a new line in the JVM's GC log reports a pause of at least MS ms |
| `file:/PATH` | the path exists |

Combine `--start-at` with triggers to arm them at a time. The manifest records
which trigger fired and how long the collector waited. Exit code 6 means
nothing fired before `--max-wait`; 4 means the JVM exited while waiting. Set
thresholds from a baseline capture, not guesses.

## Plan F: hung or unresponsive JVM

```bash
JCMD_TIMEOUT_SECONDS=10 bash collect.sh --pid PID --duration 30 --thread-dumps 3 --jfr none --out ~/jvmcap/bundles --yes
```

If the JVM does not answer `VM.version`, the collector marks it unresponsive,
skips the remaining JVM commands, and still records thread CPU, kernel thread
states (`R`, `S`, `D`, `T`), and wait channels at start and end, plus the GC
logs named on the command line. If thread dumps are essential and attach is
dead, the owner can approve `kill -3 PID`: the JVM prints a thread dump to its
own standard output (the service log), which the operator sends separately.

## Plan G: several JVMs

```bash
bash collect.sh --pid PID1 --pid PID2 --duration 120 --out ~/jvmcap/bundles --dry-run   # shows each plan
bash collect.sh --pid PID1 --pid PID2 --duration 120 --out ~/jvmcap/bundles --yes
```

The collectors run in parallel, one bundle per JVM, with output lines prefixed
by PID. All PIDs must belong to the user running the command; run separate
commands for different users.

## Plan H: Kubernetes

Container with bash and tar (most JDK images):

```bash
kubectl cp ./kits/jvm-collector-VERSION.tar.gz NS/POD:/tmp/ -c APP
kubectl exec -n NS POD -c APP -- sh -c 'cd /tmp && tar -xzf jvm-collector-VERSION.tar.gz'
kubectl exec -n NS POD -c APP -- bash /tmp/jvm-collector-VERSION/collect.sh --check --pid 1
kubectl exec -n NS POD -c APP -- bash /tmp/jvm-collector-VERSION/collect.sh --pid 1 --duration 120 --out /tmp/jvmcap --yes
kubectl exec -n NS POD -c APP -- sh -c 'ls /tmp/jvmcap/*.tar.gz'
kubectl cp NS/POD:/tmp/jvmcap/BUNDLE.tar.gz ./BUNDLE.tar.gz -c APP
kubectl exec -n NS POD -c APP -- rm -rf /tmp/jvmcap /tmp/jvm-collector-VERSION*
```

`kubectl exec` runs as the container's user, which normally owns the JVM. The
container needs space in `/tmp` (or another writable path).

Distroless or shell-less images: attach an ephemeral debug container that
shares the application container's process namespace and runs as the same
user, with a JDK image whose major version is at least the application's:

```bash
cat > jvmcap-user.yaml <<'EOF'
securityContext:
  runAsUser: APP_UID
  runAsGroup: APP_GID
EOF
kubectl debug -n NS POD -c jvmcap --target=APP --image=eclipse-temurin:21-jdk \
  --custom=jvmcap-user.yaml -- sleep 3600
kubectl cp ./kits/jvm-collector-VERSION.tar.gz NS/POD:/tmp/ -c jvmcap
kubectl exec -n NS POD -c jvmcap -- sh -c 'cd /tmp && tar -xzf jvm-collector-VERSION.tar.gz'
kubectl exec -n NS POD -c jvmcap -- bash /tmp/jvm-collector-VERSION/collect.sh --list
kubectl exec -n NS POD -c jvmcap -- bash /tmp/jvm-collector-VERSION/collect.sh --pid JAVA_PID --duration 120 --out /tmp/jvmcap --yes
kubectl cp NS/POD:/tmp/jvmcap/BUNDLE.tar.gz ./BUNDLE.tar.gz -c jvmcap
```

The collector sees that the JVM is in another mount namespace. It attaches
with the debug image's `jcmd`, has the JVM write recordings and JSON dumps to
the JVM's own `/tmp`, reads them back through `/proc/PID/root`, and removes
them. GC logs are read the same way. The manifest records
`target_mount_ns=different`. Namespaces that enforce the restricted Pod
Security level may need `--profile=restricted`. Ephemeral containers cannot
be removed until the pod restarts; `sleep` bounds this one's lifetime.

Node-level evidence such as IRQs reflects the node, and CPU limits appear in
the cgroup counters and host audit.

## Plan I: JRE-only runtime (no jcmd or jfr)

Build the kit with async-profiler (`build-kit.sh --with-async-profiler ...`).
The collector then attaches through async-profiler for JVM diagnostics, thread
dumps, and JFR recordings, and `--asprof` works:

```bash
... collect.sh --pid PID --duration 120 --thread-dumps 2 --asprof ctimer --yes
```

New recordings switch sensitive events off at the source. Without a `jfr`
tool, async-profiler output is written as collapsed stacks. A dumped
continuous recording cannot be scrubbed and is marked `NOT_SCRUBBED`.

Without async-profiler, the collector still gathers `/proc` deltas, samples,
the host audit, and GC logs (found from the command line, or given
explicitly):

```bash
... collect.sh --pid PID --duration 120 --jfr none --gc-log /var/log/APP/gc.log --yes
```

## Plan J: restricted transfer

- **Text only, or the bundle is slow to arrive:** add `--digest`. The
  collector writes `BUNDLE.digest.txt` (at most 256 KB) next to the archive:
  thread CPU, host CPU, pressure, throttling, busiest intervals, host-audit
  findings, the GC summary for the window (when `python3` is on the host), JFR
  views (when the target's `jfr` has `view`), and thread-dump states. It can be
  pasted into a ticket or chat and read directly. It has the same sensitivity
  as the bundle.
- **Attachment size limits:** add `--split-mb 20`. The collector prints each
  part's sha256 and the whole archive's. Rejoin with
  `cat BUNDLE.tar.gz.part-* > BUNDLE.tar.gz` and check the whole sha256.
- **Untrusted channel:** encrypt before sending, for example
  `gpg --encrypt --recipient ANALYST_KEY BUNDLE.tar.gz` (sends `BUNDLE.tar.gz.gpg`).
- **Console paste only (no file copy to the host):** build with
  `build-kit.sh ./kits --single-file`. The `.run` file is plain text: the
  operator pastes it into `cat > kit.run <<'EOF'` ... `EOF`, checks
  `sha256sum kit.run` against the printed `single_file_sha256`, and runs
  `bash kit.run ~/jvmcap`. It checks its own payload and refuses a damaged
  paste. Bundling async-profiler makes it about 6,000 lines, so prefer the
  plain kit for pasting.

## Retrieval

- `scp APPHOST:~APPUSER/jvmcap/bundles/BUNDLE.tar.gz .` (via a jump host if needed),
  a ticket attachment, or your file-transfer system.
- Always compare the sha256 printed on the target with `sha256sum` locally, or
  pass it to `analyze-bundle.py --expect-sha256`.
- Files already collected by other means (JFR, GC logs, jstack output, JSON
  thread dumps, class histograms, collapsed stacks, `hs_err_pid*.log`) can be
  analysed from a directory: `analyze-bundle.py DIR OUT`. Without a manifest
  and checksums, integrity is not verified.
- Delete the bundle, digest, parts, and kit from the target when retrieval is confirmed.

## Reading ANALYSIS.md

- **Findings** lists automatic signals above thresholds: GC pause share and
  alarms, long run-queue delay, steal, iowait, swapping, network errors,
  pressure stalls, cgroup throttling and OOM events, CPU bursts, RSS growth,
  blocked, stuck, deadlocked, or stopped threads, crash logs, failed collector
  steps, and scrub problems. Use them as leads.
- **Process** shows per-thread CPU and run-queue delay over the window: a hot
  thread with high delay is being starved of CPU. **Hot threads** joins those
  threads to Java stacks.
- **Time series** lists the busiest sample intervals with the busiest thread,
  host state, and GC pause time in each (times are host uptime seconds).
- **GC and safepoints** is summarised for the capture window only, using the
  JVM start time recorded by the collector.
- **Reports** under `reports/` hold the full GC summaries, JFR views, flame
  graphs, and the NMT comparison. `analysis.json` holds the same data for
  agents and `compare-bundles.py`.
