#!/usr/bin/env python3
"""Capture read-only CPU frequency, thermal, and energy-counter state as JSON."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def value(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("HOST_ROOT", "/"),
                        help="host filesystem prefix for tests or offline snapshots")
    args = parser.parse_args()
    root = Path(args.root)
    cpu_root = root / "sys/devices/system/cpu"
    cpus = []
    for directory in sorted(cpu_root.glob("cpu[0-9]*"), key=lambda p: int(p.name[3:])):
        if not directory.is_dir():
            continue
        fields = {name: value(directory / "cpufreq" / name) for name in
                  ("scaling_cur_freq", "cpuinfo_cur_freq", "scaling_governor",
                   "energy_performance_preference", "cpuinfo_min_freq", "cpuinfo_max_freq")}
        cpus.append({"cpu": int(directory.name[3:]),
                     **{key: val for key, val in fields.items() if val is not None}})
    thermals = []
    for directory in sorted((root / "sys/class/thermal").glob("thermal_zone*")):
        if not directory.is_dir():
            continue
        fields = {name: value(directory / name) for name in ("type", "temp")}
        thermals.append({"zone": directory.name,
                         **{key: val for key, val in fields.items() if val is not None}})
    energy = []
    for directory in sorted((root / "sys/class/powercap").glob("*")):
        if not directory.is_dir():
            continue
        fields = {name: value(directory / name) for name in
                  ("name", "energy_uj", "max_energy_range_uj")}
        energy.append({"path": str(directory.relative_to(root)),
                       **{key: val for key, val in fields.items() if val is not None}})
    print(json.dumps({"schema_version": 1, "cpu_count": len(cpus),
                      "boost": value(cpu_root / "cpufreq/boost"), "cpus": cpus,
                      "thermal_zones": thermals, "powercap_zones": energy},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
