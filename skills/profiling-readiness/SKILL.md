---
name: profiling-readiness
description: Read-only Linux and JVM profiling preflight for permissions, perf events, CPU topology, Java tools, and safe operator remediation. Use before async-profiler, Linux perf, PMU counters, VTune, uProf, NUMA, affinity, or production profiling, especially when perf_event_paranoid, containers, missing symbols, or unavailable tools may block trustworthy data.
---

# Profiling Readiness

Establish what the host can measure before selecting a profiler. Never infer
access from a sysctl value alone and never change the host during preflight.

## Workflow

1. Run `scripts/check-profiling-readiness.sh` on the target host or on a close
   replica. The script is read-only and performs only short self-process smoke
   tests.
2. Record the report with the profile evidence. Treat `status` as a routing
   result, not as a security-policy recommendation.
3. If `perf_smoke=failed`, inspect the captured reason. Prefer a verified
   unprivileged fallback such as launch-time JFR when it can answer the question.
   Tool presence is never reported as a successful async-profiler attach.
4. Read `references/remediation.md` only when a required measurement is blocked.
   Present the operator with the least-privilege option, scope, risk, validation,
   and rollback. Obtain explicit approval before any change.
5. Re-run the readiness script after an approved change. Do not call the host
   ready until the exact intended event succeeds.

## Interpret the report

- `READY_PERF_SOFTWARE_EVENT`: the bundled user-space software-event smoke test succeeded.
  Hardware events and attach/system-wide collection still require their own
  smoke tests.
- `DEGRADED_VERIFIED_JFR_FALLBACK`: `perf` is blocked, but a bounded launch-time
  JFR was created and parsed successfully. Attaching to an existing JVM remains
  a separate permission/namespace test.
- `FALLBACK_TOOL_PRESENT_UNVERIFIED`: async-profiler is installed and its version
  is readable, but no target attachment was attempted. Verify the exact target,
  attach mechanism, namespaces, event, and bounded output before relying on it.
- `TOOLS_PRESENT_NOT_TESTED`: smoke tests were disabled; do not infer readiness.
- `BLOCKED_PERMISSION_OR_TOOLING`: neither tested perf collection nor the safe
  Java fallback is available. Do not invent results; report the blocker.
- One NUMA node does not imply uniform cache access. Use the reported LLC count
  and CPU lists before affinity experiments.

## Guardrails

- Do not run `sudo`, `sysctl -w`, `setcap`, package managers, or service restarts.
- Do not weaken `kptr_restrict` unless kernel symbols are necessary; Java
  user-space work normally does not require that change.
- Do not recommend `CAP_SYS_ADMIN` as a convenient profiling shortcut. Prefer
  `CAP_PERFMON` where supported and scope capabilities to a dedicated service or
  tool after security review.
- Do not assume container permissions match the host. Check capabilities,
  seccomp, PID namespace visibility, and the host sysctl separately.
- Redact hostnames, usernames, process arguments, paths, and proprietary CPU or
  deployment details before publishing readiness output.
