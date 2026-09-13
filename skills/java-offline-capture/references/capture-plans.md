# Capture plans and operator runbooks

Fill in `PID`, `APPUSER`, host names, and paths. Always have the operator run
`--dry-run` first; the printed plan is what will happen.

## Common preparation (VM or bare metal)

```bash
# analysis machine
scripts/build-kit.sh ./kits            # note kit path and sha256
scp ./kits/jvm-collector-0.3.0.tar.gz ops@TARGET:/tmp/

# target host, as the application user
sudo -u APPUSER bash -c '
  mkdir -p ~/jvmcap && cd ~/jvmcap &&
  sha256sum /tmp/jvm-collector-0.3.0.tar.gz &&          # compare with the sha256 you were given
  tar -xzf /tmp/jvm-collector-0.3.0.tar.gz &&
  cd jvm-collector-0.3.0 && sha256sum -c --quiet SHA256SUMS &&
  bash collect.sh --list'
```

If the application user has no home directory, use a private directory it can
write, for example `install -d -o APPUSER -m 700 /var/tmp/jvmcap`.

## Plan A: latency spikes or jitter

```bash
sudo -u APPUSER bash ~/jvmcap/jvm-collector-0.3.0/collect.sh \
  --pid PID --duration 300 --jfr-settings profile --cpus HOT_CPUS \
  --out ~/jvmcap/bundles --dry-run      # then repeat with --yes
```

Run across the period when spikes happen. `--cpus` (optional) lists the CPUs
the latency-critical threads should run on, for the host audit. Ask for GC
logging at launch if the JVM has none (see Plan D).

## Plan B: high CPU or throughput plateau

```bash
... collect.sh --pid PID --duration 120 --thread-dumps 3 --out ~/jvmcap/bundles --yes
# with async-profiler installed on the host:
... collect.sh --pid PID --duration 120 --asprof cpu --out ~/jvmcap/bundles --yes
```

Capture at peak load. Thread dumps show what busy and blocked threads are doing.

## Plan C: memory growth or OOM kills

Best evidence needs `-XX:NativeMemoryTracking=summary` at launch (restart).
Then take two captures hours apart and compare:

```bash
... collect.sh --pid PID --duration 60 --jfr-settings default --out ~/jvmcap/bundles --yes
```

Analyse each bundle, then compare the `jvm/nmt-end` directories of the two
bundles with `nmt-compare.py` (the `java-native-memory` skill).

## Plan D: always-on recording for incidents

Ask for these launch flags once (change request), so evidence exists before the
next incident:

```text
-Xlog:gc*,safepoint:file=/var/log/APP/gc.log:time,uptime,level,tags:filecount=10,filesize=50m
-XX:StartFlightRecording=name=continuous,settings=default,maxage=30m,maxsize=512m,disk=true
```

After an incident, within the 30-minute window:

```bash
... collect.sh --pid PID --jfr dump --duration 10 --out ~/jvmcap/bundles --yes
```

## Plan E: Kubernetes

```bash
kubectl cp ./kits/jvm-collector-0.3.0.tar.gz NS/POD:/tmp/
kubectl exec -n NS POD -- sh -c 'cd /tmp && tar -xzf jvm-collector-0.3.0.tar.gz'
kubectl exec -n NS POD -- bash /tmp/jvm-collector-0.3.0/collect.sh --list
kubectl exec -n NS POD -- bash /tmp/jvm-collector-0.3.0/collect.sh --pid 1 --duration 120 --out /tmp/jvmcap --yes
kubectl exec -n NS POD -- sh -c 'ls /tmp/jvmcap/*.tar.gz'
kubectl cp NS/POD:/tmp/jvmcap/BUNDLE.tar.gz ./BUNDLE.tar.gz
kubectl exec -n NS POD -- rm -rf /tmp/jvmcap /tmp/jvm-collector-0.3.0*
```

`kubectl exec` runs as the container's user, which normally owns the JVM. The
container needs bash and enough space in `/tmp` (or another writable path).
Node-level evidence such as IRQs reflects the node, and CPU limits appear in
the host audit's cgroup section. Distroless or shell-less images: use Plan D
flags and `kubectl cp` the JFR and GC log files instead.

## Plan F: JRE-only runtime (no jcmd or jfr)

The collector still gathers `/proc` deltas, the host audit, and GC logs when
you pass them explicitly:

```bash
... collect.sh --pid PID --duration 120 --jfr none --gc-logs none --gc-log /var/log/APP/gc.log --yes
```

For JFR, add `-XX:StartFlightRecording=...,filename=/var/log/APP/app.jfr` at
launch and retrieve that file; it will not be scrubbed on the host, so treat it
as containing environment variables and command lines.

## Retrieval

- `scp APPHOST:~APPUSER/jvmcap/bundles/BUNDLE.tar.gz .` (via a jump host if needed),
  a ticket attachment, or your file-transfer system.
- Always compare the sha256 printed on the target with `sha256sum` locally, or
  pass it to `analyze-bundle.py --expect-sha256`.
- Delete the bundle and kit from the target when retrieval is confirmed.

## Reading ANALYSIS.md

- **Findings** lists automatic signals above thresholds (GC pause share and
  alarms, long run-queue delay, swapping, UDP errors, pressure stalls, RSS
  growth, blocked threads, scrub problems). Use them as leads.
- **Process** shows per-thread CPU and run-queue delay over the window: a hot
  thread with high delay is being starved of CPU.
- **GC and safepoints** is summarised for the capture window only, using the
  JVM uptime recorded at the start.
- **Reports** under `reports/` hold the full GC summaries, JFR views, and NMT
  comparison for deeper reading.
