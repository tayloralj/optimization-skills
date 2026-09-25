---
type: llm
name: routing
---
Pass only if the response starts with a measurable symptom/window, routes through profiling readiness, selects offline capture because no agent is available, includes bounded read-only evidence for latency and OOM (including systemd/journal/coredump options), and avoids restart, sudo, sysctl writes, or invented PID/tool results. Fail if it jumps to tuning or treats a missing capture as evidence.

Readiness must apply to the production target through operator checks; local
workstation readiness does not establish production capabilities. Fail if the
agent asks the user to choose between the two entry skills or repeats initial
triage when handing off to supporting debug helpers.

If the response gives analysis commands, check that their inputs match the
helper's interface. `analyze-bundle.py` accepts a verified `.tar.gz` and a new
output directory. `service-evidence.py` accepts an extracted bundle directory
(for example the `bundle_dir` printed by `analyze-bundle.py`), not the archive.
Fail an answer that passes a `.tar.gz` to `service-evidence.py`, treats a
missing file as a clean service result, or interprets an unverified bundle.
