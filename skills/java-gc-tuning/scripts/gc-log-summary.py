#!/usr/bin/env python3
"""Summarise HotSpot unified GC and safepoint logs (JDK 17, 21, 25).

Read-only: parses files named on the command line and prints a report. Expects
logs produced with, for example:
  -Xlog:gc*,safepoint:file=gc.log:time,uptime,level,tags
Works with G1, Parallel, Serial, Shenandoah, and ZGC (generational and legacy).
The `uptime` decorator is needed for pause-fraction and allocation-rate output.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict

DECORATOR_RE = re.compile(r"^((?:\[[^\]]*\])*)\s*")
UPTIME_RE = re.compile(r"\[(\d+(?:\.\d+)?)s\]")
PAUSE_RE = re.compile(
    r"GC\((?P<id>\d+)\)\s+(?:(?P<gen>[YOyo]):\s+)?(?P<name>Pause\b.*?)\s+"
    r"(?:(?P<before>\d+[BKMGT]?)->(?P<after>\d+[BKMGT]?)\((?P<capacity>\d+[BKMGT]?)\)\s+)?"
    r"(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|s)\s*$"
)
COLLECTION_RE = re.compile(
    r"GC\(\d+\)\s+(?P<kind>(?:Major|Minor) Collection|Concurrent (?:Mark|Undo) Cycle|Concurrent Mark Abort)"
    r"(?:\s+\((?P<cause>[^)]*)\))?.*?(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|s)\s*$"
)
SAFEPOINT_RE = re.compile(r'Safepoint "(?P<op>[^"]+)",\s*(?P<fields>.*)$')
NS_FIELD_RE = re.compile(r"(?P<key>[A-Za-z][A-Za-z ]*?):\s*(?P<value>\d+)\s*ns")
ALARMS = {
    "full_gc": re.compile(r"Pause Full\b"),
    "evacuation_failure": re.compile(r"To-space exhausted|Evacuation Failure", re.I),
    "humongous_allocation": re.compile(r"G1 Humongous Allocation"),
    "allocation_stall": re.compile(r"(?:Allocation|Relocation) Stall \("),
    "degenerated_gc": re.compile(r"Degenerated GC"),
    "system_gc": re.compile(r"System\.gc\(\)"),
    "metadata_threshold": re.compile(r"Metadata GC Threshold|Metadata GC Clear Soft References"),
    "gclocker": re.compile(r"GCLocker Initiated GC"),
}
UNIT = {"B": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}


def to_bytes(text: str | None) -> int | None:
    if not text:
        return None
    suffix = text[-1]
    return int(text[:-1]) * UNIT[suffix] if suffix in UNIT else int(text)


def to_ms(value: str, unit: str) -> float:
    return float(value) * (1000.0 if unit == "s" else 1.0)


def percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile of an ascending list."""
    if not sorted_values:
        return float("nan")
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[rank - 1]


def distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "sum": sum(ordered),
        "p50": percentile(ordered, 50),
        "p90": percentile(ordered, 90),
        "p99": percentile(ordered, 99),
        "p99_9": percentile(ordered, 99.9),
        "max": ordered[-1] if ordered else float("nan"),
    }


