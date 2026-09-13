# Changelog

All notable changes to this project. Versions follow
[semantic versioning](https://semver.org/); the plugin version lives in `VERSION`
and `.claude-plugin/plugin.json`.

## [0.3.0] - unreleased

Making the collection understandable to newcomers and proving it works as skills.

### Added
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
- Eval suite for Claude Code (`evals/`): 8 trigger-and-outcome cases and 2
  cases where no skill should load.
- Tests for all new scripts; optional walkthrough smoke test
  (`WALKTHROUGH_TESTS=1`); relative-link checking in the validator.

### Changed
- One name everywhere: the Claude plugin is now `optimization-skills` (was
  `java-optimization-skills`). Reinstall with
  `claude plugin install optimization-skills@optimization-skills`.
- Skill descriptions rewritten in plain words and shortened by 46%. The
  always-on context cost for all 18 skills is about 1,300 tokens.
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

[0.3.0]: https://github.com/tayloralj/optimization-skills/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/tayloralj/optimization-skills/releases/tag/v0.2.0
