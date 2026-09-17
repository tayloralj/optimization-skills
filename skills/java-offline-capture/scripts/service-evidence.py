#!/usr/bin/env python3
"""Summarise optional systemd, journal, and coredump evidence from a bundle."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def analyse(root: Path) -> dict:
    unit = read(root / "host/systemd-unit.txt")
    journal = read(root / "host/systemd-journal.txt")
    core = read(root / "host/coredumpctl.txt")
    findings = []
    if unit:
        state = re.search(r"^ActiveState=(\S+)", unit, re.M)
        result = re.search(r"^Result=(\S+)", unit, re.M)
        if state and state.group(1) not in {"active", "activating"}:
            findings.append({"severity": "warn", "kind": "service-state", "detail": f"ActiveState={state.group(1)}"})
        if result and result.group(1) not in {"success", "exit-code", ""}:
            findings.append({"severity": "warn", "kind": "service-result", "detail": f"Result={result.group(1)}"})
    oom = len(re.findall(r"(?i)out of memory|oom-kill|killed process .*java", journal))
    crashes = len(re.findall(r"(?i)segfault|core dumped|fatal error|hs_err_pid", journal + core))
    restarts = len(re.findall(r"(?i)(entered running state|starting |scheduled restart|main process exited)", journal))
    if oom:
        findings.append({"severity": "warn", "kind": "oom", "detail": f"{oom} OOM-related journal matches"})
    if crashes:
        findings.append({"severity": "warn", "kind": "crash", "detail": f"{crashes} crash/coredump matches"})
    if restarts:
        findings.append({"severity": "info", "kind": "restart", "detail": f"{restarts} service lifecycle matches"})
    return {"schema_version": 1, "files": {"systemd_unit": bool(unit), "journal": bool(journal), "coredump": bool(core)}, "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = analyse(args.bundle)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("Service evidence")
        print("files=" + ",".join(k for k, v in result["files"].items() if v) or "files=none")
        for finding in result["findings"]:
            print(f"{finding['severity']}: {finding['kind']}: {finding['detail']}")
        if not result["findings"]:
            print("info: no recognised service, OOM, restart, or crash signals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
