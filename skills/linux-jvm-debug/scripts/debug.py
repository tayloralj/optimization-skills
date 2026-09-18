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
RECOMMEND = HERE / "linux-jvm-debug/scripts/recommendations.py"
GUARD = HERE / "linux-jvm-debug/scripts/target-guard.py"
PERF_CAPTURE = HERE / "java-linux-perf/scripts/java-perf-capture.sh"


def run(argv: list[str]) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=20)
    if proc.returncode:
        raise SystemExit(proc.stderr.strip() or f"failed: {' '.join(argv)}")
    return proc.stdout.strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symptom", required=True)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--analysis", type=Path, help="analysis.json to turn into ranked next actions")
    p.add_argument("--pid", type=int, help="real discovered Java PID to verify")
    p.add_argument("--user", help="expected owner for --pid")
    p.add_argument("--start-ticks", type=int, help="expected /proc starttime for --pid")
    p.add_argument("--run", action="store_true", help="run a bounded launch capture; command follows --")
    p.add_argument("--out", type=Path, help="private output directory for --run")
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--cpus", help="CPU list for --run, for example 0-7")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.run:
        command = args.command[1:] if args.command and args.command[0] == "--" else args.command
        if not args.out or not command:
            p.error("--run requires --out DIR and a command after --")
        capture = [str(PERF_CAPTURE), "--out", str(args.out), "--duration", str(args.duration)]
        if args.cpus:
            capture += ["--cpus", args.cpus]
        capture += ["--"] + command
        capture_output = subprocess.run(capture, text=True, check=False)
        if capture_output.returncode:
            return capture_output.returncode
        print(f"capture={args.out}")
        return 0
    if args.pid is not None:
        if not args.user or args.start_ticks is None:
            p.error("--pid requires --user and --start-ticks; attach is never inferred")
        result_guard = run([sys.executable, str(GUARD), "--pid", str(args.pid), "--user", args.user, "--start-ticks", str(args.start_ticks)])
    else:
        result_guard = None
    hints = run([sys.executable, str(HINTS), "--symptom", args.symptom, "--json"])
    readiness = run([str(READY), "--no-smoke-test"])
    result = {"schema_version": 1, "symptom": args.symptom, "hints": json.loads(hints), "readiness": readiness}
    if result_guard:
        result["target_verification"] = result_guard
    if args.bundle:
        result["service_evidence"] = json.loads(run([sys.executable, str(SERVICE), str(args.bundle), "--json"]))
    if args.analysis:
        result["recommendations"] = json.loads(run([sys.executable, str(RECOMMEND), str(args.analysis), "--json"]))["recommendations"]
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
        for recommendation in result.get("recommendations", []):
            print(f"- next ({recommendation['priority']}): {recommendation['skill']}: {recommendation['action']}")
            print(f"  Evidence: {recommendation['evidence']}\n  Uncertainty: {recommendation['uncertainty']}\n  Verify: {recommendation['verification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
