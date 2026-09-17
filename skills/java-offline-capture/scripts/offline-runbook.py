#!/usr/bin/env python3
"""Generate a copyable, read-only operator runbook for an offline capture."""
from __future__ import annotations

import argparse
import shlex


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--pid", type=int, required=True); p.add_argument("--unit"); p.add_argument("--duration", type=int, default=60); p.add_argument("--out", default="./jvm-capture"); a = p.parse_args()
    if a.pid <= 1 or a.pid == 12345 or not 10 <= a.duration <= 3600:
        p.error("use a discovered PID (12345 is a placeholder) and duration 10..3600")
    command = ["./collect.sh", "--pid", str(a.pid), "--duration", str(a.duration), "--out", a.out, "--yes"]
    if a.unit:
        command += ["--systemd-unit", a.unit, "--coredump"]
    print("# Run as the service user after reviewing the dry-run output")
    print(" ".join(shlex.quote(x) for x in command + ["--dry-run"]))
    print(" ".join(shlex.quote(x) for x in command))
    print("# Transfer the resulting bundle and verify its SHA256 before analysis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
