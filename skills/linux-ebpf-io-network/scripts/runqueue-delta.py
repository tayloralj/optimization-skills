#!/usr/bin/env python3
"""Measure per-thread schedstat deltas without attaching a profiler."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def start_time(path: Path) -> str | None:
    value = text(path / "stat")
    if value is None or ")" not in value:
        return None
    tail = value.rsplit(")", 1)[1].split()
    return tail[19] if len(tail) > 19 else None


def snapshot(proc: Path) -> dict[str, tuple[int, int, int]]:
    result = {}
    for task in proc.glob("task/[0-9]*"):
        if not task.is_dir():
            continue
        fields = (text(task / "schedstat") or "").split()
        if len(fields) < 3:
            continue
        try:
            result[task.name] = tuple(int(item) for item in fields[:3])
        except ValueError:
            continue
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--duration", type=float, default=1.0)
    args = parser.parse_args()
    if args.pid <= 0 or not 0.01 <= args.duration <= 600:
        parser.error("pid must be positive and duration must be 0.01..600 seconds")
    proc = Path(os.environ.get("PROC_ROOT", "/proc")) / str(args.pid)
    before_start = start_time(proc)
    before = snapshot(proc)
    if before_start is None or not before:
        parser.error(f"cannot read schedstat for PID {args.pid}")
    time.sleep(args.duration)
    after_start = start_time(proc)
    if after_start is None or after_start != before_start:
        print("target exited or PID was reused during measurement", file=os.sys.stderr)
        return 1
    after = snapshot(proc)
    rows = []
    for tid in sorted(set(before) & set(after), key=int):
        on_cpu = after[tid][0] - before[tid][0]
        run_queue = after[tid][1] - before[tid][1]
        slices = after[tid][2] - before[tid][2]
        if min(on_cpu, run_queue, slices) < 0:
            continue
        rows.append({"tid": int(tid), "on_cpu_ns": on_cpu,
                     "run_queue_ns": run_queue, "timeslices": slices})
    total = {key: sum(row[key] for row in rows)
             for key in ("on_cpu_ns", "run_queue_ns", "timeslices")}
    print(json.dumps({"schema_version": 1, "pid": args.pid,
                      "duration_seconds": args.duration,
                      "threads_before": len(before), "threads_after": len(after),
                      "threads_compared": len(rows), "totals": total,
                      "threads": rows}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
