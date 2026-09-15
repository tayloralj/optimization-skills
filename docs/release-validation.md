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

Automatic approval review initially rejected the external retry pending
explicit private-plugin data-transfer approval. After the user approved it,
Claude Code 2.1.272 completed `vendor-perf-blocked` outside the restricted
sandbox: plugin 1.00, baseline 1.00, delta 0.00, three PASS votes per arm,
105 seconds, $0.196756 total, exit 0. Publishing remained disabled. Neither
prior execution error recurred; this does not isolate their original cause.

The private local report is in
`evals/results/2026-09-15T17-58-04-560Z/`. A subsequent vendor-only suite run
covered all three vendor cases with one repetition each, both plugin and
baseline: every arm scored 1.00 with three PASS votes, total cost $0.57, and
delta 0.00. Its report is in
`evals/results/2026-09-15T19-35-26-305Z/`. The vendor behavioral gate is closed;
the broader non-vendor suite remains to be scored before tagging.

A complete-suite attempt launched 18 cases but timed out on the first
`benchmark-host-lab-mode` arm after 300 seconds and was interrupted at $0.30.
That partial run is retained as a timeout diagnostic, not as a score.

Shorter targeted evaluations subsequently passed for `gc-log-triage` (1.00
with and without the plugin) and `closed-loop-latency` (1.00 with the plugin,
0.67 without, delta +0.33). These cases provide valid behavioral evidence;
the remaining non-vendor cases still need targeted runs.