def parse(paths: list[str], from_uptime: float | None = None, to_uptime: float | None = None) -> dict:
    pauses: dict[tuple, dict] = {}
    collections: Counter = Counter()
    safepoints: list[dict] = []
    alarms: Counter = Counter()
    alarm_seen: set[tuple] = set()
    first_uptime = last_uptime = None
    collectors: set[str] = set()

    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, 1):
                line = raw.rstrip("\n")
                match = DECORATOR_RE.match(line)
                decorators, message = match.group(1), line[match.end():]
                uptime_match = UPTIME_RE.search(decorators)
                uptime = float(uptime_match.group(1)) if uptime_match else None
                if message.startswith("Using "):
                    collectors.add(message[len("Using "):].strip())
                if uptime is not None and ((from_uptime is not None and uptime < from_uptime)
                                           or (to_uptime is not None and uptime > to_uptime)):
                    continue
                if uptime is not None:
                    first_uptime = uptime if first_uptime is None else min(first_uptime, uptime)
                    last_uptime = uptime if last_uptime is None else max(last_uptime, uptime)

                pause = PAUSE_RE.search(message)
                if pause:
                    key = (path, pause["id"], pause["gen"], pause["name"])
                    pauses[key] = {
                        "gc_id": int(pause["id"]),
                        "generation": pause["gen"],
                        "name": pause["name"],
                        "ms": to_ms(pause["value"], pause["unit"]),
                        "before": to_bytes(pause["before"]),
                        "after": to_bytes(pause["after"]),
                        "capacity": to_bytes(pause["capacity"]),
                        "uptime_s": uptime,
                        "where": f"{path}:{line_no}",
                    }
                collection = COLLECTION_RE.search(message)
                if collection:
                    label = collection["kind"] + (f" ({collection['cause']})" if collection["cause"] else "")
                    collections[label] += 1
                safepoint = SAFEPOINT_RE.search(message)
                if safepoint:
                    fields = {m["key"].strip().lower(): int(m["value"]) for m in NS_FIELD_RE.finditer(safepoint["fields"])}
                    safepoints.append({"op": safepoint["op"], "uptime_s": uptime, **fields})
                for alarm, pattern in ALARMS.items():
                    if pattern.search(message):
                        gc_id = re.search(r"GC\((\d+)\)", message)
                        dedupe = (path, alarm, gc_id.group(1) if gc_id else line_no)
                        if dedupe not in alarm_seen:
                            alarm_seen.add(dedupe)
                            alarms[alarm] += 1
    return {
        "pauses": sorted(pauses.values(), key=lambda p: (p["uptime_s"] or 0, p["gc_id"])),
        "collections": collections,
        "safepoints": safepoints,
        "alarms": alarms,
        "first_uptime": first_uptime,
        "last_uptime": last_uptime,
        "collectors": sorted(collectors),
    }


def summarise(data: dict, top: int) -> dict:
    pauses = data["pauses"]
    by_name: dict[str, list[float]] = defaultdict(list)
    for pause in pauses:
        label = (f"{pause['generation']}: " if pause["generation"] else "") + pause["name"]
        by_name[label].append(pause["ms"])
    elapsed_s = None
    if data["first_uptime"] is not None and data["last_uptime"] is not None:
        elapsed_s = data["last_uptime"] - data["first_uptime"]
    total_pause_ms = sum(p["ms"] for p in pauses)

    allocation = None
    sized = [p for p in pauses if p["before"] is not None and p["uptime_s"] is not None and not p["generation"]]
    if len(sized) >= 2 and sized[-1]["uptime_s"] > sized[0]["uptime_s"]:
        allocated = sum(max(0, cur["before"] - prev["after"]) for prev, cur in zip(sized, sized[1:]))
        allocation = allocated / (sized[-1]["uptime_s"] - sized[0]["uptime_s"]) / (1 << 20)

    safepoint_summary = None
    if data["safepoints"]:
        reaching = [s["reaching safepoint"] / 1e6 for s in data["safepoints"] if "reaching safepoint" in s]
        totals = [s["total"] / 1e6 for s in data["safepoints"] if "total" in s]
        by_op: dict[str, list[float]] = defaultdict(list)
        for s in data["safepoints"]:
            if "total" in s:
                by_op[s["op"]].append(s["total"] / 1e6)
        safepoint_summary = {
            "time_to_safepoint_ms": distribution(reaching),
            "total_ms": distribution(totals),
            "by_operation_ms": {op: distribution(v) for op, v in sorted(by_op.items(), key=lambda kv: -sum(kv[1]))},
            "worst_ttsp": sorted(
                ({"op": s["op"], "uptime_s": s["uptime_s"], "ms": s["reaching safepoint"] / 1e6}
                 for s in data["safepoints"] if "reaching safepoint" in s),
                key=lambda s: -s["ms"])[:top],
        }

    return {
        "collectors": data["collectors"],
        "elapsed_s": elapsed_s,
        "pause_count": len(pauses),
        "pause_total_ms": total_pause_ms,
        "pause_fraction": (total_pause_ms / 1000.0 / elapsed_s) if elapsed_s else None,
        "pause_ms": distribution([p["ms"] for p in pauses]) if pauses else None,
        "pauses_by_type_ms": {k: distribution(v) for k, v in sorted(by_name.items(), key=lambda kv: -sum(kv[1]))},
        "worst_pauses": [
            {k: p[k] for k in ("gc_id", "generation", "name", "ms", "uptime_s", "where")}
            for p in sorted(pauses, key=lambda p: -p["ms"])[:top]
        ],
        "collections": dict(data["collections"].most_common()),
        "approx_allocation_mib_per_s": allocation,
        "safepoints": safepoint_summary,
        "alarms": dict(data["alarms"]),
    }


