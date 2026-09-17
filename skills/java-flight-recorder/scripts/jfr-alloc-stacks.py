#!/usr/bin/env python3
"""Allocation pressure by thread and call stack from a JFR recording.

Read-only. `jfr view allocation-by-site` names only the allocating method; this
groups jdk.ObjectAllocationSample weight by thread and the top N frames, so a
per-message allocation on the hot thread can be told apart from start-up or
background work that allocates in the same method.

  jfr-alloc-stacks.py run.jfr [--depth 5] [--thread REGEX] [--top 15] [--json]
  jfr-alloc-stacks.py events.json      # output of: jfr print --json --events jdk.ObjectAllocationSample --stack-depth N

Weights are sampled estimates (JDK 16+ event); compare sites within one
recording, and do not read them as exact byte counts. Exit codes: 0 report
printed, 2 bad arguments or unreadable input, 3 no allocation samples found.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict

EVENT = "jdk.ObjectAllocationSample"


def load_events(path: str, depth: int, jfr_tool: str, timeout: int) -> list:
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    else:
        tool = shutil.which(jfr_tool) or jfr_tool
        cmd = [tool, "print", "--json", "--events", EVENT, "--stack-depth", str(depth), path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise SystemExit(f"jfr tool not found: {jfr_tool} (use the JDK's bin/jfr, at least as new as the recording JVM)")
        except subprocess.TimeoutExpired:
            raise SystemExit(f"jfr print timed out after {timeout}s")
        if proc.returncode != 0:
            raise SystemExit(f"jfr print failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
        data = json.loads(proc.stdout)
    try:
        return [e for e in data["recording"]["events"] if e.get("type") == EVENT]
    except (KeyError, TypeError):
        raise SystemExit(f"{path}: not jfr print --json output")


def frame_name(frame: dict) -> str:
    method = frame.get("method") or {}
    owner = ((method.get("type") or {}).get("name") or "?").replace("/", ".")
    return f"{owner.rsplit('.', 1)[-1]}.{method.get('name', '?')}"


def aggregate(events: list, depth: int, thread_re: re.Pattern | None) -> tuple[dict, float]:
    totals: dict = defaultdict(lambda: {"weight": 0.0, "samples": 0, "classes": defaultdict(float)})
    grand = 0.0
    for event in events:
        values = event.get("values") or {}
        thread = (values.get("eventThread") or {}).get("javaName") or "?"
        if thread_re and not thread_re.search(thread):
            continue
        weight = float(values.get("weight") or 0)
        frames = ((values.get("stackTrace") or {}).get("frames") or [])[:depth]
        stack = tuple(frame_name(f) for f in frames) or ("<no stack>",)
        cls = ((values.get("objectClass") or {}).get("name") or "?").replace("/", ".")
        entry = totals[(thread, stack)]
        entry["weight"] += weight
        entry["samples"] += 1
        entry["classes"][cls] += weight
        grand += weight
    return totals, grand


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", help=".jfr file, or .json from jfr print --json")
    parser.add_argument("--depth", type=int, default=5, help="frames per stack key (default 5)")
    parser.add_argument("--thread", help="only threads whose Java name matches this regex")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--jfr", default="jfr", help="jfr tool to use (default: jfr on PATH)")
    parser.add_argument("--timeout", type=int, default=120, help="seconds allowed for jfr print")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.depth <= 64:
        parser.error("--depth must be between 1 and 64")
    if args.top < 1:
        parser.error("--top must be positive")
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        thread_re = re.compile(args.thread) if args.thread else None
    except re.error as exc:
        parser.error(f"invalid --thread regex: {exc}")
    try:
        events = load_events(args.recording, args.depth, args.jfr, args.timeout)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {args.recording}: {exc}", file=sys.stderr)
        return 2
    totals, grand = aggregate(events, args.depth, thread_re)
    if not totals or grand <= 0:
        print(f"no {EVENT} samples" + (f" for threads matching {args.thread!r}" if args.thread else "")
              + "; was the event enabled (settings=profile)?", file=sys.stderr)
        return 3
    ranked = sorted(totals.items(), key=lambda kv: kv[1]["weight"], reverse=True)[:args.top]
    rows = []
    for (thread, stack), entry in ranked:
        top_class = max(entry["classes"].items(), key=lambda kv: kv[1])[0]
        rows.append({"thread": thread, "stack": list(stack), "weight_bytes": entry["weight"],
                     "share": entry["weight"] / grand, "samples": entry["samples"], "top_class": top_class})
    if args.json:
        json.dump({"events": len(events), "total_weight_bytes": grand, "rows": rows}, sys.stdout, indent=2)
        print()
        return 0
    print(f"{EVENT}: {len(events)} samples, estimated {grand / 1e6:.1f} MB"
          + (f" (threads ~ {args.thread})" if args.thread else ""))
    for row in rows:
        print(f"{row['share'] * 100:5.1f}% {row['weight_bytes'] / 1e6:8.1f} MB  n={row['samples']:<4} "
              f"[{row['thread']}] {row['top_class']}")
        print("        " + " <- ".join(row["stack"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
