# Optimization Skills

**Help your AI coding agent find and fix Java performance problems on Linux.**

Optimization Skills is a set of skills (instructions plus small tools) that
Claude Code and OpenAI Codex load when you ask about Java performance: slow
requests, latency spikes, GC pauses, memory growth, jittery hosts, suspicious
benchmarks. Instead of guessing at JVM flags, the agent follows an engineer's
method. It checks what the machine can measure, collects evidence, changes one
thing, and proves the result.

> **Example.** "Our order gateway's p99.99 is 2 ms but the handler is fast."
> The agent shows the time is spent *waiting*, not computing, and ties the wait
> to GC pauses. It finds the allocating code with JDK Flight Recorder (no root
> needed), rewrites it allocation-free, proves zero allocation, and re-runs the
> same test: **p99.99 2.18 ms → 55 µs**. The full story, with real output, is in
> [the walkthrough](docs/walkthrough/README.md).

## Who it is for

- Java developers and SREs with JVM services or jobs **on Linux** (JDK 21 or 25).
- Built latency-first (trading, messaging, real-time pipelines); most of it
  applies to ordinary services too.
- No profiling experience or root access needed to start.

Not for macOS or Windows hosts, non-JVM code, or front-end performance.

## Install

The GitHub repository is currently **private**; you need read access to it.

**Claude Code** (plugin):

```bash
claude plugin marketplace add git@github.com:tayloralj/optimization-skills.git
claude plugin install optimization-skills@optimization-skills
```

**Codex, or Claude Code without plugins:**

```bash
git clone git@github.com:tayloralj/optimization-skills.git
cd optimization-skills
./install.sh                 # links every skill into ~/.codex/skills and ~/.claude/skills
./install.sh --codex         # Codex only; --claude for Claude only; --copy to copy instead of link
./install.sh --uninstall     # removes only what this installer created
```

Restart the agent afterwards. Requirements: Linux, Bash 4+, Python 3.9+ (standard
library only), and a JDK. Profilers, BCC/bpftrace, and JOL are optional and
detected when needed.

## Use it

Describe the problem in your own words. The matching skill loads automatically:

- "My service's p99 latency jumps every few minutes. Help me find out why."
- "Summarise these GC logs and tell me whether pauses are a problem."
- "This JVM's RSS keeps growing but the heap is flat."
- "Review this hot path for allocation and contention."
- "Is this machine ready for latency testing on CPUs 4-7?"
- "Production can't run an agent. Give the ops team a kit to capture the JVM during tonight's peak, and I'll send you the result."

Or name a skill directly: `/java-gc-tuning` in Claude Code, `$java-gc-tuning` in
Codex. **New here?** Read [Getting started](docs/getting-started.md): what to
ask, what the agent will and won't do, the no-root path, and a glossary.

## What's included

Start with **`java-performance-investigation`** if you don't know the cause; it
routes to the rest.

| Area | Skill | Helps you |
| --- | --- | --- |
| Start | `java-performance-investigation` | Turn a symptom into a goal, workload type, and plan |
| | `profiling-readiness` | Find out what this host lets you measure (read-only) |
| Measure | `java-latency-measurement` | Get latency numbers that are real: open-loop load, percentiles, jitter meter |
| | `java-flight-recorder` | Record and read JFR evidence with no root or extra tools |
| | `java-jmh-benchmarking` | Write and run microbenchmarks that model production |
| | `java-offline-capture` | Collect evidence on prod/QA hosts that can't run an agent; analyse the bundle later |
| Profile | `java-async-profiler` | CPU, allocation, lock, and wall-clock profiles |
| | `java-linux-perf` | Linux `perf` with working Java symbols |
| | `java-hardware-counters` | CPU counter experiments (cache, branch, IPC) |
| | `java-vtune-uprof` | Intel VTune and AMD uProf |
| | `linux-ebpf-io-network` | Where threads wait: scheduler, disk, network (eBPF) |
| JVM | `java-gc-tuning` | Understand GC and safepoint pauses; choose and tune collectors |
| | `java-jit-codegen` | Inlining, deoptimization, warmup, startup caches |
| | `java-native-memory` | Memory outside the heap, container OOM kills |
| Code | `java-low-latency-patterns` | Allocation-free hot paths, ring buffers, flyweights, off-heap |
| | `java-performance-patterns` | Evidence-backed fixes for common bottlenecks |
| | `java-cache-efficiency` | False sharing, object layout, cache locality |
| Host | `linux-low-latency-tuning` | Audit host jitter; CPU isolation and pinning; opt-in lab mode |
| | `java-numa-affinity` | NUMA, cache-domain, and thread-placement experiments |

See [real output from every tool](docs/examples.md) and how to read it.

## Safety by design

Profilers and kernel tweaks can hurt a live system, and performance numbers are
easy to get wrong in convincing ways. So the skills are **read-only by default**:

- No `sudo`, no kernel or service changes, and no production JVM restarts
  without your explicit approval. When root is needed, the agent prints the
  exact command for you to run.
- Captures are time- and size-limited and target only processes you own.
- **Lab mode** (`linux-low-latency-tuning`) is for machines you declare
  expendable. It generates a host-specific plan of reversible runtime
  settings, which you apply as root. Every original value is recorded, and
  rollback is verified.
- Results need evidence: a baseline, repetitions, and the same test before and
  after. Profiles and recordings are treated as sensitive data.

## Project

- [CHANGELOG](CHANGELOG.md) · [Getting started](docs/getting-started.md) ·
  [Walkthrough](docs/walkthrough/README.md) · [Examples](docs/examples.md)
- Contributing and skill-authoring rules: [`AGENTS.md`](AGENTS.md)
- Checks: `./scripts/validate-all.sh`, `./tests/run-tests.sh`, and evals in
  [`evals/`](evals/README.md); CI runs on JDK 21 and 25
- Names: the repository, Claude marketplace, and plugin are all
  `optimization-skills`
- Sources and credits: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) · Licence: MIT ([`LICENSE`](LICENSE))
