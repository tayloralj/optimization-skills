#!/usr/bin/env python3
"""Compare two analysed capture bundles: a baseline (healthy period) and an
incident. Reads the analysis.json that analyze-bundle.py wrote for each and
reports what changed: process and thread-group CPU, host CPU, steal, pressure,
cgroup throttling, GC pauses and allocation, hot methods, allocation sites,
profile self time, and findings that appear only in the incident. With
async-profiler's jfrconv available it also writes a differential flame graph.

  compare-bundles.py BASELINE_ANALYSIS_DIR INCIDENT_ANALYSIS_DIR [--output COMPARISON.md] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def load(directory: Path) -> dict:
    path = directory / "analysis.json"
    if not path.is_file():
        raise SystemExit(f"{path} not found; run analyze-bundle.py first")
    data = json.loads(path.read_text())
    if data.get("analysis_format") != 1:
        raise SystemExit(f"{path}: unsupported analysis_format {data.get('analysis_format')}")
    return data


def get(data: dict, *keys, default=None):
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def row(label: str, base, incident, unit: str = "", scale: float = 1.0, worse_if_higher: bool = True) -> dict | None:
    b, i = number(base), number(incident)
    if b is None and i is None:
        return None
    b = None if b is None else b * scale
    i = None if i is None else i * scale
    change = None if b is None or i is None else i - b
    flag = ""
    if change is not None:
        rel = abs(change) / max(abs(b), 1e-9)
        if rel >= 0.5 and abs(change) >= 1.0:
            flag = "worse" if (change > 0) == worse_if_higher else "better"
    return {"metric": label, "baseline": b, "incident": i, "change": change, "unit": unit, "flag": flag}


def share_table(base: list, incident: list, limit: int = 12) -> list[dict]:
    b = {name: pct for name, pct in base}
    i = {name: pct for name, pct in incident}
    rows = [{"name": n, "baseline_pct": b.get(n, 0.0), "incident_pct": i.get(n, 0.0),
             "change": i.get(n, 0.0) - b.get(n, 0.0)} for n in set(b) | set(i)]
    return sorted(rows, key=lambda r: -abs(r["change"]))[:limit]


def first_profile(data: dict, key: str) -> list:
    for name, tables in sorted(get(data, "profiles", default={}).items()):
        if key in tables and tables[key]:
            return tables[key]
    return []


def find_jfrconv(explicit: str | None) -> str | None:
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("jfrconv")
    home = os.environ.get("ASYNC_PROFILER_HOME")
    if not found and home and os.access(Path(home) / "bin/jfrconv", os.X_OK):
        found = str(Path(home) / "bin/jfrconv")
    return found if found and shutil.which("java") else None


def fmt(value, unit: str) -> str:
    if value is None:
        return "-"
    return f"{value:,.1f}{unit}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("incident", type=Path)
    parser.add_argument("--output", type=Path, help="write the Markdown report here (default: stdout)")
    parser.add_argument("--json", action="store_true", help="print the comparison as JSON instead of Markdown")
    parser.add_argument("--jfrconv", help="async-profiler jfrconv for a differential flame graph")
    args = parser.parse_args(argv)
    base, inc = load(args.baseline), load(args.incident)

    caveats = []
    for key, label in (("host", "host"), ("pid", "process id")):
        if get(base, "capture", key) != get(inc, "capture", key):
            caveats.append(f"different {label}: `{get(base, 'capture', key)}` vs `{get(inc, 'capture', key)}`")
    if base.get("jvm_version") != inc.get("jvm_version"):
        caveats.append(f"different JVM: `{base.get('jvm_version')}` vs `{inc.get('jvm_version')}`")
    for label, data in (("baseline", base), ("incident", inc)):
        if get(data, "capture", "integrity_problems"):
            caveats.append(f"{label} bundle has integrity problems")
        if get(data, "capture", "loose"):
            caveats.append(f"{label} came from loose files: host and process sections are missing")

    def gc_rate(data: dict) -> float | None:
        count, elapsed = number(get(data, "gc", "pause_count")), number(get(data, "capture", "elapsed_s"))
        return count / elapsed if count is not None and elapsed else None

    def rss_growth(data: dict) -> float | None:
        a, b = number(get(data, "process", "rss_start_kib")), number(get(data, "process", "rss_end_kib"))
        return (b - a) / 1024 if a is not None and b is not None else None

    metrics = [r for r in (
        row("Process CPU (% of one core)", get(base, "process", "cpu_pct"), get(inc, "process", "cpu_pct"), "%"),
        row("Median sampled process CPU", get(base, "timeseries", "process_cpu_median_pct"), get(inc, "timeseries", "process_cpu_median_pct"), "%"),
        row("RSS at end", get(base, "process", "rss_end_kib"), get(inc, "process", "rss_end_kib"), " MiB", 1 / 1024),
        row("RSS growth in window", rss_growth(base), rss_growth(inc), " MiB"),
        row("Process disk read", get(base, "process", "read_mib"), get(inc, "process", "read_mib"), " MiB"),
        row("Process disk write", get(base, "process", "write_mib"), get(inc, "process", "write_mib"), " MiB"),
        row("Host user CPU", get(base, "host", "cpu_pct", "user"), get(inc, "host", "cpu_pct", "user"), "%"),
        row("Host system CPU", get(base, "host", "cpu_pct", "system"), get(inc, "host", "cpu_pct", "system"), "%"),
        row("Host iowait", get(base, "host", "cpu_pct", "iowait"), get(inc, "host", "cpu_pct", "iowait"), "%"),
        row("Host steal", get(base, "host", "cpu_pct", "steal"), get(inc, "host", "cpu_pct", "steal"), "%"),
        row("CPU pressure (some)", get(base, "host", "pressure_some_pct", "cpu"), get(inc, "host", "pressure_some_pct", "cpu"), "%"),
        row("I/O pressure (some)", get(base, "host", "pressure_some_pct", "io"), get(inc, "host", "pressure_some_pct", "io"), "%"),
        row("Memory pressure (some)", get(base, "host", "pressure_some_pct", "memory"), get(inc, "host", "pressure_some_pct", "memory"), "%"),
        row("Load average (1 min)", get(base, "host", "loadavg_1m"), get(inc, "host", "loadavg_1m"), ""),
        row("Host memory available", get(base, "host", "mem_available_pct"), get(inc, "host", "mem_available_pct"), "%", worse_if_higher=False),
        row("cgroup throttled time", get(base, "cgroup", "throttled_ms"), get(inc, "cgroup", "throttled_ms"), " ms"),
        row("GC pause share of wall time", get(base, "gc", "pause_fraction"), get(inc, "gc", "pause_fraction"), "%", 100.0),
        row("GC pauses per second", gc_rate(base), gc_rate(inc), "/s"),
        row("GC pause p99", get(base, "gc", "pause_ms", "p99"), get(inc, "gc", "pause_ms", "p99"), " ms"),
        row("GC pause max", get(base, "gc", "pause_ms", "max"), get(inc, "gc", "pause_ms", "max"), " ms"),
        row("Allocation rate (approx.)", get(base, "gc", "approx_allocation_mib_per_s"), get(inc, "gc", "approx_allocation_mib_per_s"), " MiB/s"),
        row("Time to safepoint max", get(base, "gc", "safepoints", "time_to_safepoint_ms", "max"),
            get(inc, "gc", "safepoints", "time_to_safepoint_ms", "max"), " ms"),
    ) if r]
    threads = share_table(list(get(base, "thread_groups_cpu_pct", default={}).items()),
                          list(get(inc, "thread_groups_cpu_pct", default={}).items()), 10)
    hot = share_table(first_profile(base, "hot-methods"), first_profile(inc, "hot-methods"))
    alloc = share_table(first_profile(base, "allocation-by-site"), first_profile(inc, "allocation-by-site"))
    self_time = share_table(first_profile(base, "self"), first_profile(inc, "self"))
    base_findings = {f["text"] for f in base.get("findings", [])}
    new_findings = [f for f in inc.get("findings", []) if f["text"] not in base_findings]

    diff_graph = None
    jfrconv = find_jfrconv(args.jfrconv)
    base_coll, inc_coll = base.get("collapsed_profiles") or [], inc.get("collapsed_profiles") or []
    if jfrconv and base_coll and inc_coll:
        out_dir = (args.output.parent if args.output else args.incident)
        target = out_dir / "flamegraph-diff.html"
        if not target.exists():
            result = subprocess.run([jfrconv, "--diff", base_coll[0], inc_coll[0], str(target)], capture_output=True, text=True)
            if result.returncode == 0 and target.is_file():
                diff_graph = str(target)

    result = {"comparison_format": 1, "baseline": str(args.baseline), "incident": str(args.incident), "caveats": caveats,
              "metrics": metrics, "thread_groups": threads, "hot_methods": hot, "allocation_sites": alloc,
              "profile_self": self_time, "new_findings": new_findings, "differential_flamegraph": diff_graph}
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    md = [f"# Comparison: `{args.baseline.name}` (baseline) → `{args.incident.name}` (incident)", ""]
    if caveats:
        md += ["**Comparability caveats:** " + "; ".join(caveats), ""]
    md += ["## Findings only in the incident", ""]
    md += [f"- **{f['severity']}**: {f['text']}" for f in new_findings] or ["- none"]
    md += ["", "## Metrics", "", "| Metric | Baseline | Incident | Change | |", "| --- | ---: | ---: | ---: | --- |"]
    for m in metrics:
        md.append(f"| {m['metric']} | {fmt(m['baseline'], m['unit'])} | {fmt(m['incident'], m['unit'])} | "
                  f"{change_cell(m)} | {m['flag']} |")
    for title, rows in (("Thread groups by CPU (% of one core)", threads), ("Hot methods (JFR share)", hot),
                        ("Allocation sites (JFR share)", alloc), ("Profile self time (leaf share)", self_time)):
        if not rows:
            continue
        md += ["", f"## {title}", "", "| Name | Baseline | Incident | Change |", "| --- | ---: | ---: | ---: |"]
        md += [f"| `{r['name']}` | {r['baseline_pct']:.1f} | {r['incident_pct']:.1f} | {r['change']:+.1f} |" for r in rows]
    if diff_graph:
        md += ["", f"Differential flame graph: `{diff_graph}` (red grew in the incident, blue shrank)."]
    md += ["", "Treat differences as leads: check they exceed run-to-run variation (repeat the baseline capture) "
           "and that both captures covered comparable load.", ""]
    text = "\n".join(md)
    if args.output:
        if args.output.exists():
            parser.error(f"{args.output} already exists")
        args.output.write_text(text)
        print(f"comparison={args.output}")
    else:
        print(text, end="")
    return 0


def change_cell(m: dict) -> str:
    return "-" if m["change"] is None else f"{m['change']:+,.1f}{m['unit']}"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
