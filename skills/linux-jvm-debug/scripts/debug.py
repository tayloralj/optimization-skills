#!/usr/bin/env python3
"""One-command Linux JVM triage plan and optional offline evidence summary."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parents[2]
HINTS = HERE / "linux-jvm-debug/scripts/debug-hints.py"
READY = HERE / "profiling-readiness/scripts/check-profiling-readiness.sh"
SERVICE = HERE / "java-offline-capture/scripts/service-evidence.py"


def run(argv: list[str]) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=20)
    if proc.returncode:
        raise SystemExit(proc.stderr.strip() or f"failed: {' '.join(argv)}")
    return proc.stdout.strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symptom", required=True)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    hints = run([sys.executable, str(HINTS), "--symptom", args.symptom, "--json"])
    readiness = run([str(READY), "--no-smoke-test"])
    result = {"schema_version": 1, "symptom": args.symptom, "hints": json.loads(hints), "readiness": readiness}
    if args.bundle:
        result["service_evidence"] = json.loads(run([sys.executable, str(SERVICE), str(args.bundle), "--json"]))
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"Symptom: {args.symptom}")
        for item in result["hints"]["hints"]:
            print(f"- {item['skill']}: {item['reason']}")
        print("Readiness: " + next((line for line in readiness.splitlines() if line.startswith("status=")), readiness))
        if args.bundle:
            for finding in result["service_evidence"]["findings"]:
                print(f"- service {finding['severity']}: {finding['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
