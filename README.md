# Java Optimization Skills

Public Codex skills for measuring and improving Java/JVM performance on Linux.
The collection is deliberately evidence-first: it checks whether the host can
collect trustworthy data, distinguishes fixed-rate latency tests from maximum
throughput tests, and requires a production-code fidelity check before a
microbenchmark is trusted.

## Skills

| Skill | Use it for |
| --- | --- |
| `profiling-readiness` | Read-only host, tool, permission, and topology checks; operator remediation guidance |
| `java-async-profiler` | CPU, allocation, lock, wall-clock, and JFR profiling |
| `java-jmh-benchmarking` | Production-faithful Java microbenchmarks and reproducible comparisons |
| `java-linux-perf` | Linux `perf` with Java/JIT-aware symbolization and portable event selection |
| `java-performance-patterns` | Evidence-backed Java optimization patterns |
| `java-vtune-uprof` | Vendor-aware Intel VTune and AMD uProf workflows |
| `java-hardware-counters` | Portable PMU experiment design and counter interpretation |
| `java-cache-efficiency` | Java cache locality, object layout, and false-sharing analysis |
| `java-numa-affinity` | NUMA, LLC/CCD topology, first-touch, and CPU-affinity experiments |

Install `profiling-readiness` with every specialised skill and start there. Its script does not use `sudo`, install tools,
change sysctls, attach to a process, or persist configuration. If the host is
restricted, the skill explains the least-privilege options and their rollback.

## Install

These skills target Linux HotSpot/OpenJDK workloads. The helper scripts require
Bash 4 or newer and GNU userland tools. They were forward-tested with
async-profiler 4.4; always check the installed release's help before advanced
use.

Copy `skills/profiling-readiness` plus the specialised skill directories you
need into your Codex skills directory, or install the repository with your
normal Codex skill installer. A specialised skill copied alone has an incomplete
preflight workflow. Invoke a skill explicitly with its `$skill-name` while
evaluating the collection.

For a manual personal install:

```bash
install -d "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/profiling-readiness skills/java-async-profiler \
  "${CODEX_HOME:-$HOME/.codex}/skills/"
```

## Safety and evidence rules

- Never change kernel settings, capabilities, CPU governors, affinity, or a
  running service without explicit operator approval.
- Smoke-test the actual event on the actual host. A numeric
  `perf_event_paranoid` value alone is not proof that collection works.
- Detect CPU vendor/model and select only events listed by the installed tool.
- Treat profiles as observations, not proof of causality. Verify a change with
  representative load, repetitions, variance, and a rollback path.
- Confirm that benchmark setup and data structures still model production code.
- Do not publish profiles, command lines, JFRs, or paths until they have been
  checked for secrets and customer data.

## Development

Run `./scripts/validate-all.sh` from the repository root. This checks skill
metadata and structure only; it is not a profiler, permission, or production
readiness test. The validation is offline and does not require elevated privileges. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for source inspirations.

## Licence

MIT. See [`LICENSE`](LICENSE).
