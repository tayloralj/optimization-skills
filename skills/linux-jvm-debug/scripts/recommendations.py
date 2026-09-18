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
    evidence = []
    for path, findings in (("/findings", data.get("findings", [])),
                           ("/service_evidence/findings", data.get("service_evidence", {}).get("findings", []))):
        for i, finding in enumerate(findings):
            evidence.append({'source': f'{path}/{i}', 'observation':
                             ' '.join(str(finding.get(k, '')) for k in ('kind', 'text', 'detail')).strip()})
    out = []
    for key, priority, action, skill in RULES:
        matches = [e for e in evidence if key in e['observation'].lower()]
        if matches or key in str(data.get('symptom', '')).lower():
            out.append({'priority': priority, 'action': action, 'skill': skill,
                        'evidence': matches, 'confidence': 'unverified',
                        'basis': 'reported_observation' if matches else 'symptom_only',
                        'uncertainty': 'A routing hint does not establish causality or exclude other causes.',
                        'verification': 'Capture a healthy baseline on the same host and workload; change one factor and repeat without profiler overhead.'})
    if not out:
        out.append({"priority": 10, "action": "Run profiling readiness, then choose one evidence path and establish a baseline.", "skill": "profiling-readiness", "evidence": [], "confidence": "unverified", "basis": "missing_evidence", "uncertainty": "No matching evidence was supplied.", "verification": "Collect a bounded baseline and verify capture completeness."})
    return sorted(out, key=lambda x: -x["priority"])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("analysis", type=Path); p.add_argument("--json", action="store_true"); a = p.parse_args()
    data = json.loads(a.analysis.read_text())
    recs = recommend(data)
    result = {"schema_version": 1, "confidence": "unverified", "recommendations": recs}
    print(json.dumps(result, indent=2) if a.json else "\n".join(
        f"{r['priority']}: {r['skill']}: {r['action']}\nEvidence: {r['evidence']}\nUncertainty: {r['uncertainty']}\nVerify: {r['verification']}"
        for r in result["recommendations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
