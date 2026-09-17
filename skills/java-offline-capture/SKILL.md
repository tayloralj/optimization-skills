---
name: java-offline-capture
description: Capture JVM evidence on a production or QA host that cannot run Codex or Claude, then analyse it here. Builds a collector kit with run, trigger, and retrieval steps for an operator, and analyses the returned bundle, a pasted digest, or loose JFR, GC, thread-dump, and crash files. Use when the problem host has no agent, restricted access, or change control.
---

# Java Offline Capture

Split the investigation into three places: **build** the kit here, **collect**
on the target host (run by an operator, no agent there), and **analyse** the
returned evidence here. The agent never needs a shell on the target.

## Workflow

1. **Agree the question and the window.** Which JVM, which symptom, and when
   it happens (a load test, a daily peak, "right now", "whenever CPU spikes").
   A capture of a quiet period cannot explain a busy one. Plan a baseline
   capture from a healthy period too; `compare-bundles.py` needs one.
2. **Choose options** with `references/capture-plans.md`: latency spike, high
   CPU, memory growth, hung JVM, incident with always-on JFR, unattended
   (`--start-at`, `--trigger`), several JVMs, JRE-only runtime, Kubernetes
   (including distroless images through a debug container), and restricted
   transfer channels. Keep the window short enough to be safe and long enough
   to include the problem.
3. **Build the kit** on this machine:

   ```bash
   scripts/build-kit.sh ./kits                  # jvm-collector-VERSION.tar.gz + sha256
   scripts/build-kit.sh ./kits --single-file    # also a .run text file for console-paste-only hosts
   scripts/build-kit.sh ./kits --with-async-profiler async-profiler-X.Y-linux-x64.tar.gz \
     --async-profiler-sha256 PUBLISHED_SHA      # jvm-collector-VERSION-asprof.tar.gz
   ```

   The kit contains `collect.sh`, an operator `README.txt`, and read-only
   helpers from sibling skills (listed in `requires.txt`). It needs bash 4.2+,
   coreutils, tar, and gzip on the target, plus the target JVM's own
   `jcmd`/`jfr` if present. Bundle async-profiler (verified against the
   release checksum; never download it on the target) when the host is
   JRE-only or CPU profiles are wanted; it also provides JVM attach without
   `jcmd`. Loading it into a production JVM needs the owner's approval.
4. **Hand the operator a runbook**: the kit and its sha256, `collect.sh --check
   --pid PID` first, then the exact `--dry-run` and real commands from
   `references/capture-plans.md` (as the application user), and how to send
   the result back. Change-controlled environments may need the `--check` and
   `--dry-run` output attached to the change request.
5. **Analyse what comes back**:

   ```bash
   cat BUNDLE.tar.gz.part-* > BUNDLE.tar.gz            # only if --split-mb was used
   scripts/analyze-bundle.py BUNDLE.tar.gz ./analysis-1 --expect-sha256 SHA
   scripts/analyze-bundle.py ./files-from-ops ./analysis-2   # loose files, no kit
   scripts/compare-bundles.py ./analysis-baseline ./analysis-1 --output COMPARISON.md
   ```

   The analyser refuses unsafe archives, verifies every checksum, and writes
   `ANALYSIS.md` (findings first) plus `analysis.json` (`--json` prints it).
   It covers per-thread CPU and run-queue delay, hot threads joined to their
   stacks through the thread dumps' native ids, a time series of the busiest
   intervals with GC pauses placed on the same clock, host CPU including
   steal and iowait, disks, softirqs, pressure, cgroup throttling and OOM
   events, GC for the capture window, JFR views, flame graphs (when
   async-profiler's `jfrconv` and a JDK are available), NMT, class histogram
   growth, lock owners, deadlocks, stuck threads, virtual threads, and
   `hs_err` crash logs. A directory of loose files (JFR, GC logs, jstack
   output, JSON thread dumps, histograms, collapsed stacks, `hs_err`) is
   classified by content and gets the same treatment, without integrity
   checks. `--vendor-artifact` results are listed and checksum-verified, not
   parsed.
   If only the text digest (`NAME.digest.txt`) came back, read it directly: it
   holds thread CPU, host CPU, pressure, busiest intervals, audit findings, the
   GC window summary, and JFR views rendered on the host.
6. **Interpret with the specialist skills** named in `ANALYSIS.md`
   (`java-gc-tuning`, `java-flight-recorder`, `java-native-memory`,
   `java-async-profiler`, `linux-low-latency-tuning`,
   `linux-ebpf-io-network`, ...). Treat automatic findings as leads; confirm
   against the stated symptom and a baseline. Differences in
   `COMPARISON.md` matter only when they exceed run-to-run variation.
7. **Close the loop**: if evidence is missing (steps listed as not completed,
   no GC logs, JFR unavailable, window missed the spike, JVM unresponsive),
   produce a revised plan rather than guessing, and ask the operator to delete
   bundles from the target once retrieved.

## What the collector guarantees

- Read-only on the host; attaches only to the chosen JVM; never uses `sudo`.
- Bounded: window 10–3600 s, wait at most `--max-wait`, every JVM diagnostic
  command limited by `JCMD_TIMEOUT_SECONDS` (default 30). A JVM that does not
  answer is recorded as unresponsive and the capture continues with `/proc`
  evidence (thread states and kernel wait channels). JFR size cap, GC log copy
  cap, vendor artifacts limited to a quarter of `--max-mb`, free-space check;
  a partial bundle is still produced if interrupted, and an interrupted wait
  writes nothing.
- Private: bundle, archive, parts, and digest are mode 0600. New recordings
  switch off environment variables, system and security properties, JVM
  information, other processes, and child-process command lines
  (`jdk.ProcessStart`) at the source, and the target's `jfr` tool scrubs them
  again. A dumped recording without a `jfr` tool is marked `NOT_SCRUBBED`;
  async-profiler output without one is written as collapsed stacks instead of
  JFR. `--redact-hostname` hashes the hostname.
- Verifiable: `SHA256SUMS` inside, sha256 of the archive (and of each part)
  printed for transfer.

Bundle layout and manifest keys: `references/bundle-format.md`.

## Guardrails

- Production attach needs the owner's approval even though it is low risk;
  thread dumps, histograms, and JFR start/stop cause short safepoints.
- The bundle and digest still hold class, method, thread, and file names and
  host details: store them with production diagnostic data controls, encrypt
  them for transfer when the channel is not trusted, and delete them when done.
- Root-only evidence (perf, eBPF, lab-mode tuning) is out of scope for the
  kit; generate those commands with the relevant skill and send them as a
  separate, reviewed operator task.
- Analyse with a JDK at least as new as the one that recorded the JFR files.