def fmt_dist(d: dict | None) -> str:
    if not d or not d["count"]:
        return "n=0"
    return (f"n={d['count']} sum={d['sum']:.3f} p50={d['p50']:.3f} p90={d['p90']:.3f} "
            f"p99={d['p99']:.3f} p99.9={d['p99_9']:.3f} max={d['max']:.3f}")


def print_text(s: dict) -> None:
    print(f"collectors: {', '.join(s['collectors']) or 'unknown (no gc,init lines)'}")
    if s["elapsed_s"] is not None:
        print(f"log_span_s: {s['elapsed_s']:.3f}")
    if any(v is not None for v in s.get("window_uptime_s", [])):
        print(f"window_uptime_s: from={s['window_uptime_s'][0]} to={s['window_uptime_s'][1]}")
    print(f"pauses_ms: {fmt_dist(s['pause_ms'])}" + ("  (no pauses in this window)" if not s["pause_count"] else ""))
    if s["pause_fraction"] is not None:
        print(f"pause_fraction: {s['pause_fraction'] * 100:.3f}% of wall time")
    if s["approx_allocation_mib_per_s"] is not None:
        print(f"approx_allocation_rate_mib_s: {s['approx_allocation_mib_per_s']:.1f} (from heap before/after pauses)")
    print("pauses_by_type_ms:")
    for name, dist in s["pauses_by_type_ms"].items():
        print(f"  {name}: {fmt_dist(dist)}")
    print("worst_pauses:")
    for p in s["worst_pauses"]:
        gen = f"{p['generation']}: " if p["generation"] else ""
        print(f"  {p['ms']:.3f} ms GC({p['gc_id']}) {gen}{p['name']} uptime={p['uptime_s']} {p['where']}")
    if s["collections"]:
        print("collections:")
        for name, count in s["collections"].items():
            print(f"  {name}: {count}")
    sp = s["safepoints"]
    if sp:
        print(f"time_to_safepoint_ms: {fmt_dist(sp['time_to_safepoint_ms'])}")
        print(f"safepoint_total_ms: {fmt_dist(sp['total_ms'])}")
        print("safepoints_by_operation_ms:")
        for op, dist in sp["by_operation_ms"].items():
            print(f"  {op}: {fmt_dist(dist)}")
        print("worst_time_to_safepoint:")
        for w in sp["worst_ttsp"]:
            print(f"  {w['ms']:.3f} ms {w['op']} uptime={w['uptime_s']}")
    else:
        print("safepoints: none recorded (if unexpected, check that 'safepoint' is in the -Xlog tags)")
    print("alarms:" + ("" if s["alarms"] else " none"))
    for name, count in sorted(s["alarms"].items()):
        print(f"  {name}: {count}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+", help="unified logging files (pass rotated files too)")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--top", type=int, default=5, help="worst entries to list (default 5)")
    parser.add_argument("--from-uptime", type=float, metavar="S", help="ignore events before this JVM uptime (exclude warmup)")
    parser.add_argument("--to-uptime", type=float, metavar="S", help="ignore events after this JVM uptime")
    args = parser.parse_args(argv)
    try:
        summary = summarise(parse(args.logs, args.from_uptime, args.to_uptime), args.top)
    except OSError as exc:
        print(f"cannot read log: {exc}", file=sys.stderr)
        return 3
    if summary["pause_count"] == 0 and not summary["safepoints"] and not summary["collectors"]:
        print("no GC pauses, safepoints, or collector lines recognised; check -Xlog tags and decorators", file=sys.stderr)
        return 4
    summary["window_uptime_s"] = [args.from_uptime, args.to_uptime]
    if args.json:
        json.dump(summary, sys.stdout, indent=2, default=lambda v: None)
        print()
    else:
        print_text(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
