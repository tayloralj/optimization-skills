#!/usr/bin/env python3
"""Coordinated-omission-aware latency report from per-operation timestamps.

Read-only. Input CSV (header optional), nanoseconds on one monotonic clock:
  intended_start_ns,actual_start_ns,end_ns     -> service time, queue delay, response time
  intended_start_ns,actual_start_ns,end_ns,group -> as above, plus per-group percentiles
                                               (needs this header line)
  latency_ns                                   -> single column; no CO analysis possible
Compare two runs with --baseline. Stability is shown by splitting the run into
equal-count blocks and reporting the spread of each block's percentile.

--episodes treats rows as recovery episodes (for example gap repairs):
intended = when the fault became observable, actual = when it was detected,
end = when recovery completed. Rate checks are skipped because episodes do not
follow a fixed schedule. --expected N fails the report (exit 5) when fewer than
N operations completed: percentiles of the survivors are not a latency result.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys

PCTS = (50.0, 90.0, 99.0, 99.9, 99.99)


def percentile(ordered: list[int], pct: float) -> float:
    if not ordered:
        return float("nan")
    return ordered[max(1, math.ceil(pct / 100.0 * len(ordered))) - 1]


def load(path: str) -> dict:
    intended, starts, ends, groups, single = [], [], [], [], []
    grouped = False
    with open(path, newline="", encoding="utf-8") as handle:
        for row_no, row in enumerate(csv.reader(handle), 1):
            if not row or row[0].strip().startswith("#"):
                continue
            header = ["intended_start_ns", "actual_start_ns", "end_ns"]
            if row_no == 1 and row in (["latency_ns"], header, header + ["group"]):
                grouped = row == header + ["group"]
                continue
            group = None
            if len(row) == 4:
                if not grouped:
                    raise SystemExit(f"{path}:{row_no}: 4-column rows need the header "
                                     "intended_start_ns,actual_start_ns,end_ns,group")
                group = row[3].strip()
                if not group:
                    raise SystemExit(f"{path}:{row_no}: empty group label")
                row = row[:3]
            try:
                values = [int(cell) for cell in row]
            except ValueError:
                raise SystemExit(f"{path}:{row_no}: non-numeric row")
            if len(values) == 3:
                if not values[0] <= values[1] <= values[2]:
                    raise SystemExit(f"{path}:{row_no}: require intended <= actual start <= end")
                intended.append(values[0]); starts.append(values[1]); ends.append(values[2])
                groups.append(group)
            elif len(values) == 1:
                if values[0] < 0:
                    raise SystemExit(f"{path}:{row_no}: latency must be non-negative")
                single.append(values[0])
            else:
                raise SystemExit(f"{path}:{row_no}: expected 1, 3, or 4 columns")
    if intended and single:
        raise SystemExit(f"{path}: mixes 1- and 3-column rows")
    if any(g is not None for g in groups) and any(g is None for g in groups):
        raise SystemExit(f"{path}: group label missing on some rows")
    if intended:
        order = sorted(range(len(intended)), key=intended.__getitem__)
        intended = [intended[i] for i in order]; starts = [starts[i] for i in order]; ends = [ends[i] for i in order]
        groups = [groups[i] for i in order]
        return {
            "kind": "timestamps",
            "response": [e - i for i, e in zip(intended, ends)],
            "service": [e - s for s, e in zip(starts, ends)],
            "queue": [s - i for i, s in zip(intended, starts)],
            "intended": intended,
            "ends": ends,
            "groups": groups if groups and groups[0] is not None else None,
        }
    return {"kind": "latency", "response": single}


def dist(values: list[int]) -> dict:
    ordered = sorted(values)
    out = {"count": len(ordered)}
    for p in PCTS:
        out[f"p{p:g}"] = percentile(ordered, p)
    out["max"] = ordered[-1] if ordered else float("nan")
    out["mean"] = sum(ordered) / len(ordered) if ordered else float("nan")
    return out


def blocks(values: list[int], pct: float, n_blocks: int) -> dict | None:
    size = len(values) // n_blocks
    if size < 100:
        return None
    per_block = [percentile(sorted(values[i * size:(i + 1) * size]), pct) for i in range(n_blocks)]
    return {"pct": pct, "blocks": n_blocks, "min": min(per_block), "median": sorted(per_block)[n_blocks // 2],
            "max": max(per_block), "values": per_block}


def group_sort_key(label: str):
    try:
        return (0, float(label), label)
    except ValueError:
        return (1, 0.0, label)


def analyse(data: dict, n_blocks: int, episodes: bool = False) -> dict:
    result = {"kind": data["kind"], "episodes": episodes, "response_ns": dist(data["response"])}
    if data["kind"] == "timestamps":
        result["service_ns"] = dist(data["service"])
        result["queue_delay_ns"] = dist(data["queue"])
        if data.get("groups"):
            by_group: dict[str, list[int]] = {}
            for label, value in zip(data["groups"], data["response"]):
                by_group.setdefault(label, []).append(value)
            result["groups"] = {label: dist(by_group[label]) for label in sorted(by_group, key=group_sort_key)}
        span_ns = data["intended"][-1] - data["intended"][0]
        if span_ns > 0 and not episodes:
            result["intended_rate_per_s"] = (len(data["intended"]) - 1) / (span_ns / 1e9)
            result["achieved_rate_per_s"] = (len(data["ends"]) - 1) / max(1e-9, (max(data["ends"]) - min(data["ends"])) / 1e9)
        negative = sum(1 for q in data["queue"] if q < 0)
        result["negative_queue_delay"] = negative
        ratios = {}
        for key in ("p99", "p99.9", "p99.99"):
            svc, resp = result["service_ns"][key], result["response_ns"][key]
            ratios[key] = resp / svc if svc else float("nan")
        result["co_ratios"] = ratios
        result["co_ratio_p99"] = ratios["p99"]
    # Blocks follow arrival order (timestamps) or file order (single column).
    stable = blocks(data["response"], 99.0, n_blocks)
    if stable:
        result["p99_block_spread_ns"] = stable
    return result


def fmt(ns: float) -> str:
    if isinstance(ns, float) and math.isnan(ns):
        return "nan"
    if ns >= 1e9:
        return f"{ns / 1e9:.3f}s"
    if ns >= 1e6:
        return f"{ns / 1e6:.3f}ms"
    if ns >= 1e3:
        return f"{ns / 1e3:.3f}us"
    return f"{ns:.0f}ns"


def line(name: str, d: dict) -> str:
    parts = [f"n={d['count']}"] + [f"{k}={fmt(d[k])}" for k in [f"p{p:g}" for p in PCTS] + ["max"]]
    return f"{name}: " + " ".join(parts)


def print_text(r: dict, baseline: dict | None) -> None:
    if "expected" in r and r["completed"] < r["expected"]:
        print(f"INVALID: only {r['completed']} of {r['expected']} operations completed; "
              "percentiles below describe the survivors, not the workload")
    if r.get("episodes"):
        print("episode mode: response = end - fault observable (intended), service = end - detection (actual), "
              "queue = detection delay")
    print(line("response_time", r["response_ns"]))
    if r["indicative_percentiles"]:
        print("note: fewer than 100 tail samples; indicative only: " + ", ".join(r["indicative_percentiles"]))
    if r["kind"] == "timestamps":
        print(line("service_time ", r["service_ns"]))
        print(line("queue_delay  ", r["queue_delay_ns"]))
        if "intended_rate_per_s" in r:
            print(f"intended_rate_per_s={r['intended_rate_per_s']:.1f} achieved_completion_rate_per_s={r['achieved_rate_per_s']:.1f}")
        worst_key = max(r["co_ratios"], key=lambda k: r["co_ratios"][k] if not math.isnan(r["co_ratios"][k]) else 0)
        parts = " ".join(f"{k}={v:.2f}" for k, v in r["co_ratios"].items())
        flag = r["co_ratios"][worst_key] > 1.5
        print(f"response/service ratio: {parts}"
              + (f"  <- queueing at {worst_key}: service-time-only reporting would hide this" if flag else ""))
        if r["negative_queue_delay"]:
            print(f"WARNING: {r['negative_queue_delay']} operations started before their intended time: generator schedule or clocks are wrong")
        if r["response_ns"]["count"] and r["response_ns"]["count"] < 10000:
            print("note: fewer than 10000 operations; p99.9 and above are not meaningful")
        for label, d in r.get("groups", {}).items():
            print(line(f"  group {label}", d))
    else:
        print("note: single-column latencies cannot reveal coordinated omission; record intended start times")
    if "p99_block_spread_ns" in r:
        b = r["p99_block_spread_ns"]
        print(f"p99_across_{b['blocks']}_blocks: min={fmt(b['min'])} median={fmt(b['median'])} max={fmt(b['max'])}")
    if baseline:
        print("vs_baseline (response time, candidate/baseline):")
        for key in [f"p{p:g}" for p in PCTS] + ["max"]:
            base, cand = baseline["response_ns"][key], r["response_ns"][key]
            ratio = cand / base if base else float("nan")
            print(f"  {key}: {fmt(base)} -> {fmt(cand)} ({ratio:.3g}x)")
        bb, cb = baseline.get("p99_block_spread_ns"), r.get("p99_block_spread_ns")
        if bb and cb:
            above = sum(1 for v in cb["values"] if v > bb["max"])
            below = sum(1 for v in cb["values"] if v < bb["min"])
            print(f"  p99 blocks above baseline block range: {above}/{cb['blocks']}; below: {below}/{cb['blocks']}")
            if 0 < above <= cb["blocks"] // 5:
                print("  note: regression concentrated in few blocks -> episodic stall; align with GC/OS event timelines")
            elif above == 0 and below == 0:
                print("  note: every block p99 lies within the baseline range; difference may be run-to-run noise")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv")
    parser.add_argument("--baseline", help="baseline CSV in the same format")
    parser.add_argument("--blocks", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--episodes", action="store_true",
                        help="rows are recovery episodes, not a fixed-rate schedule")
    parser.add_argument("--expected", type=int,
                        help="operations the workload should have completed; fewer is invalid (exit 5)")
    args = parser.parse_args(argv)
    if args.blocks < 1:
        parser.error("--blocks must be positive")
    if args.expected is not None and args.expected < 1:
        parser.error("--expected must be positive")
    result = analyse(load(args.csv), args.blocks, args.episodes)
    baseline = analyse(load(args.baseline), args.blocks, args.episodes) if args.baseline else None
    if result["response_ns"]["count"] == 0 or (baseline is not None and baseline["response_ns"]["count"] == 0):
        print("no rows", file=sys.stderr)
        return 4
    for report in (result, baseline):
        if report is not None:
            count = report["response_ns"]["count"]
            report["indicative_percentiles"] = [f"p{p:g}" for p in PCTS if count * (1 - p / 100) < 100 - 1e-8]
    incomplete = False
    if args.expected is not None:
        result["expected"] = args.expected
        result["completed"] = result["response_ns"]["count"]
        incomplete = result["completed"] < args.expected
    if args.json:
        json.dump({"candidate": result, "baseline": baseline, "valid": not incomplete}, sys.stdout, indent=2)
        print()
    else:
        print_text(result, baseline)
    return 5 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
