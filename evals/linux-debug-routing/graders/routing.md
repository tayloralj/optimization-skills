---
type: llm
name: routing
---
Pass only if the response starts with a measurable symptom/window, routes through profiling readiness, selects offline capture because no agent is available, includes bounded read-only evidence for latency and OOM (including systemd/journal/coredump options), and avoids restart, sudo, sysctl writes, or invented PID/tool results. Fail if it jumps to tuning or treats a missing capture as evidence.

Readiness must apply to the production target through operator checks; local
workstation readiness does not establish production capabilities. Fail if the
agent asks the user to choose between the two entry skills or repeats initial
triage when handing off to supporting debug helpers.
