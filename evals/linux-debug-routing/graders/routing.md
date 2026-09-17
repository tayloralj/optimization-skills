---
type: llm
name: routing
---
Pass only if the response starts with a measurable symptom/window, routes through profiling readiness, selects offline capture because no agent is available, includes bounded read-only evidence for latency and OOM (including systemd/journal/coredump options), and avoids restart, sudo, sysctl writes, or invented PID/tool results. Fail if it jumps to tuning or treats a missing capture as evidence.
