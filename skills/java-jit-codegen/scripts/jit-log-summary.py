#!/usr/bin/env python3
"""Summarise HotSpot -XX:+PrintCompilation / -XX:+PrintInlining output (JDK 17-25).

Read-only. Typical capture on a controlled launch:
  java -XX:+UnlockDiagnosticVMOptions -XX:+PrintCompilation -XX:+PrintInlining ... > jit.txt
Output from several compiler threads can interleave; unparseable fragments are
counted and skipped rather than guessed. For per-compilation inlining trees use
-XX:+LogCompilation with JITWatch instead.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict

COMPILE_RE = re.compile(
    r"^\s*(?P<ts>\d+)\s+(?P<id>\d+)\s+(?P<attrs>[%sbn! ]*?)\s*(?P<tier>[0-4])?\s+"
    r"(?P<method>[\w$.<>/\[\]]+::[\w$<>]+(?:\([^)]*\)\S*)?)\s*"
    r"(?:@\s*(?P<bci>\d+)\s*)?(?:\((?P<bytes>\d+) bytes\)|\(native\))?\s*(?P<rest>.*)$"
)
INLINE_RE = re.compile(
    r"^(?P<indent>\s*)@\s*(?P<bci>\d+)\s+(?P<callee>[\w$.<>/\[\]]+::[\w$<>]+)\s+"
    r"\((?P<bytes>\d+) bytes\)\s+(?P<status>.+?)\s*$"
)
SUCCESS_RE = re.compile(
    r"^(?:inline|\(?intrinsic\)?$|force inline\b|accessor$|late inline succeeded)"
)
INTRINSIC_RE = re.compile(r"^\(?intrinsic\)?$")


def parse(paths: list[str]) -> dict:
    compiles = Counter()
    osr = 0
    native = 0
    compiles_per_method = Counter()
    not_entrant = Counter()
    not_entrant_methods = Counter()
    inline_outcomes = Counter()
    inline_failures: dict[str, Counter] = defaultdict(Counter)
    garbled = 0
    code_cache_full = 0
    timestamps: list[int] = []
    late: list[tuple[int, str, str]] = []

    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                if "CodeCache is full" in line or "code cache is full" in line.lower():
                    code_cache_full += 1
                    continue
                inline = INLINE_RE.match(line)
                if inline:
                    status = re.sub(r"\s{2,}.*$", "", inline["status"]).strip()
                    if status.startswith("@") or not status:
                        garbled += 1
                    elif INTRINSIC_RE.match(status):
                        inline_outcomes["intrinsic"] += 1
                    elif SUCCESS_RE.match(status):
                        inline_outcomes["inlined"] += 1
                    else:
                        reason = status.removeprefix("failed to inline:").strip()
                        inline_outcomes["failed"] += 1
                        inline_failures[reason][f"{inline['callee']} ({inline['bytes']} bytes)"] += 1
                    continue
                compile_line = COMPILE_RE.match(line)
                if compile_line and compile_line["method"]:
                    attrs = compile_line["attrs"] or ""
                    tier = compile_line["tier"] or "?"
                    method = compile_line["method"]
                    rest = compile_line["rest"] or ""
                    if "made not entrant" in rest or "made zombie" in rest:
                        reason = rest.split("made not entrant", 1)[-1].lstrip(": ").strip() or "unspecified"
                        not_entrant[reason] += 1
                        if reason != "not used":
                            not_entrant_methods[method] += 1
                        continue
                    ts = int(compile_line["ts"])
                    timestamps.append(ts)
                    if "n" in attrs:
                        native += 1
                        continue
                    if "%" in attrs:
                        osr += 1
                    compiles[f"tier{tier}"] += 1
                    compiles_per_method[method] += 1
                    late.append((ts, tier, method))
                    continue
                garbled += 1

    return {
        "compiles": compiles, "osr": osr, "native_wrappers": native,
        "compiles_per_method": compiles_per_method, "not_entrant": not_entrant,
        "not_entrant_methods": not_entrant_methods, "inline_outcomes": inline_outcomes,
        "inline_failures": inline_failures, "garbled_lines": garbled,
        "code_cache_full": code_cache_full, "timestamps": timestamps, "late": late,
    }


def summarise(data: dict, top: int, warmup_ms: int | None) -> dict:
    span = (min(data["timestamps"]), max(data["timestamps"])) if data["timestamps"] else None
    late_compiles = None
    if warmup_ms is not None:
        after = [(ts, tier, m) for ts, tier, m in data["late"] if ts >= warmup_ms]
        late_compiles = {
            "after_ms": warmup_ms,
            "count": len(after),
            "by_tier": dict(Counter(f"tier{t}" for _, t, _ in after)),
            "examples": [f"{ts}ms tier{t} {m}" for ts, t, m in after[-top:]],
        }
    failures = {
        reason: {"count": sum(c.values()), "top_callees": c.most_common(top)}
        for reason, c in sorted(data["inline_failures"].items(), key=lambda kv: -sum(kv[1].values()))
    }
    return {
        "timestamp_span_ms": span,
        "compiles_by_tier": dict(sorted(data["compiles"].items())),
        "osr_compiles": data["osr"],
        "native_wrappers": data["native_wrappers"],
        "most_recompiled": data["compiles_per_method"].most_common(top),
        "made_not_entrant_by_reason": dict(data["not_entrant"].most_common()),
        "deoptimized_methods": data["not_entrant_methods"].most_common(top),
        "inline_outcomes": dict(data["inline_outcomes"]),
        "inline_failures": failures,
        "late_compiles": late_compiles,
        "code_cache_full_events": data["code_cache_full"],
        "unparsed_lines": data["garbled_lines"],
    }


def print_text(s: dict) -> None:
    if s["timestamp_span_ms"]:
        print(f"timestamp_span_ms: {s['timestamp_span_ms'][0]}..{s['timestamp_span_ms'][1]}")
    print(f"compiles_by_tier: {s['compiles_by_tier']}  osr={s['osr_compiles']} native_wrappers={s['native_wrappers']}")
    print("made_not_entrant_by_reason:" + ("" if s["made_not_entrant_by_reason"] else " none"))
    for reason, count in s["made_not_entrant_by_reason"].items():
        note = "  (normal tier-3 -> tier-4 replacement)" if reason == "not used" else ""
        print(f"  {reason}: {count}{note}")
    if s["deoptimized_methods"]:
        print("deoptimized_methods (excluding 'not used'):")
        for method, count in s["deoptimized_methods"]:
            print(f"  {count}x {method}")
    print("most_recompiled:")
    for method, count in s["most_recompiled"]:
        if count > 1:
            print(f"  {count}x {method}")
    print(f"inline_outcomes: {s['inline_outcomes']}")
    print("inline_failures:")
    for reason, info in s["inline_failures"].items():
        print(f"  {reason}: {info['count']}")
        for callee, count in info["top_callees"]:
            print(f"      {count}x {callee}")
    if s["late_compiles"]:
        lc = s["late_compiles"]
        print(f"compiles_after_{lc['after_ms']}ms: {lc['count']} {lc['by_tier']}")
        for example in lc["examples"]:
            print(f"  {example}")
    if s["code_cache_full_events"]:
        print(f"CODE CACHE FULL events: {s['code_cache_full_events']}")
    print(f"unparsed_lines: {s['unparsed_lines']} (interleaved compiler-thread output)")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--warmup-ms", type=int, help="report compilations at or after this JVM uptime")
    args = parser.parse_args(argv)
    try:
        data = parse(args.logs)
    except OSError as exc:
        print(f"cannot read log: {exc}", file=sys.stderr)
        return 3
    if not data["timestamps"] and not data["inline_outcomes"]:
        print("no PrintCompilation or PrintInlining lines recognised", file=sys.stderr)
        return 4
    summary = summarise(data, args.top, args.warmup_ms)
    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        print()
    else:
        print_text(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
