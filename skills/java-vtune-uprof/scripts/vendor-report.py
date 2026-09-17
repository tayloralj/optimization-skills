#!/usr/bin/env python3
"""Extract portable metrics from exported vendor/perf text artifacts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse(root: Path) -> dict:
    metrics = {}
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        files.append(str(path.relative_to(root)))
        text = path.read_text(errors="replace")[:2_000_000]
        for key, pattern in (("cycles", r"(?i)(?:cycles|cpu.?cycles)[^0-9]*([0-9][0-9,]*)"),
                             ("instructions", r"(?i)instructions[^0-9]*([0-9][0-9,]*)"),
                             ("samples", r"(?i)samples?[^0-9]*([0-9][0-9,]*)")):
            match = re.search(pattern, text)
            if match and key not in metrics:
                metrics[key] = int(match.group(1).replace(",", ""))
    if metrics.get("cycles") and metrics.get("instructions"):
        metrics["ipc"] = round(metrics["instructions"] / metrics["cycles"], 4)
    return {"schema_version": 1, "files": files, "metrics": metrics, "attribution": any(re.search(r"(?i)(java|hotspot|jit|::)", f) for f in files)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("root", type=Path); p.add_argument("--json", action="store_true"); a = p.parse_args()
    result = parse(a.root)
    print(json.dumps(result, sort_keys=True) if a.json else "files=%d metrics=%s attribution=%s" % (len(result["files"]), result["metrics"], result["attribution"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
