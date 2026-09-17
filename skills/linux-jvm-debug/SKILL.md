---
name: linux-jvm-debug
description: Turn a Linux Java symptom into a safe debug plan with ranked hints, readiness checks, and an online or offline evidence path. Use when a server-side JVM needs diagnosis and the next tool is unclear.
---

# Linux JVM Debug

Start here when a Linux JVM is slow, stuck, restarting, consuming CPU or
memory, or showing latency spikes. This skill produces a decision-ready plan;
it does not attach to a process or change a host by itself.

For a single guided report, run `scripts/debug.py --symptom TEXT [--json]`.
Pass `--bundle DIR` when an offline capture has returned; the command adds the
service evidence summary to the routing output.
For a ranked follow-up from an analysis, pass `--analysis analysis.json` or
run `scripts/recommendations.py analysis.json` directly.
Use `scripts/evidence-report.py RESULT_DIR [--baseline BASELINE_ANALYSIS]` to
merge analysis, service, perf, and vendor summaries and report confidence.
Before any attach-oriented command, verify the discovered target with
`scripts/target-guard.py --pid PID --user USER --start-ticks TICKS`; it rejects
the example PID `12345`, non-Java executables, owner changes, and PID reuse.

1. State the symptom, affected JVM, time window, offered load, and the result
   that would confirm the suspected cause. Treat any PID in an example,
   including `12345`, as a placeholder; discover and verify the real target.
2. Run `scripts/debug-hints.py --symptom TEXT` to get ranked evidence paths and
   read `references/server-debug.md` for the matching Linux commands.
3. Run the `profiling-readiness` skill before selecting perf, eBPF, or an
   attach profiler. Prefer launch-time JFR when permissions or namespaces
   block attachment.
4. If an agent cannot run on the target, use the `java-offline-capture` skill.
   Build a kit locally, have the operator run its check and dry-run as the JVM
   user, then analyse the returned bundle or digest. Include optional systemd,
   journal, and crash evidence when the symptom involves restarts or OOMs.
5. Follow the selected specialist skill, one hypothesis at a time. Preserve
   raw output, timestamps, identity checks, and a healthy comparison capture.
6. End with a confirmed or inconclusive diagnosis, next evidence, and rollback;
   never call a missing tool or failed capture proof that the issue is absent.

The hints are routing advice, not thresholds or automatic tuning. Read-only
collection remains the default; production attach and root-only diagnostics
need the operator's approval.
