---
type: llm
weight: 2
---

The response should propose the offline workflow: build a collector kit locally, give ops a runbook that verifies the
kit's sha256, runs `collect.sh` as the `payments` user (for example with `sudo -u payments`), does a `--dry-run` first,
and captures a window covering the 18:00 spike (for example several minutes with JFR); then copy the bundle back,
verify its sha256, and run `analyze-bundle.py` locally before interpreting the findings.
It should mention at least one data-handling point (secrets scrubbed from JFR, bundle is confidential, delete after
retrieval) and at least one prerequisite or gap (GC logging or continuous JFR at launch for incident capture, JDK tools
such as jcmd being present).
If it gives commands, the archive must go to `analyze-bundle.py` with a new
output directory and the expected SHA256 when available. A separate
`service-evidence.py` command must use the extracted bundle directory printed
by the analyser, never the `.tar.gz` archive. Fail an answer whose suggested
command would silently report no service evidence because it reads the wrong
input type.
Fail if it asks the user to install an agent on production, to give the agent SSH access, or to run perf/eBPF as root
as the first step.
