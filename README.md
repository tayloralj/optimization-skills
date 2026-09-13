# Java Optimization Skills

Agent skills for measuring and improving Java/JVM performance on Linux, usable
from both **OpenAI Codex** and **Claude Code**. Low-latency systems come first
(single-writer pipelines, messaging, matching engines), and general service
throughput is covered too. JDK 21 and 25 LTS are the baseline.

The collection is deliberately evidence-first. It checks whether the host can
collect trustworthy data, keeps fixed-rate latency tests separate from
maximum-throughput tests, rejects latency numbers distorted by coordinated
omission, and requires a production-fidelity check before trusting a
microbenchmark.

## Skills

Start with `java-performance-investigation` when the cause is unknown; it routes
to the others. Install `profiling-readiness` with every specialised skill.

| Skill | Use it for |
| --- | --- |
| `java-performance-investigation` | Triage a symptom into an objective, workload class, and routed plan |
| `profiling-readiness` | Read-only host, tool, permission, and topology checks; operator remediation guidance |
| `java-latency-measurement` | Open-loop load, coordinated omission, HdrHistogram, jitter meter, latency comparison |
| `java-gc-tuning` | G1/ZGC/Shenandoah choice and tuning; GC and safepoint log analysis; heap retention |
| `java-jit-codegen` | Inlining, deoptimization, code cache, assembly, warmup, CDS and JDK 25 AOT cache |
| `java-native-memory` | NMT ledger, RSS beyond heap, direct/mapped buffers, malloc arenas, cgroup OOM |
| `linux-low-latency-tuning` | Host jitter audit, CPU isolation, IRQs, C-states, THP, thread pinning; opt-in lab mode |
| `linux-ebpf-io-network` | Off-CPU, run-queue, syscall, storage, and network latency with bounded eBPF captures |
| `java-async-profiler` | CPU, allocation, lock, wall-clock, and JFR profiling |
| `java-jmh-benchmarking` | Production-faithful Java microbenchmarks and reproducible comparisons |
| `java-linux-perf` | Linux `perf` with Java/JIT-aware symbolization and portable event selection |
| `java-performance-patterns` | Evidence-backed Java optimization patterns |
| `java-vtune-uprof` | Vendor-aware Intel VTune and AMD uProf workflows |
| `java-hardware-counters` | Portable PMU experiment design and counter interpretation |
| `java-cache-efficiency` | Java cache locality, object layout, and false-sharing analysis |
| `java-numa-affinity` | NUMA, LLC/CCD topology, first-touch, and CPU-affinity experiments |

## Install

Requirements: Linux, Bash 4+, GNU userland, Python 3.9+ (standard library
only), and a JDK 21+ for the Java helper. Profilers, BCC/bpftrace, and JOL are
optional and detected at run time. Scripts were exercised on JDK 25, kernel 7.0,
async-profiler 4.x, BCC (`bpfcc-tools`), and bpftrace 0.25.

### Claude Code (plugin)

```bash
claude plugin marketplace add tayloralj/optimization-skills
claude plugin install java-optimization-skills@optimization-skills
```

### Codex and/or Claude Code (personal skill directories)

```bash
git clone git@github.com:tayloralj/optimization-skills.git
cd optimization-skills
./install.sh                    # symlink every skill into ~/.codex/skills and ~/.claude/skills
./install.sh --codex java-gc-tuning java-latency-measurement   # subset, Codex only
./install.sh --claude --copy    # copy instead of link
./install.sh --uninstall        # remove only entries this repository installed
```

`CODEX_HOME` and `CLAUDE_CONFIG_DIR` are honoured. The installer never overwrites
a skill directory it did not create. Restart the agent session afterwards.

### Working inside this repository

`.agents/skills/` (Codex) and `.claude/skills/` (Claude Code) contain symlinks to
`skills/`, so both agents discover the skills when started in a checkout.

### Invoking

- Codex: `$java-gc-tuning analyse these GC logs`, or let Codex select by description.
- Claude Code: `/java-gc-tuning analyse these GC logs`, or let Claude select by description.

## Safety and evidence rules

- Never change kernel settings, capabilities, CPU governors, affinity, or a
  running service without explicit operator approval.
- Host tuning is read-only by default. `linux-low-latency-tuning` has an opt-in
  **lab mode** for hosts the user declares expendable: allowlisted runtime knobs
  only, applied by the operator as root with a hostname acknowledgement, with
  recorded and verified rollback. Boot parameters and persistent configuration
  always stay operator-owned.
- eBPF captures are bounded and PID-scoped where possible; the wrapper prints
  the command for the operator instead of escalating privileges.
- Smoke-test the actual event on the actual host. A numeric
  `perf_event_paranoid` value alone is not proof that collection works.
- Detect CPU vendor/model and select only events listed by the installed tool.
- Treat profiles as observations, not proof of causality. Verify a change with
  representative load, repetitions, variance, and a rollback path.
- Measure latency from intended start times; report full distributions with
  sample counts.
- Confirm that benchmark setup and data structures still model production code.
- Do not publish profiles, command lines, JFRs, heap dumps, or paths until they
  have been checked for secrets and customer data.

## Development

```bash
./scripts/validate-all.sh   # bundled validator + Codex quick_validate + claude plugin validate (when installed)
./tests/run-tests.sh        # script tests against real JDK log fixtures and fake /sys trees
```

See [`AGENTS.md`](AGENTS.md) for the skill authoring contract shared by both
agents. CI runs validation, ShellCheck, and tests on JDK 21 and 25. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for source inspirations.

## Licence

MIT. See [`LICENSE`](LICENSE).
