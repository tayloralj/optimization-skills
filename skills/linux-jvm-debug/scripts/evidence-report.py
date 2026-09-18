#!/usr/bin/env python3
"""Merge offline, perf, vendor, and service evidence into one report."""
from __future__ import annotations

import argparse
import json
from recommendations import recommend
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path, help="directory containing analysis.json and optional vendor/perf reports")
    p.add_argument("--baseline", type=Path)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    analysis = load(a.root / "analysis.json") if (a.root / "analysis.json").is_file() else {}
    result = {"schema_version": 1, "analysis": analysis, "sources": []}
    for name, filename in (("perf", "perf-report.json"), ("vendor", "vendor-report.json")):
        path = a.root / filename
        if path.is_file():
            result[name] = load(path); result["sources"].append(filename)
    if a.baseline:
        base = load(a.baseline)
        result["baseline"] = {"findings": len(base.get("findings", [])), "next_skills": base.get("next_skills", []),
                              "comparison_status": "not_compared",
                              "reason": "Metric scope, units, workload and measurement windows must be verified before computing changes."}
    findings = analysis.get("findings", [])
    result["confidence"] = "unverified"
    result["recommendations"] = recommend(analysis)
    result["limitations"] = ['Imported findings and counters are not independently validated or time-correlated.']
    if a.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"confidence={result['confidence']} findings={len(findings)} sources={','.join(result['sources']) or 'analysis'}")
        for finding in findings:
            print(f"{finding.get('severity','info')}: {finding.get('text','')}")
        for rec in result['recommendations']:
            print(f"Next: {rec['action']}\nEvidence: {rec['evidence']}\nUncertainty: {rec['uncertainty']}\nVerify: {rec['verification']}")
    return 0 if analysis or result['sources'] else 3


if __name__ == "__main__":
    raise SystemExit(main())
