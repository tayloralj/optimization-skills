---
name: java-offline-capture
description: Capture JVM performance evidence on a production or QA host that cannot run Codex or Claude, then analyse it elsewhere. Builds a self-contained collector kit, gives the operator exact run and retrieval steps, and turns the returned bundle (JFR, GC logs, jcmd and NMT snapshots, thread dumps, /proc deltas, host audit) into findings. Use when the problem host has no agent, restricted access, or change control.
---

# Java Offline Capture

Split the investigation into three places: **build** the kit here, **collect**
on the target host (run by an operator, no agent there), and **analyse** the
returned bundle here. The agent never needs a shell on the target.

## Workflow

1. **Agree the question and the window.** Which JVM, which symptom, and when
   it happens (a load test, a daily peak, "right now"). A capture of a quiet
   period cannot explain a busy one. Plan a baseline capture from a healthy
   period too if possible.
2. **Choose options** with `references/capture-plans.md` (latency spike, high
   CPU, memory growth, incident with always-on JFR, JRE-only host, Kubernetes).
   Keep the window short enough to be safe and long enough to include the problem.
3. **Build the kit** on this machine:

   ```bash
   scripts/build-kit.sh ./kits
   # kit=./kits/jvm-collector-0.3.0.tar.gz  sha256=...
   ```

   The kit contains `collect.sh`, an operator `README.txt`, and read-only
   helpers from sibling skills (listed in `requires.txt`). It needs only bash
   and coreutils on the target, plus the target JVM's own `jcmd`/`jfr` if present.
4. **Hand the operator a runbook**: the kit file and its sha256, the exact
   commands from `references/capture-plans.md` filled in (including
   `sudo -u <app user>`, `--dry-run` first, then the real run), and how to send
   the bundle back. Change-controlled environments may need the plan output
   (`--dry-run`) attached to the change request.
5. **Analyse the returned bundle**:

   ```bash
   scripts/analyze-bundle.py jvmcap-HOST-PID-TIME.tar.gz ./analysis-1 --expect-sha256 SHA
   ```

   It refuses unsafe archives, verifies every checksum, computes per-thread CPU
   and run-queue delay, interrupt, vmstat, network, and pressure deltas, runs the
   GC, JFR, and NMT analysers for the capture window, and writes
   `ANALYSIS.md` with findings and suggested next skills. To preserve a vendor
   result collected alongside the JVM window, repeat `--vendor-artifact PATH`
   for each existing VTune, uProf, `perf`, or PCM file/directory; the analyser
   verifies checksums and leaves proprietary databases for their native tools.
6. **Interpret with the specialist skills** named in `ANALYSIS.md`
   (`java-gc-tuning`, `java-flight-recorder`, `java-native-memory`,
   `linux-low-latency-tuning`, `linux-ebpf-io-network`, ...). Treat automatic
   findings as leads; confirm against the stated symptom and a baseline.
7. **Close the loop**: if evidence is missing (no GC logs, JFR not available,
   window missed the spike), produce a revised plan rather than guessing, and
   ask the operator to delete bundles from the target once retrieved.

## What the collector guarantees

- Read-only on the host; attaches only to the chosen JVM; never uses `sudo`.
- Bounded: window 10–3600 s, JFR size cap, GC log copy cap, free-space check;
  a partial bundle is still produced if interrupted.
- Private: bundle and archive are mode 0600. JFR files are scrubbed of
  environment variables, system and security properties, JVM and
  application command lines, and other processes' command lines (needs the
  target's `jfr` tool; the manifest records if scrubbing was impossible).
  `--redact-hostname` hashes the hostname.
- Verifiable: `SHA256SUMS` inside, sha256 of the archive printed for transfer.

Bundle layout and manifest keys: `references/bundle-format.md`.

## Guardrails

- Production attach needs the owner's approval even though it is low risk;
  thread dumps and JFR start/stop cause short safepoints.
- The bundle still holds class, method, thread, and file names and host
  details: store it with production diagnostic data controls and delete it
  when done.
- Root-only evidence (perf, eBPF, lab-mode tuning) is out of scope for the
  kit; generate those commands with the relevant skill and send them as a
  separate, reviewed operator task.
- Analyse with a JDK at least as new as the one that recorded the JFR files.
