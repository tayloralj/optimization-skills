#!/usr/bin/env python3
"""Run interleaved fixed-work baseline/profiled comparisons.

Commands are tokenised with shlex and executed without a shell. Both commands
must print key=value fields including measured_operations, checksum, and
elapsed_ns. Results and raw output are retained for inspection.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-cmd", required=True, help="baseline command, quoted as one argument")
    parser.add_argument("--profiled-cmd", required=True, help="profiled command, quoted as one argument")
    parser.add_argument("--pairs", type=int, default=3, help="interleaved pairs (default: 3)")
    parser.add_argument("--timeout", type=float, default=120.0, help="per-command timeout in seconds")
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory for raw outputs and summary")
    return parser.parse_args()


def command(value: str, name: str) -> list[str]:
    try:
        parts = shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"{name} is not valid shell-like quoting: {exc}") from exc
    if not parts:
        raise ValueError(f"{name} is empty")
    return parts


def fields(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key and key.replace("_", "").isalnum():
            result[key] = value
    return result


def run(argv: list[str], path: Path, timeout: float) -> dict[str, object]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        path.with_suffix(".stdout").write_text(exc.stdout or "", encoding="utf-8")
        path.with_suffix(".stderr").write_text(exc.stderr or "", encoding="utf-8")
        raise RuntimeError(f"command timed out after {timeout:g}s: {argv[0]}") from exc
    path.with_suffix(".stdout").write_text(completed.stdout, encoding="utf-8")
    path.with_suffix(".stderr").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"command exited {completed.returncode}: {argv[0]}")
    data = fields(completed.stdout)
    missing = [key for key in ("measured_operations", "checksum", "elapsed_ns") if key not in data]
    if missing:
        raise RuntimeError(f"{argv[0]} output is missing: {', '.join(missing)}")
    try:
        measured = int(data["measured_operations"])
        checksum = int(data["checksum"])
        elapsed = int(data["elapsed_ns"])
    except ValueError as exc:
        raise RuntimeError(f"{argv[0]} emitted non-integer comparison fields") from exc
    if measured <= 0 or elapsed <= 0:
        raise RuntimeError(f"{argv[0]} emitted non-positive work or elapsed time")
    return {"measured_operations": measured, "checksum": checksum, "elapsed_ns": elapsed}


def main() -> int:
    args = parse_args()
    if not 1 <= args.pairs <= 20 or args.timeout <= 0:
        print("pairs must be 1..20 and timeout must be positive", file=sys.stderr)
        return 2
    try:
        baseline = command(args.baseline_cmd, "--baseline-cmd")
        profiled = command(args.profiled_cmd, "--profiled-cmd")
        args.output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    except (ValueError, FileExistsError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    rows: list[dict[str, object]] = []
    try:
        for pair in range(1, args.pairs + 1):
            base = run(baseline, args.output_dir / f"pair-{pair:02d}-baseline", args.timeout)
            prof = run(profiled, args.output_dir / f"pair-{pair:02d}-profiled", args.timeout)
            if base["measured_operations"] != prof["measured_operations"]:
                raise RuntimeError(f"pair {pair}: measured operation counts differ")
            if base["checksum"] != prof["checksum"]:
                raise RuntimeError(f"pair {pair}: checksums differ")
            base_ns = int(base["elapsed_ns"])
            prof_ns = int(prof["elapsed_ns"])
            rows.append({"pair": pair, "baseline": base, "profiled": prof,
                         "overhead_percent": (prof_ns / base_ns - 1.0) * 100.0})
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    summary = {"pairs": rows, "pair_count": len(rows),
               "mean_overhead_percent": sum(float(row["overhead_percent"]) for row in rows) / len(rows)}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
