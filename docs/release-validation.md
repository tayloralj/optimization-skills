# 0.3.0 release validation

Validation performed on 2026-09-15 against main `6d548cd` plus the release
hardening changes in this PR. Version files already agree on 0.3.0; tagging
and publication remain pending the behavioral evaluation gate.

## Repository checks

- Full `WALKTHROUGH_TESTS=1 ./tests/run-tests.sh`: 125 passed, zero failed on
  Temurin 25.0.2; 126 passed, zero failed on Oracle 21.0.10.
- ShellCheck 0.11.0, distribution package extracted privately without system
  installation: warning-level check passed over all required shell scripts.
- Bundled, Codex, and Claude validators passed for 19 skills. The known
  root CLAUDE.md plugin-context warning remains.
- Compatibility regression tests exercise existing destinations, symlink parents,
  nonfinite timeouts, missing JDKs, private permissions and real JVM metadata.

## AMD evidence

Local Ryzen 9 7900, uProf 5.3.521, `/usr/bin/java` Ubuntu OpenJDK 25.0.4.
The installed CLI help confirmed `profile --config cpi` and `--config ibs`.
Both self-owned launches completed within a 60-second timeout and generated
reports containing nonzero samples attributed to `VendorWorkload::chaseBatch`.
The fixture used 30,000 measured batches, 2,000 warmup batches, a 64 MiB
working set, a fixed 256 MiB heap, and frame pointers.

Three interleaved unprofiled/hotspots pairs completed with matching operations
and checksum 250703326249. Relative measured-window times were +1.47%, -1.31%,
and -6.87% (mean -2.23%). These noisy observations do not demonstrate a speedup
or a reliable profiler-overhead estimate. Profiler finalization is excluded.
Java attribution appears in all three hotspots reports. Source-line accuracy,
steady-state-only counter filtering, other JDK/profile combinations and EPYC
system counters require additional evidence.

Private local artifacts are under `/tmp/performance-hardware-check/`:
`cpi/`, `ibs/`, `hotspot-sessions/`, and `comparison/summary.json`.
These temporary artifacts are not shipped or guaranteed durable.

## Intel VM evidence

The authorized KVM guest still reports ptrace_scope=1 and
perf_event_paranoid=4, with no core CPU event source. A bounded VTune 2026.4
software-mode Java launch exits 1 at the ptrace policy check. PCM 202502 exits 1
and reports missing vPMU and MSR/PCI access. No host policy was changed.
Software sampling needs an operator-approved ptrace policy decision; hardware
validation additionally needs suitable hypervisor or physical-host access.

## Behavioral evaluation and release gate

The installed evaluator accepts the repository's prompt.md plus graders/*.md
layout. The retained failed run has no model trace. Its missing-prompt error
and the grader's EAI_AGAIN are separate failures; the latter is consistent
with restricted network access but has not been proven to be the sole cause.

An authorized $5-capped retry outside the sandbox was rejected by automatic
approval review because private plugin data could be transmitted to the Claude
API. Explicit data-transfer approval is required before another external run.
The proposed payload comprises the selected synthetic evaluation prompt,
plugin instructions/resources loaded by the evaluator, model responses and
rubric; report publishing remains disabled. The missing-prompt failure still
requires diagnosis after network access is authorized. No behavioral pass is
claimed and v0.3.0 has not been tagged or published.
