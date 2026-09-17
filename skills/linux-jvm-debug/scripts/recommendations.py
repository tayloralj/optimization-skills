#!/usr/bin/env python3
"""Rank next actions from the structured analysis output."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


RULES = (("oom", 100, "Confirm native memory and cgroup limits with NMT and RSS deltas.", "java-native-memory"),
         ("crash", 100, "Preserve hs_err/coredump evidence and correlate the failing JVM build.", "java-offline-capture"),
         ("service-state", 90, "Check service lifecycle and journal timing before changing JVM flags.", "java-offline-capture"),
         ("gc", 80, "Correlate pause and allocation windows before tuning the collector.", "java-gc-tuning"),
         ("latency", 70, "Validate open-loop timestamps and completeness before comparing percentiles.", "java-latency-measurement"),
         ("vendor", 60, "Use the detected CPU vendor and verified PMU/tool readiness for a bounded profile.", "java-vtune-uprof"))


def recommend(data: dict) -> list[dict]:
    text = " ".join(str(x.get("text", "")) + " " + str(x.get("kind", "")) for x in data.get("findings", [])) + " " + str(data.get("symptom", ""))
    out = [{"priority": priority, "action": action, "skill": skill} for key, priority, action, skill in RULES if key in text.lower()]
    if not out:
        out.append({"priority": 10, "action": "Run profiling readiness, then choose one evidence path and establish a baseline.", "skill": "profiling-readiness"})
    return sorted(out, key=lambda x: -x["priority"])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("analysis", type=Path); p.add_argument("--json", action="store_true"); a = p.parse_args()
    result = {"schema_version": 1, "recommendations": recommend(json.loads(a.analysis.read_text()))}
    print(json.dumps(result, indent=2) if a.json else "\n".join(f"{r['priority']}: {r['skill']}: {r['action']}" for r in result["recommendations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
