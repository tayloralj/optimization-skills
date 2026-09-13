#!/usr/bin/env python3
"""Compare two native-memory snapshots (from native-memory-snapshot.sh).

Read-only. Reports RSS change against NMT committed change per category so
growth outside NMT (glibc arenas, JNI/native libraries, mapped files) stands
out. Accepts snapshot directories or two NMT summary files.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CATEGORY_RE = re.compile(r"^-\s+(?P<name>.+?)\s+\(reserved=(?P<reserved>\d+)KB, committed=(?P<committed>\d+)KB\)")
TOTAL_RE = re.compile(r"^Total: reserved=(?P<reserved>\d+)KB, committed=(?P<committed>\d+)KB")
STATUS_RE = re.compile(r"^(?P<key>\w+):\s+(?P<value>\d+)(?:\s+kB)?")


def load(path: Path) -> dict:
    nmt_file = path / "nmt-summary.txt" if path.is_dir() else path
    status_file = path / "proc-status.txt" if path.is_dir() else None
    categories: dict[str, dict[str, int]] = {}
    total = None
    enabled = False
    if nmt_file.is_file():
        for line in nmt_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if m := TOTAL_RE.match(line):
                total = {"reserved": int(m["reserved"]), "committed": int(m["committed"])}
                enabled = True
            elif m := CATEGORY_RE.match(line):
                categories[m["name"]] = {"reserved": int(m["reserved"]), "committed": int(m["committed"])}
    status: dict[str, int] = {}
    if status_file and status_file.is_file():
        for line in status_file.read_text(encoding="utf-8").splitlines():
            if m := STATUS_RE.match(line):
                status[m["key"]] = int(m["value"])
    return {"nmt_enabled": enabled, "total": total, "categories": categories, "status": status}


def compare(before: dict, after: dict) -> dict:
    names = sorted(set(before["categories"]) | set(after["categories"]))
    rows = []
    for name in names:
        b = before["categories"].get(name, {"committed": 0, "reserved": 0})
        a = after["categories"].get(name, {"committed": 0, "reserved": 0})
        rows.append({"category": name, "before_kb": b["committed"], "after_kb": a["committed"],
                     "delta_kb": a["committed"] - b["committed"]})
    rows.sort(key=lambda r: -abs(r["delta_kb"]))
    result = {"categories": rows}
    if before["total"] and after["total"]:
        result["nmt_committed_delta_kb"] = after["total"]["committed"] - before["total"]["committed"]
    for key in ("VmRSS", "RssAnon", "RssFile", "RssShmem", "VmSwap", "Threads"):
        if key in before["status"] and key in after["status"]:
            result[f"{key}_delta"] = after["status"][key] - before["status"][key]
    if "nmt_committed_delta_kb" in result and "RssAnon_delta" in result:
        result["anon_rss_minus_nmt_delta_kb"] = result["RssAnon_delta"] - result["nmt_committed_delta_kb"]
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--min-kb", type=int, default=64, help="hide category deltas smaller than this")
    parser.add_argument("--gap-kb", type=int, default=65536,
                        help="flag anon RSS growth beyond NMT growth above this many kB (default 64 MiB)")
    args = parser.parse_args(argv)
    before, after = load(args.before), load(args.after)
    if not (before["nmt_enabled"] or before["status"]) or not (after["nmt_enabled"] or after["status"]):
        print("no NMT summary or proc status found in one of the inputs", file=sys.stderr)
        return 4
    result = compare(before, after)
    result["nmt_enabled"] = before["nmt_enabled"] and after["nmt_enabled"]
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0
    if not result["nmt_enabled"]:
        print("NMT disabled in at least one snapshot: only RSS deltas are available")
    for key in ("VmRSS_delta", "RssAnon_delta", "RssFile_delta", "RssShmem_delta", "VmSwap_delta", "Threads_delta"):
        if key in result:
            unit = "" if key == "Threads_delta" else " kB"
            print(f"{key}: {result[key]:+d}{unit}")
    if "nmt_committed_delta_kb" in result:
        print(f"nmt_committed_delta: {result['nmt_committed_delta_kb']:+d} kB")
    if "anon_rss_minus_nmt_delta_kb" in result:
        gap = result["anon_rss_minus_nmt_delta_kb"]
        print(f"anon_rss_growth_not_explained_by_nmt: {gap:+d} kB"
              + ("  <- candidate non-NMT growth (malloc arenas, native libraries)" if gap > args.gap_kb else ""))
        print("  note: committed-but-untouched heap/stack pages skew this; compare steady-state snapshots,"
              " ideally with -XX:+AlwaysPreTouch, and repeat before concluding")
    print("nmt_committed_by_category (largest change first):")
    for row in result["categories"]:
        if abs(row["delta_kb"]) >= args.min_kb:
            print(f"  {row['category']}: {row['before_kb']} -> {row['after_kb']} kB ({row['delta_kb']:+d})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
