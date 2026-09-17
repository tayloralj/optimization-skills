#!/usr/bin/env python3
"""Run a bounded recovery command repeatedly and validate DONE completeness."""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--done-regex", default=r"DONE.*delivered=(?P<delivered>\d+)/(?P<expected>\d+)")
    p.add_argument("--", dest="separator", action="store_true")
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    if a.reps < 1 or a.reps > 50 or a.timeout < 1 or a.timeout > 3600 or not a.command:
        p.error("reps, timeout, or command out of bounds")
    if a.command[0] == "--":
        a.command = a.command[1:]
    if a.out.exists():
        p.error(f"refusing existing output: {a.out}")
    a.out.mkdir(mode=0o700, parents=True)
    pattern = re.compile(a.done_regex)
    rows = []
    for rep in range(1, a.reps + 1):
        start = time.monotonic()
        try:
            proc = subprocess.run(a.command, capture_output=True, text=True, timeout=a.timeout, check=False)
            status = proc.returncode
            output = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            status = 124
            output = (exc.stdout or "") + (exc.stderr or "")
        elapsed_ms = round((time.monotonic() - start) * 1000, 3)
        match = next((m for m in (pattern.search(line) for line in output.splitlines()) if m), None)
        delivered = int(match.group("delivered")) if match and "delivered" in match.groupdict() else None
        expected = int(match.group("expected")) if match and "expected" in match.groupdict() else None
        complete = bool(match and delivered is not None and expected is not None and delivered == expected and status == 0)
        (a.out / f"run-{rep:03d}.log").write_text(output)
        rows.append({"rep": rep, "exit_status": status, "elapsed_ms": elapsed_ms, "delivered": delivered, "expected": expected, "complete": complete})
    (a.out / "results.json").write_text(json.dumps({"schema_version": 1, "command": a.command, "runs": rows}, indent=2) + "\n")
    with (a.out / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps(rows, indent=2))
    return 0 if all(row["complete"] for row in rows) else 5


if __name__ == "__main__":
    raise SystemExit(main())
