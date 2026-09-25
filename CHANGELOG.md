# Changelog

All notable changes to this project. Versions follow
[semantic versioning](https://semver.org/); the plugin version lives in `VERSION`
and `.claude-plugin/plugin.json`.

## Unreleased

- Add `cpp-build-readiness`, the first native C/C++ skill: a read-only check
  of symbols, debuginfo, build-id, frame pointers, unwind tables, recorded
  GCC switches, allocator, and JVM presence for a binary or running process.
- Add `cpp-performance-investigation`, a separate entry point for native
  C/C++ symptoms and JNI code implicated by a Java investigation, with
  bounded perf, `/proc`, and core-file triage and routing to shared Linux skills.
- Support Codex plugin installs: Codex reads the existing marketplace, and a new
  `.codex-plugin/plugin.json` supplies its UI metadata. The README covers
  Codex plugin install and update.

## [0.3.2] - 2026-09-21

- Keep bounded JFR captures polling through documented `STARTING`, `STOPPING`,
  `STOPPED`, and `CLOSED` lifecycle states instead of failing during normal
  duration-triggered finalization; unknown responses now include their raw
  status for diagnosis.

## [0.3.1] - 2026-09-21

- Unify unexplained JVM symptom triage under `java-performance-investigation`,
  including hangs, crashes, and offline incidents. Keep `linux-jvm-debug` as a
  supporting toolkit with compatible script paths and install its helpers with
  the entry skill.
- Fix plain-text guided debug reports failing when formatting routing evidence.

## [0.3.0] - 2026-09-18

- Preserve interrupted captures and enforce launch deadlines, per-file limits
  and monitored aggregate storage budgets for perf and vendor wrappers.
- Install guided-debug and vendor-capture script dependencies in subset installs.
- Trace recommendations to observations, explain uncertainty and verification,
  and remove confidence claims based on warning counts or severity.

- Add structured service-evidence parsing, vendor result summaries, ranked
  recommendations, target identity guards, and guided bounded capture runners.
- Add a guided debug CLI, service-evidence summariser, portable Intel/AMD
  readiness report, bounded perf capture, and repeated recovery comparison.
- Add a top-level Linux JVM debug workflow with ranked symptom hints and
  server-side journal, systemd, and coredump routing.
- Extend offline capture with bounded optional systemd, journal, and coredump
  evidence for restart, OOM, and crash investigations.
- Fix the offline collector's host audit, which failed on every run without
  `--cpus`, and the audit's own error message for that case.
- Keep child-process command lines (`jdk.ProcessStart`) out of offline JFR
  recordings: sensitive events are now switched off when recording starts and
  scrubbed again afterwards; JRE-only hosts without a `jfr` tool get
  source-disabled recordings and collapsed async-profiler stacks.
- Bound every JVM diagnostic command in the offline collector and the NMT
  snapshot helper; a JVM that does not answer is recorded as unresponsive and
  the capture continues with thread states and kernel wait channels.
- Offline collector: unattended starts (`--start-at`, `--trigger cpu|rss|gcpause|file`,
  `--max-wait`), several JVMs per run, `--check` preflight, a `--list` that
  shows JVMs owned by other users, per-interval sampling, process, cgroup, and
  thread-state counters, optional JSON thread dumps and class histograms, GC
  log discovery from the command line, a text `--digest`, `--split-mb` parts,
  vendor artifacts counted against the size budget, and capture from
  Kubernetes debug containers in another mount namespace.
- `build-kit.sh`: optional checksum-pinned async-profiler (also used for JVM
  attach on JRE-only runtimes) and a single-file self-extracting kit for
  console-only hosts; the GC summariser now ships in the kit.
- `analyze-bundle.py`: loose-file directories and extracted bundles as input,
  `analysis.json` and `--json`, hot threads joined to stacks, busiest-interval
  time series with GC pauses on the same clock, host steal, iowait, disks,
  softirqs, memory, cgroup throttling and OOM events, flame graphs via
  `jfrconv`, lock owners, deadlocks, stuck and virtual threads, class
  histogram growth, `hs_err` crash logs, JVM-start-based GC windows without
  `jcmd`, rejection of unknown bundle formats and truncated archives.
- New `compare-bundles.py` compares a baseline and an incident analysis,
  including a differential flame graph when `jfrconv` is available.
- Document how to update the plugin and `install.sh` installs.
- Add `unattended-trigger-capture` and `digest-triage` eval cases.
- Harden compatibility matrix private output, path checks, timeout validation, and JVM metadata parsing.
- Add a bounded JDK compatibility matrix runner for the vendor workload,
  preserving per-mode logs and failing closed on failed or unavailable JDKs.
- Record host CPU, kernel, virtualization, and JVM identity alongside matrix
  results so Intel/AMD and bare-metal/VM comparisons retain their context.
- Extend the vendor workload fixture with synchronization and scheduler-wait
  modes, with explicit limits on contention and queueing interpretation.
- Extend the offline capture kit with checksum-verified vendor profiler
  companion artifacts and report their paths without parsing proprietary data.
- Add a bounded, read-only schedstat delta tool for per-thread run-queue delay,
  with PID-reuse checks and scheduler/off-CPU correlation guidance.
- Add a read-only frequency, thermal, boost, and powercap snapshot for
  frequency-aware Intel and AMD Java comparisons.
- Add a read-only container profiling readiness report for PID namespaces,
  mount namespaces, cgroup limits, capabilities, seccomp, and effective CPU and
  memory placement.
- Add an Intel/AMD CPU capability matrix covering hybrid cores, AMD CCD/CCX and
  EPYC scopes, VM vPMU boundaries, and the minimum evidence required before
  selecting model-specific events.
- Add a vendor-neutral Java/JIT symbol validation check for exported profiler
  reports, with required-method checks, unresolved-frame markers, JSON output,
  and conservative inconclusive status.
- Add a bounded vendor-profiler comparison runner that interleaves profiled and
  unprofiled fixed-work commands, checks completion and checksums, and preserves
  raw output with a JSON overhead summary.
- Add vendor-specific VTune/uProf runbooks, Intel PCM and AMD system-counter guidance, an offline result handoff, and a tested synthetic Java attribution fixture. AMD Java hotspots attribution succeeded; Intel collection remains blocked.
- Preserve incomplete rollback status after interruption and allow recovery retries.
- Require every measured allocation round to meet the budget; reject invalid latency data without losing integer timestamp precision.
- Fail incomplete JFR reports and bound diagnostic command waits during capture.
- Correct Claude plugin invocation and use the documented Codex personal skill directory, with an explicit legacy-directory override.
- Test installer lifecycle outside the checkout; document selective-install limitations, per-helper capture guarantees, and compatibility evidence.
- Separate walkthrough diagnostics from repeated comparisons and add behavioral regression eval cases.

Making the collection understandable to newcomers and proving it works as skills.

### Added
- `java-offline-capture` skill for hosts that cannot run an agent: `build-kit.sh`
  makes a reproducible, checksummed collector kit (bash only on the target);
  `collect.sh` captures a bounded bundle (JFR new or dump of a continuous
  recording, GC logs found from the JVM's log configuration, jcmd and NMT
  snapshots, thread dumps, optional async-profiler, before/after `/proc`
  deltas, host audit), scrubs secrets from JFR with `jfr scrub`, and seals it
  with checksums; `analyze-bundle.py` safely extracts, verifies, and writes
  `ANALYSIS.md` with findings and next skills. Runbooks for VMs, Kubernetes,
  JRE-only runtimes, and always-on incident recording.
- `requires.txt` skill dependencies, followed by `install.sh` and checked by the validator.
- `java-flight-recorder` skill: JFR settings, `jcmd` control, custom events,
  streaming; `jfr-capture.sh` (bounded recording of a running JVM, no root) and
  `jfr-report.sh` (curated `jfr view` reports). Covers the JDK 25 CPU-time
  sampling and method timing events.
- `java-low-latency-patterns` skill: allocation-free hot paths, single-writer
  ring buffers, wait strategies, flyweight encoding, FFM off-heap memory, JCStress
  verification; `AllocationProbe.java` measures bytes per operation and gates CI.
- `make-lab-plan.py`: host-specific lab-mode plans for the `benchmark-host`,
  `irq-isolation`, and `quiet-watchdogs` profiles.
- Containers and Kubernetes reference for the investigation skill.
- Documentation: plain-language README, [getting started](docs/getting-started.md)
  with a no-root path and glossary, [annotated real output](docs/examples.md)
  from every tool, and an end-to-end [walkthrough](docs/walkthrough/README.md)
  (p99.99 2.18 ms → 55 µs) with a runnable demo program.
- Eval suite for Claude Code (`evals/`): 9 trigger-and-outcome cases and 2
  cases where no skill should load.
- Tests for all new scripts; optional walkthrough smoke test
  (`WALKTHROUGH_TESTS=1`); relative-link checking in the validator.

### Changed
- One name everywhere: the Claude plugin is now `optimization-skills` (was
  `java-optimization-skills`). Reinstall with
  `claude plugin install optimization-skills@optimization-skills`.
- Skill descriptions rewritten in plain words and shortened by 46%. The
  always-on context cost for all 19 skills is about 1,400 tokens.
- `gc-log-summary.py`: `--from-uptime`/`--to-uptime` windows to exclude
  warmup; a log with zero pauses is now a successful result, not an error.
- `latency-report.py`: flags queueing at p99.9 and p99.99, not only p99, where
  coordinated omission usually hides.
- `lab-tune.sh`: IRQ affinity writes refused by the kernel (managed IRQs) are
  reported and skipped instead of aborting the plan.
- Lab-mode docs explain why both root and the hostname acknowledgement are required.

### Fixed
- `jfr-capture.sh` polled until timeout after a recording finished (the
  "Could not find NAME" message matched the name check).
- `cmd | grep -q` under `pipefail` could report a false negative when grep
  exited early (in `jfr-capture.sh` this could end the wait loop too soon);
  replaced in `jfr-capture.sh`, `native-memory-snapshot.sh`, and the collector.

## [0.2.0] - 2026-09-13

First release usable from both OpenAI Codex and Claude Code.

### Added
- One `skills/` tree for both agents: Claude Code plugin and marketplace,
  `.claude/skills` and `.agents/skills` links, `install.sh` for personal installs.
- Skills: `java-performance-investigation`, `java-gc-tuning`, `java-jit-codegen`,
  `java-native-memory`, `linux-low-latency-tuning` (with lab mode),
  `java-latency-measurement`, `linux-ebpf-io-network`.
- Scripts: GC/safepoint and JIT log summaries, NMT snapshot and compare, host
  jitter audit, lab-mode tuner with verified rollback, jitter meter,
  coordinated-omission-aware latency report, bounded BCC capture wrapper.
- Bundled validator enforcing both agents' rules; tests on real JDK logs; CI on
  JDK 21 and 25.

### Changed
- Existing skills reworded to agent-neutral references; readiness check
  reports bpftrace and BCC.

## [0.1.0]

Initial Codex skill collection: profiling readiness, async-profiler, JMH, Linux
perf, performance patterns, VTune/uProf, hardware counters, cache efficiency,
NUMA and affinity.

[0.3.0]: https://github.com/tayloralj/optimization-skills/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/tayloralj/optimization-skills/releases/tag/v0.2.0
