---
type: llm
weight: 2
---

Pass if the response builds a collector kit and gives ops a runbook that runs `collect.sh` as `router` with an
unattended start: a `--trigger` condition (for example process CPU or a GC pause threshold) bounded by `--max-wait`,
started detached (for example `nohup ... &`) so it survives logout, after `--check` and/or `--dry-run`. It should use
the existing continuous recording (`--jfr dump`) or otherwise explain how the minutes before the trigger are kept,
and say the threshold should come from a baseline or normal-load capture. Retrieval must include the sha256 check and
`analyze-bundle.py` (optionally `compare-bundles.py` against a baseline).
Fail if it proposes a hand-written loop that records continuously all night, installing an agent on the VM, running
perf/eBPF as root first, or restarting the JVM when the needed launch flags are already present.
