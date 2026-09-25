# Optimization Skills

**Help your AI coding agent find and fix Java performance problems on Linux.**

Optimization Skills is a set of skills (instructions plus small tools) that
Claude Code and OpenAI Codex load when you ask about Java performance: slow
requests, latency spikes, GC pauses, memory growth, jittery hosts, suspicious
benchmarks. Instead of guessing at JVM flags, the agent follows an engineer's
method. It checks what the machine can measure, collects evidence, changes one
thing, and proves the result.

> **Example.** Investigate a slow order gateway by separating handler time from
> queueing, checking GC evidence, and comparing repeated unprofiled runs.
> The [walkthrough](docs/walkthrough/README.md) uses a synthetic workload and
> real tool output; its measurements are illustrative, not a promised speedup.

## Who it is for

- Java developers and SREs with JVM services or jobs **on Linux** (JDK 21 or 25).
- Built latency-first (trading, messaging, real-time pipelines); most of it
  applies to ordinary services too.
- No profiling experience or root access needed to start.

Not for macOS or Windows hosts, or front-end performance. Native C and C++ support
(GNU/Linux toolchain) starts at `cpp-performance-investigation`.

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
./install.sh                 # links every skill into ~/.agents/skills and ~/.claude/skills
./install.sh --codex         # Codex only; --claude for Claude only; --copy to copy instead of link
./install.sh --uninstall     # removes only what this installer created
```

Restart the agent afterwards. Requirements: Linux, Bash 4+, GNU coreutils (including `timeout`),
Python 3.9+ (standard library only), and a JDK 21 or 25. Profilers, BCC/bpftrace, and JOL are optional and
detected when needed.

The full install is recommended. Named subsets include readiness and declared helper dependencies, but omit
other skills referenced by their workflows. Set `CODEX_SKILLS_DIR` to override the
Codex destination. For a previous legacy install, remove its owned entries with
`CODEX_SKILLS_DIR="$HOME/.codex/skills" ./install.sh --codex --uninstall`, then
install into the default location. Keep the checkout in place for symlink installs.

### Update to the latest version

**Claude Code plugin:** refresh the marketplace, then update the plugin:

```bash
claude plugin marketplace update optimization-skills
claude plugin update optimization-skills@optimization-skills
claude plugin list                     # confirm the new version
```

**`install.sh` installs (Codex or Claude):** pull the checkout, then re-run the
installer with the options you used the first time. Linked skills already follow
the checkout; the re-run links skills added since, and with `--copy` it
replaces the copies it made earlier:

```bash
cd optimization-skills
git pull
cat VERSION
./install.sh                 # or: ./install.sh --copy, --codex, --claude
```

Restart the agent after either route. The [changelog](CHANGELOG.md) lists what
changed. Collector kits already handed to operators do not update themselves:
rebuild with `build-kit.sh` and send the new kit. The analyser still reads
bundles from older kits that use the same `bundle_format`.

## Use it

Describe the problem in your own words. The agent can select a matching skill automatically:

- "My service's p99 latency jumps every few minutes. Help me find out why."
- "Summarise these GC logs and tell me whether pauses are a problem."
- "This JVM's RSS keeps growing but the heap is flat."
- "Review this hot path for allocation and contention."
- "Is this machine ready for latency testing on CPUs 4-7?"
- "Production can't run an agent. Give the ops team a kit to capture the JVM during tonight's peak, and I'll send you the result."

Or name a skill directly: `/optimization-skills:java-gc-tuning` with the Claude
plugin, `/java-gc-tuning` with standalone Claude skills, or `$java-gc-tuning`
in Codex. **New here?** Read [Getting started](docs/getting-started.md): what to
ask, what the agent will and won't do, the no-root path, and a glossary.

## What's included

Start with **`java-performance-investigation`** for any unexplained Java symptom,
including slowness, hangs, crashes, and OOMs. It chooses online or offline evidence
and routes to a specialist. If you already know the tool or have an artifact to
analyse, go directly to that specialist. `linux-jvm-debug` provides supporting
helpers; its existing commands remain available.

| Area | Skill | Helps you |
| --- | --- | --- |
| Start | `java-performance-investigation` | Define the problem, choose online/offline evidence, and route to a specialist |
| Support | `linux-jvm-debug` | Generate debug reports, check target identity, and summarize evidence |
| | `profiling-readiness` | Find out what this host lets you measure (read-only) |
| Native | `cpp-performance-investigation` | Start a C/C++ (GNU/Linux) investigation and route it to evidence |
| | `cpp-build-readiness` | Check a C/C++ binary or process (including JNI code) gives usable stacks |
| Measure | `java-latency-measurement` | Get latency numbers that are real: open-loop load, percentiles, jitter meter |
| | `java-flight-recorder` | Record and read JFR evidence with no root or extra tools |
| | `java-jmh-benchmarking` | Write and run microbenchmarks that model production |
| | `java-offline-capture` | Collect evidence on prod/QA hosts that can't run an agent, on a schedule or trigger; analyse bundles, digests, or loose files later |
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
- JVM attach helpers check ownership and target identity. BPF also supports
  explicitly selected system-wide, operator-run captures. Duration and storage
  controls vary by helper; see [capture guarantees](docs/compatibility.md#capture-guarantees).
  Instruction-level guardrails are not a sandbox or a hard resource limit.
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
- [Compatibility and validation status](docs/compatibility.md)
- [Vendor-profiler investigation and validation gaps](docs/vendor-profilers.md)
- Sources and credits: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) · Licence: MIT ([`LICENSE`](LICENSE))
