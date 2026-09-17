#!/usr/bin/env python3
"""Report vendor, PMU, and installed-profiler readiness without changing the host."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path


def command_output(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace") if Path("/proc/cpuinfo").is_file() else ""
    vendor = "AMD" if "AuthenticAMD" in cpuinfo else "Intel" if "GenuineIntel" in cpuinfo else "unknown"
    sources = sorted(p.name for p in Path("/sys/bus/event_source/devices").glob("*") if p.is_dir())
    tools = {}
    for name in ("vtune", "vtune-backend", "AMDuProfCLI", "AMDuProfPcm", "pcm", "pcm-memory"):
        path = shutil.which(name)
        tools[name] = {"path": path, "version": command_output([path, "--version"]) if path else "missing"}
    result = {"schema_version": 1, "vendor": vendor, "kernel": platform.release(), "pmu_sources": sources, "tools": tools,
              "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip() if Path("/proc/sys/kernel/perf_event_paranoid").is_file() else "unavailable"}
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"vendor={vendor} kernel={result['kernel']} perf_event_paranoid={result['perf_event_paranoid']}")
        print("pmu_sources=" + (",".join(sources) or "none"))
        for name, data in tools.items():
            print(f"{name}={data['path'] or 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
