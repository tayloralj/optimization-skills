#!/usr/bin/env python3
"""Generate a host-specific lab-tune.sh plan from a named profile. Read-only.

Profiles:
  benchmark-host  performance governor and deep idle states off on the hot CPUs, THP
                  madvise, NUMA balancing/KSM/timer migration off, calmer vmstat
  irq-isolation   move IRQs, unbound workqueues, and the softlockup watchdog off the
                  hot CPUs onto the housekeeping CPUs (needs --housekeeping)
  quiet-watchdogs NMI watchdog off; softlockup watchdog on housekeeping CPUs only

Only lines whose target file exists and whose value would change are emitted, so
the plan is a precise diff for this host. Review it, then run
  lab-tune.sh plan PLAN   and (operator, root)   LAB_HOST_ACK=$(hostname) lab-tune.sh apply PLAN DIR
HOST_ROOT prefixes paths for reading (tests); emitted paths are always real paths.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import sys
from pathlib import Path

ROOT = os.environ.get("HOST_ROOT", "")
LIST_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
IDLE_LATENCY_US = 50


def rd(path: str) -> str | None:
    try:
        raw = Path(ROOT + path).read_text().strip()
    except OSError:
        return None
    selected = re.search(r"\[([^\]]+)\]", raw)
    return selected.group(1) if selected else raw


def expand(cpu_list: str) -> list[int]:
    cpus: list[int] = []
    for part in filter(None, cpu_list.split(",")):
        lo, _, hi = part.partition("-")
        cpus.extend(range(int(lo), int(hi or lo) + 1))
    return sorted(set(cpus))


def compact(cpus: list[int]) -> str:
    ranges, start, prev = [], None, None
    for c in sorted(cpus):
        if start is None:
            start = prev = c
        elif c == prev + 1:
            prev = c
        else:
            ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = prev = c
    if start is not None:
        ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ",".join(ranges)


def hexmask(cpus: list[int]) -> str:
    """Kernel cpumask format: hex, comma every 32 bits, most significant first."""
    value = sum(1 << c for c in cpus)
    words = []
    while True:
        words.append(value & 0xFFFFFFFF)
        value >>= 32
        if not value:
            break
    return ",".join([f"{words[-1]:x}"] + [f"{w:08x}" for w in reversed(words[:-1])])


class Plan:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.skipped: list[str] = []

    def set(self, path: str, value: str, why: str) -> None:
        current = rd(path)
        if current is None:
            self.skipped.append(f"{path} (absent on this host)")
        elif current == value:
            self.skipped.append(f"{path} (already {value})")
        else:
            self.lines.append(f"# {why}; currently {current}")
            self.lines.append(f"set {path} {value}")


def benchmark_host(plan: Plan, hot: list[int]) -> None:
    for c in hot:
        base = f"/sys/devices/system/cpu/cpu{c}"
        # EPP is deliberately not planned: amd-pstate-epp and intel_pstate force EPP=performance under the
        # performance governor and reject other EPP writes, which would break reverse-order rollback.
        plan.set(f"{base}/cpufreq/scaling_governor", "performance", f"cpu{c}: avoid frequency transitions (EPP follows)")
        idle_dir = Path(ROOT + f"{base}/cpuidle")
        for state in sorted(idle_dir.glob("state*"), key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 0):
            latency = rd(f"{base}/cpuidle/{state.name}/latency")
            if latency and latency.isdigit() and int(latency) >= IDLE_LATENCY_US:
                name = rd(f"{base}/cpuidle/{state.name}/name") or state.name
                plan.set(f"{base}/cpuidle/{state.name}/disable", "1", f"cpu{c}: disable {name} (exit latency {latency} us)")
    thp = "/sys/kernel/mm/transparent_hugepage"
    if rd(f"{thp}/enabled") == "always":
        plan.set(f"{thp}/enabled", "madvise", "THP only where requested (-XX:+UseTransparentHugePages)")
    if rd(f"{thp}/defrag") == "always":
        plan.set(f"{thp}/defrag", "madvise", "no direct compaction stalls for ordinary allocations")
    plan.set("/proc/sys/kernel/numa_balancing", "0", "no NUMA hinting faults or page migration")
    plan.set("/sys/kernel/mm/ksm/run", "0", "no KSM scanning or copy-on-write faults")
    plan.set("/proc/sys/kernel/timer_migration", "0", "keep timers where they were armed")
    stat = rd("/proc/sys/vm/stat_interval")
    if stat and stat.isdigit() and int(stat) < 10:
        plan.set("/proc/sys/vm/stat_interval", "10", "fewer vmstat updates on every CPU")


def irq_isolation(plan: Plan, hot: list[int], housekeeping: list[int]) -> None:
    hk = compact(housekeeping)
    irq_root = Path(ROOT + "/proc/irq")
    for irq_dir in sorted(irq_root.glob("[0-9]*"), key=lambda p: int(p.name)):
        affinity = rd(f"/proc/irq/{irq_dir.name}/smp_affinity_list")
        if affinity and LIST_RE.match(affinity) and set(expand(affinity)) & set(hot):
            plan.set(f"/proc/irq/{irq_dir.name}/smp_affinity_list", hk, f"IRQ {irq_dir.name} off hot CPUs")
    plan.set("/sys/devices/virtual/workqueue/cpumask", hexmask(housekeeping), "unbound workqueues on housekeeping CPUs")
    plan.set("/proc/sys/kernel/watchdog_cpumask", hk, "softlockup watchdog on housekeeping CPUs")


def quiet_watchdogs(plan: Plan, housekeeping: list[int] | None) -> None:
    plan.set("/proc/sys/kernel/nmi_watchdog", "0", "no periodic NMI watchdog perf events")
    if housekeeping:
        plan.set("/proc/sys/kernel/watchdog_cpumask", compact(housekeeping), "softlockup watchdog on housekeeping CPUs")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("profile", choices=["benchmark-host", "irq-isolation", "quiet-watchdogs"])
    parser.add_argument("--cpus", required=True, help="latency-critical CPUs, e.g. 4-7,16-19")
    parser.add_argument("--housekeeping", help="CPUs for the OS, IRQs, GC and JIT threads, e.g. 0-1,12-13")
    args = parser.parse_args(argv)
    if not LIST_RE.match(args.cpus) or (args.housekeeping and not LIST_RE.match(args.housekeeping)):
        parser.error("CPU lists look like 0-3,8")
    hot = expand(args.cpus)
    online = rd("/sys/devices/system/cpu/online")
    if online and LIST_RE.match(online):
        missing = sorted(set(hot) - set(expand(online)))
        if missing:
            parser.error(f"CPUs not online on this host: {compact(missing)}")
    housekeeping = expand(args.housekeeping) if args.housekeeping else None
    if housekeeping and set(housekeeping) & set(hot):
        parser.error("--housekeeping must not overlap --cpus")
    if args.profile == "irq-isolation" and not housekeeping:
        parser.error("irq-isolation needs --housekeeping")

    plan = Plan()
    if args.profile == "benchmark-host":
        benchmark_host(plan, hot)
    elif args.profile == "irq-isolation":
        irq_isolation(plan, hot, housekeeping)
    else:
        quiet_watchdogs(plan, housekeeping)

    print(f"# lab-tune plan: profile={args.profile} host={socket.gethostname()} hot_cpus={compact(hot)}"
          + (f" housekeeping={compact(housekeeping)}" if housekeeping else ""))
    print("# Generated read-only from this host's current values. Runtime-only; lost on reboot.")
    print("# Review every line, then: lab-tune.sh plan THIS_FILE")
    for line in plan.lines:
        print(line)
    print(f"# entries={sum(1 for l in plan.lines if l.startswith('set '))} unchanged_or_absent={len(plan.skipped)}")
    for skipped in plan.skipped:
        print(f"#   skipped {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
