#!/usr/bin/env python3
"""Fail-closed verification of a real Java PID before an attach operation."""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--pid", type=int, required=True); p.add_argument("--user", required=True); p.add_argument("--start-ticks", type=int, required=True); a = p.parse_args()
    if a.pid <= 1 or a.pid == 12345:
        p.error("PID must be a discovered target; 12345 is an example placeholder")
    proc = Path("/proc") / str(a.pid)
    if not proc.is_dir():
        p.error("target PID does not exist")
    try:
        owner = proc.stat().st_uid
        actual_start = int((proc / "stat").read_text().split(")", 1)[1].split()[19])
        exe = os.readlink(proc / "exe")
    except (OSError, ValueError, IndexError) as exc:
        p.error(f"cannot verify target identity: {exc}")
    import pwd
    actual_user = pwd.getpwuid(owner).pw_name
    if actual_user != a.user or actual_start != a.start_ticks or "java" not in Path(exe).name.lower():
        p.error(f"identity mismatch: user={actual_user} start_ticks={actual_start} exe={exe}")
    print(f"verified pid={a.pid} user={actual_user} start_ticks={actual_start} exe={exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
