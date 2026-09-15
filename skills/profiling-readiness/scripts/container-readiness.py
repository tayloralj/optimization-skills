#!/usr/bin/env python3
"""Report read-only namespace, cgroup, and capability facts for a PID."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def ns(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=os.getpid())
    args = parser.parse_args()
    if args.pid <= 0:
        parser.error("--pid must be positive")
    proc_root = Path(os.environ.get("PROC_ROOT", "/proc"))
    cgroup_root = Path(os.environ.get("CGROUP_ROOT", "/sys/fs/cgroup"))
    proc = proc_root / str(args.pid)
    status_text = read(proc / "status")
    cgroup_text = read(proc / "cgroup")
    if status_text is None or cgroup_text is None:
        print(f"cannot read proc status/cgroup for PID {args.pid}", file=sys.stderr)
        return 2
    values: dict[str, str] = {}
    for line in status_text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            values[key] = value.strip()
    cgroup_path: str | None = None
    cgroup_version = "unknown"
    for line in cgroup_text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0":
            cgroup_version, cgroup_path = "v2", fields[2]
            break
    if cgroup_path is None:
        cgroup_version = "v1_or_unknown"
        for line in cgroup_text.splitlines():
            fields = line.split(":", 2)
            if len(fields) == 3:
                cgroup_path = fields[2]
                break
    if cgroup_path and ".." in Path(cgroup_path).parts:
        print("unsafe cgroup path", file=sys.stderr)
        return 2
    group = cgroup_root / cgroup_path.lstrip("/") if cgroup_path else None
    controller_files = {}
    for name in ("cpu.max", "cpu.stat", "memory.max", "memory.events", "cpuset.cpus.effective"):
        value = read(group / name) if group else None
        if value is not None:
            controller_files[name] = value
    self_pid_ns = ns(proc_root / "self/ns/pid")
    target_pid_ns = ns(proc / "ns/pid")
    self_mnt_ns = ns(proc_root / "self/ns/mnt")
    target_mnt_ns = ns(proc / "ns/mnt")
    result = {
        "pid": args.pid,
        "uid": values.get("Uid", "unknown").split()[0],
        "gid": values.get("Gid", "unknown").split()[0],
        "cpus_allowed": values.get("Cpus_allowed_list", "unknown"),
        "mems_allowed": values.get("Mems_allowed_list", "unknown"),
        "cap_eff": values.get("CapEff", "unknown"),
        "no_new_privs": values.get("NoNewPrivs", "unknown"),
        "seccomp": values.get("Seccomp", "unknown"),
        "cgroup_version": cgroup_version,
        "cgroup_path": cgroup_path or "unknown",
        "cgroup_files": controller_files,
        "pid_namespace": target_pid_ns or "unknown",
        "mount_namespace": target_mnt_ns or "unknown",
        "same_pid_namespace_as_checker": bool(self_pid_ns and self_pid_ns == target_pid_ns),
        "same_mount_namespace_as_checker": bool(self_mnt_ns and self_mnt_ns == target_mnt_ns),
        "profile_scope": "same-namespace-check-required",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
