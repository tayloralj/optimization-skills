---
name: linux-jvm-debug
description: Supporting Linux JVM tools for ranked hints, target identity checks, and evidence reports. Use after investigation routing when a guided debug report or capture helper is needed.
---

# Linux JVM Debug

Script dependencies are declared in `requires.txt` and installed automatically.

The `java-performance-investigation` skill owns initial symptom triage and the
online/offline decision. Use these helpers within that investigation. Existing
explicit invocations and script paths remain supported: if given only an
unexplained symptom, follow that entry workflow, then use the relevant helper
here. Do not send an investigation already in progress back through triage.

For a single guided report, run `scripts/debug.py --symptom TEXT [--json]`.
Pass `--bundle DIR` when an offline capture has returned; the command adds the
service evidence summary to the routing output.
For a ranked follow-up from an analysis, pass `--analysis analysis.json` or
run `scripts/recommendations.py analysis.json` directly.
Use `scripts/evidence-report.py RESULT_DIR [--baseline BASELINE_ANALYSIS]` to
merge analysis, service, perf, and vendor summaries and report confidence.

Recommendations cite JSON source paths and observations, include uncertainty,
and specify a verification experiment. Confidence is `unverified`: neither
warning severity nor finding count demonstrates causality. A supplied baseline
is labelled `not_compared` until metric units, workload, scope and time windows
are verified. Claude and Codex should show the leading action, its evidence,
uncertainty and verification step; do not turn routing hints into diagnoses.
Before any attach-oriented command, verify the discovered target with
`scripts/target-guard.py --pid PID --user USER --start-ticks TICKS`; it rejects
the example PID `12345`, non-Java executables, owner changes, and PID reuse.

## Helper selection

- `scripts/debug-hints.py --symptom TEXT` produces routing hints without a host
  check. Read `references/server-debug.md` for service and crash evidence commands.
- `scripts/debug.py` combines those hints with local readiness. Run it on the
  affected host; its readiness output describes the machine executing it, even
  when `--bundle` refers to evidence collected elsewhere. Use the offline
  capture skill's analyser for returned bundles when the target is inaccessible.
- Capture is opt-in: `scripts/debug.py --symptom TEXT --run --out DIR -- COMMAND`
  launches a bounded perf capture through the `java-linux-perf` skill's helper.
  Follow that skill's readiness, command validation, and approval requirements
  before using it; the default report does not launch or attach to a JVM.
- Use the recommendation and evidence-report helpers above to explain findings,
  uncertainty, and the next verification step. Preserve raw output and timestamps.

The hints are routing advice, not thresholds or automatic tuning. Read-only
collection remains the default; production attach and root-only diagnostics
need the operator's approval.
