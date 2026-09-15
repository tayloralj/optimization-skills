#!/usr/bin/env python3
"""Analyse a JVM capture bundle produced by the collector kit (collect.sh).

Runs on the analysis machine. It safely extracts the archive (no absolute paths,
no '..', no links or devices, size-capped), verifies SHA256SUMS, turns the
start/end /proc snapshots into deltas, runs the sibling skills' analysers when
they are installed (GC log summary, JFR report, NMT comparison), and writes
ANALYSIS.md: a findings-first summary for a human or an agent to read.

  analyze-bundle.py jvmcap-HOST-PID-TIME.tar.gz NEW_OUTPUT_DIR [--expect-sha256 HEX]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
GC_SUMMARY = SKILLS_ROOT / "java-gc-tuning/scripts/gc-log-summary.py"
JFR_REPORT = SKILLS_ROOT / "java-flight-recorder/scripts/jfr-report.sh"
NMT_COMPARE = SKILLS_ROOT / "java-native-memory/scripts/nmt-compare.py"
MAX_UNPACKED = 8 * 1024**3
VMSTAT_KEYS = ("pgmajfault", "pswpin", "pswpout", "compact_stall", "thp_fault_alloc", "thp_collapse_alloc",
               "numa_hint_faults", "numa_pages_migrated", "pgscan_direct", "oom_kill")
SNMP_KEYS = {("Udp", "InErrors"), ("Udp", "RcvbufErrors"), ("Udp", "SndbufErrors"), ("Tcp", "RetransSegs"),
             ("Tcp", "InErrs"), ("TcpExt", "ListenDrops"), ("TcpExt", "ListenOverflows"), ("TcpExt", "TCPTimeouts")}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, dest: Path) -> Path:
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        tops = set()
        total = 0
        for m in members:
            name = m.name
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or not parts:
                raise SystemExit(f"unsafe path in archive: {name!r}")
            if not (m.isfile() or m.isdir()):
                raise SystemExit(f"archive contains a link or special file: {name!r}")
            total += m.size
            tops.add(parts[0])
        if len(tops) != 1 or not next(iter(tops)).startswith("jvmcap-"):
            raise SystemExit(f"not a collector bundle (top-level entries: {sorted(tops)[:3]})")
        if total > MAX_UNPACKED:
            raise SystemExit(f"archive expands to {total} bytes; refusing")
        dest.mkdir(mode=0o700)
        for m in members:
            target = dest / m.name
            if m.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with tar.extractfile(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                target.chmod(0o600)
    return dest / next(iter(tops))


def verify_sums(bundle: Path) -> list[str]:
    problems = []
    sums = bundle / "SHA256SUMS"
    if not sums.is_file():
        return ["SHA256SUMS missing"]
    listed = set()
    for line in sums.read_text().splitlines():
        digest, _, name = line.partition("  ")
        name = name.removeprefix("./")
        listed.add(name)
        path = bundle / name
        if not path.is_file():
            problems.append(f"missing {name}")
        elif sha256(path) != digest:
            problems.append(f"checksum mismatch {name}")
    for path in bundle.rglob("*"):
        rel = path.relative_to(bundle).as_posix()
        if path.is_file() and rel != "SHA256SUMS" and rel not in listed:
            problems.append(f"unlisted file {rel}")
    return problems


def kv_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                data[key.strip()] = value.strip()
    return data


def read(path: Path) -> str:
    return path.read_text(errors="replace") if path.is_file() else ""


def elapsed_seconds(bundle: Path) -> float | None:
    try:
        return float(read(bundle / "proc-end/uptime_s")) - float(read(bundle / "proc-start/uptime_s"))
    except ValueError:
        return None


def thread_deltas(bundle: Path, clk_tck: int, elapsed: float) -> list[dict]:
    def load(path: Path) -> dict[str, dict]:
        rows = {}
        lines = read(path).splitlines()
        if not lines:
            return rows
        header = lines[0].split("\t")
        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) == len(header):
                rows[cols[0]] = dict(zip(header, cols))
        return rows

    start, end = load(bundle / "proc-start/threads.tsv"), load(bundle / "proc-end/threads.tsv")
    out = []
    for tid, e in end.items():
        s = start.get(tid)
        if not s:
            continue

        def d(key: str) -> int:
            try:
                return int(e[key]) - int(s[key])
            except (ValueError, KeyError):
                return 0
        cpu_ticks = d("utime") + d("stime")
        out.append({
            "tid": tid, "name": e["comm"],
            "cpu_pct": 100.0 * cpu_ticks / clk_tck / elapsed if elapsed else 0.0,
            "run_delay_ms": d("run_delay_ns") / 1e6,
            "nonvoluntary": d("nonvoluntary_ctxt"),
            "voluntary": d("voluntary_ctxt"),
            "last_cpu": e.get("processor", "?"),
        })
    return out


def interrupt_deltas(bundle: Path) -> list[tuple[str, int, str]]:
    def load(path: Path) -> dict[str, tuple[int, str]]:
        lines = read(path).splitlines()
        if not lines:
            return {}
        ncpu = len(lines[0].split())
        rows = {}
        for line in lines[1:]:
            name, _, rest = line.partition(":")
            fields = rest.split()
            counts = [int(f) for f in fields[:ncpu] if f.isdigit()]
            desc = " ".join(fields[len(counts):])
            rows[name.strip()] = (sum(counts), desc)
        return rows

    start, end = load(bundle / "proc-start/interrupts"), load(bundle / "proc-end/interrupts")
    deltas = [(k, v[0] - start[k][0], v[1]) for k, v in end.items() if k in start]
    return sorted(deltas, key=lambda t: -t[1])


def vmstat_deltas(bundle: Path) -> dict[str, int]:
    def load(path: Path) -> dict[str, int]:
        out = {}
        for line in read(path).splitlines():
            key, _, value = line.partition(" ")
            if value.strip().isdigit():
                out[key] = int(value)
        return out

    start, end = load(bundle / "proc-start/vmstat"), load(bundle / "proc-end/vmstat")
    result = {k: end[k] - start[k] for k in VMSTAT_KEYS if k in end and k in start}
    allocstall = sum(end[k] - start.get(k, 0) for k in end if k.startswith("allocstall"))
    if any(k.startswith("allocstall") for k in end):
        result["allocstall_total"] = allocstall
    return result


def snmp_deltas(bundle: Path) -> dict[str, int]:
    def load(*paths: Path) -> dict[tuple[str, str], int]:
        out = {}
        for path in paths:
            lines = read(path).splitlines()
            for header, values in zip(lines[0::2], lines[1::2]):
                proto, _, names = header.partition(":")
                _, _, nums = values.partition(":")
                for name, num in zip(names.split(), nums.split()):
                    if num.lstrip("-").isdigit():
                        out[(proto, name)] = int(num)
        return out

    start = load(bundle / "proc-start/net_snmp", bundle / "proc-start/net_netstat")
    end = load(bundle / "proc-end/net_snmp", bundle / "proc-end/net_netstat")
    return {f"{p}.{n}": end[(p, n)] - start[(p, n)] for (p, n) in sorted(SNMP_KEYS) if (p, n) in end and (p, n) in start}


def pressure(bundle: Path, elapsed: float) -> dict[str, float]:
    out = {}
    for kind in ("cpu", "io", "memory"):
        s, e = read(bundle / f"proc-start/pressure_{kind}"), read(bundle / f"proc-end/pressure_{kind}")
        ms, me = re.search(r"^some .*total=(\d+)", s, re.M), re.search(r"^some .*total=(\d+)", e, re.M)
        if ms and me and elapsed:
            out[kind] = 100.0 * (int(me.group(1)) - int(ms.group(1))) / 1e6 / elapsed
    return out


def status_field(path: Path, key: str) -> int | None:
    m = re.search(rf"^{key}:\s+(\d+)", read(path), re.M)
    return int(m.group(1)) if m else None


def thread_dump_summary(path: Path) -> dict:
    text = read(path)
    states: dict[str, int] = {}
    blocked_frames: dict[str, int] = {}
    for block in re.split(r"\n(?=\")", text):
        m = re.search(r"java\.lang\.Thread\.State: (\w+)", block)
        if not m:
            continue
        states[m.group(1)] = states.get(m.group(1), 0) + 1
        if m.group(1) == "BLOCKED":
            frame = re.search(r"^\s+at (\S+)", block, re.M)
            if frame:
                blocked_frames[frame.group(1)] = blocked_frames.get(frame.group(1), 0) + 1
    return {"states": states, "blocked_top_frames": sorted(blocked_frames.items(), key=lambda kv: -kv[1])[:5]}


def uptime_at_start(bundle: Path) -> float | None:
    m = re.search(r"([\d.]+)\s*s", read(bundle / "jvm/VM.uptime.txt"))
    return float(m.group(1)) if m else None


def run_tool(cmd: list[str], out: Path) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    out.write_text(result.stdout + (("\n# stderr\n" + result.stderr) if result.stderr.strip() else ""))
    return result.returncode, result.stdout


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path, help="new directory for the extracted bundle and ANALYSIS.md")
    parser.add_argument("--expect-sha256", help="sha256 printed by collect.sh on the source host")
    args = parser.parse_args(argv)

    if args.output.exists():
        parser.error(f"{args.output} already exists")
    archive_sha = sha256(args.archive)
    if args.expect_sha256 and archive_sha != args.expect_sha256.lower():
        print(f"sha256 mismatch: got {archive_sha}, expected {args.expect_sha256}", file=sys.stderr)
        return 5
    bundle = safe_extract(args.archive, args.output)
    problems = verify_sums(bundle)
    reports = args.output / "reports"
    reports.mkdir(mode=0o700)

    manifest = kv_file(bundle / "MANIFEST.txt")
    clk_tck = int(manifest.get("clk_tck", "100") or 100)
    elapsed = elapsed_seconds(bundle) or float(manifest.get("duration_s", "0") or 0)
    findings: list[tuple[str, str]] = []   # (severity, text)
    next_skills: set[str] = set()
    md: list[str] = []

    md += [f"# Analysis of {manifest.get('bundle', args.archive.name)}", ""]
    md += ["## Capture", "",
           f"- Archive sha256: `{archive_sha}`" + (" (matches expected)" if args.expect_sha256 else ""),
           f"- Integrity: {'OK' if not problems else 'PROBLEMS: ' + '; '.join(problems[:5])}",
           f"- Host `{manifest.get('host', '?')}`, kernel `{manifest.get('kernel', '?')}`, "
           f"{manifest.get('logical_cpus', '?')} logical CPUs",
           f"- PID {manifest.get('pid', '?')}, window {manifest.get('duration_s', '?')} s "
           f"({manifest.get('started_utc', '?')} to {manifest.get('finished_utc', '?')}), measured {elapsed:.1f} s",
           f"- JFR mode `{manifest.get('jfr_mode', '?')}`, interrupted `{manifest.get('interrupted', '?')}`, "
           f"target alive at end `{manifest.get('target_alive_at_end', '?')}`"]
    version = read(bundle / "jvm/VM.version.txt").strip().splitlines()
    if len(version) > 1:
        md.append(f"- JVM: {version[1].strip()}")
    failed = {k[5:]: v for k, v in manifest.items() if k.startswith("step.") and not (v == "ok" or v.startswith("copied="))}
    for key, value in manifest.items():
        if key.startswith("jfr_scrub.") and value != "ok":
            findings.append(("warn", f"JFR file {key[10:]} scrub status: {value}"))
    if failed:
        md.append("- Steps not completed: " + ", ".join(f"`{k}`={v}" for k, v in failed.items()))
    if problems:
        findings.append(("warn", "bundle integrity problems: " + "; ".join(problems[:5])))
    md.append("")

    vendor_files = sorted((bundle / "vendor").rglob("*") if (bundle / "vendor").is_dir() else [])
    if vendor_files:
        md += ["## Vendor profiler artifacts", "",
               "These files were preserved and checksum-verified. Open them with the matching vendor tool; this analyser does not parse proprietary databases.", ""]
        for path in vendor_files:
            if path.is_file():
                md.append(f"- `{path.relative_to(bundle)}` ({path.stat().st_size} bytes, sha256 `{sha256(path)}`)")
        md.append("")
        next_skills.add("java-vtune-uprof")

    # Process and threads
    threads = thread_deltas(bundle, clk_tck, elapsed)
    rss_start = status_field(bundle / "proc-start/pid_status", "VmRSS")
    rss_end = status_field(bundle / "proc-end/pid_status", "VmRSS")
    md += ["## Process", ""]
    if rss_start is not None and rss_end is not None:
        md.append(f"- RSS {rss_start // 1024} MiB → {rss_end // 1024} MiB ({(rss_end - rss_start) // 1024:+d} MiB over the window)")
    if threads:
        total_cpu = sum(t["cpu_pct"] for t in threads)
        md.append(f"- {len(threads)} threads; total CPU {total_cpu:.0f}% of one core")
        md += ["", "| Thread (tid) | CPU % | Run-queue delay ms | Involuntary switches | Last CPU |", "| --- | ---: | ---: | ---: | ---: |"]
        for t in sorted(threads, key=lambda t: -t["cpu_pct"])[:10]:
            md.append(f"| {t['name']} ({t['tid']}) | {t['cpu_pct']:.1f} | {t['run_delay_ms']:.1f} | {t['nonvoluntary']} | {t['last_cpu']} |")
        worst_delay = max(threads, key=lambda t: t["run_delay_ms"])
        if elapsed and worst_delay["run_delay_ms"] > 0.01 * elapsed * 1000:
            findings.append(("warn", f"thread {worst_delay['name']} ({worst_delay['tid']}) waited {worst_delay['run_delay_ms']:.0f} ms "
                                     f"for a CPU during {elapsed:.0f} s (run-queue delay >1% of the window)"))
            next_skills.update({"linux-low-latency-tuning", "linux-ebpf-io-network"})
    md.append("")

    # Host counters
    md += ["## Host counters over the window", ""]
    irqs = interrupt_deltas(bundle)
    if irqs and elapsed:
        md.append("- Top interrupts/s: " + ", ".join(f"{n} {d / elapsed:.0f}/s{(' (' + desc[:30] + ')') if desc else ''}" for n, d, desc in irqs[:6]))
    vm = vmstat_deltas(bundle)
    if vm:
        md.append("- vmstat deltas: " + ", ".join(f"{k}={v}" for k, v in vm.items()))
        if vm.get("pswpin", 0) or vm.get("pswpout", 0):
            findings.append(("warn", f"swapping during the window (pswpin={vm.get('pswpin')}, pswpout={vm.get('pswpout')})"))
            next_skills.add("linux-low-latency-tuning")
        if vm.get("compact_stall", 0) or vm.get("allocstall_total", 0):
            findings.append(("info", f"memory reclaim/compaction stalls (compact_stall={vm.get('compact_stall', 0)}, allocstall={vm.get('allocstall_total', 0)})"))
        if vm.get("pgmajfault", 0) > 100:
            findings.append(("info", f"{vm['pgmajfault']} major page faults host-wide"))
    net = snmp_deltas(bundle)
    if net:
        md.append("- Network error deltas: " + ", ".join(f"{k}={v}" for k, v in net.items()))
        if net.get("Udp.RcvbufErrors", 0) > 0 or net.get("Udp.InErrors", 0) > 0:
            findings.append(("warn", f"UDP receive errors (RcvbufErrors={net.get('Udp.RcvbufErrors', 0)}, InErrors={net.get('Udp.InErrors', 0)})"))
            next_skills.add("linux-ebpf-io-network")
        if net.get("Tcp.RetransSegs", 0) > 0:
            findings.append(("info", f"TCP retransmitted segments: {net['Tcp.RetransSegs']}"))
    psi = pressure(bundle, elapsed)
    if psi:
        md.append("- Pressure stall (some): " + ", ".join(f"{k} {v:.2f}%" for k, v in psi.items()))
        for kind, value in psi.items():
            if value > 5:
                findings.append(("warn", f"{kind} pressure: tasks stalled {value:.1f}% of the window"))
    audit = read(bundle / "host/audit.txt")
    audit_findings = [l.removeprefix("finding=") for l in audit.splitlines() if l.startswith("finding=")]
    if audit_findings:
        md += ["", "Host audit findings:", ""] + [f"- {f}" for f in audit_findings]
        if any(f.startswith("warn:cfs_") for f in audit_findings):
            findings.append(("warn", "cgroup CPU quota throttling reported by the host audit"))
    readiness = kv_file(bundle / "host/readiness.txt")
    if readiness:
        md.append(f"- Readiness status on the source host: `{readiness.get('status', '?')}`")
    md.append("")

    # GC logs
    logs = sorted((bundle / "logs").glob("*"))
    md += ["## GC and safepoints", ""]
    if logs and GC_SUMMARY.is_file():
        rc, out = run_tool([sys.executable, str(GC_SUMMARY), *map(str, logs)], reports / "gc-summary-full.txt")
        start_up = uptime_at_start(bundle)
        window_out = ""
        if start_up is not None:
            _, window_out = run_tool([sys.executable, str(GC_SUMMARY), "--from-uptime", f"{start_up:.3f}",
                                      "--to-uptime", f"{start_up + elapsed:.3f}", *map(str, logs)], reports / "gc-summary-window.txt")
        pick = (window_out or out).replace(str(bundle) + "/", "")
        md += ["During the capture window" if window_out else "Whole log", "", "```text"]
        md += [l for l in pick.splitlines() if re.match(r"^(collectors|pauses_ms|pause_fraction|approx_allocation|time_to_safepoint_ms|safepoint_total_ms)", l)]
        worst = pick.split("worst_pauses:", 1)[-1].splitlines()[1:4] if "worst_pauses:" in pick else []
        md += ["worst pauses:", *worst]
        alarm_lines = pick.split("alarms:", 1)[-1].strip().splitlines() if "alarms:" in pick else []
        md += ["alarms: " + (", ".join(a.strip() for a in alarm_lines) or "none"), "```",
               "", "Full reports: `reports/gc-summary-full.txt`, `reports/gc-summary-window.txt`"]
        frac = re.search(r"^pause_fraction: ([\d.]+)%", pick, re.M)
        if frac and float(frac.group(1)) >= 5:
            findings.append(("warn", f"GC pauses took {float(frac.group(1)):.1f}% of wall time (high allocation or small heap)"))
            next_skills.add("java-gc-tuning")
        ttsp = re.search(r"^time_to_safepoint_ms: .*max=([\d.]+)", pick, re.M)
        if ttsp and float(ttsp.group(1)) >= 10:
            findings.append(("info", f"time-to-safepoint reached {float(ttsp.group(1)):.1f} ms (threads slow to stop)"))
        m = re.search(r"^pauses_ms: .*max=([\d.]+)", pick, re.M)
        if m and float(m.group(1)) >= 10:
            findings.append(("warn", f"GC pause up to {float(m.group(1)):.1f} ms in the {'window' if window_out else 'log'}"))
            next_skills.add("java-gc-tuning")
        if any(a.strip().startswith(("full_gc", "evacuation_failure", "allocation_stall")) for a in alarm_lines):
            findings.append(("warn", "GC alarms: " + ", ".join(a.strip() for a in alarm_lines)))
            next_skills.add("java-gc-tuning")
    elif logs:
        md.append(f"{len(logs)} log file(s) in `logs/`; install the `java-gc-tuning` skill to summarise them.")
    else:
        md.append("No GC logs in the bundle (the JVM was not started with `-Xlog:gc*`).")
    md.append("")

    # JFR
    md += ["## JDK Flight Recorder", ""]
    jfr_files = sorted((bundle / "jvm").glob("*.jfr"))
    if jfr_files and JFR_REPORT.is_file() and shutil.which("jfr"):
        for jfr in jfr_files:
            report_dir = reports / f"jfr-{jfr.stem}"
            rc, out = run_tool(["bash", str(JFR_REPORT), str(jfr), str(report_dir)], reports / f"jfr-{jfr.stem}.log")
            if rc != 0:
                md.append(f"- `{jfr.name}`: report failed (see `reports/jfr-{jfr.stem}.log`; the analysis JDK may be older than the recording JDK)")
                continue
            md.append(f"- `{jfr.name}` → `reports/jfr-{jfr.stem}/` ({len(list(report_dir.glob('*.txt')))} views)")
            for view in ("hot-methods", "allocation-by-site", "contention-by-site", "gc-pauses"):
                files = [f for f in report_dir.glob("*.txt") if re.fullmatch(rf"\d+-{view}\.txt", f.name)]
                if files:
                    rows = [l for l in read(files[0]).splitlines() if l.strip() and not set(l.strip()) <= set("-")][:8]
                    md += ["", f"`{view}`:", "", "```text", *rows, "```"]
            contention = list(report_dir.glob("*-contention-by-site.txt"))
            if contention and len([l for l in read(contention[0]).splitlines() if l.strip()]) > 3:
                next_skills.add("java-flight-recorder")
    elif jfr_files:
        md.append(f"{len(jfr_files)} recording(s) in `jvm/`; install a JDK (for `jfr`) and the `java-flight-recorder` skill to render reports.")
    else:
        md.append("No JFR recording (collector ran with `--jfr none`, or no jcmd on the source host).")
    md.append("")

    # Native memory
    md += ["## Native memory", ""]
    if (bundle / "jvm/nmt-start").is_dir() and (bundle / "jvm/nmt-end").is_dir() and NMT_COMPARE.is_file():
        rc, out = run_tool([sys.executable, str(NMT_COMPARE), str(bundle / "jvm/nmt-start"), str(bundle / "jvm/nmt-end")], reports / "nmt-compare.txt")
        md += ["```text", *out.splitlines()[:14], "```"]
        m = re.search(r"^VmRSS_delta: ([+-]\d+)", out, re.M)
        if m and int(m.group(1)) > 256 * 1024:
            findings.append(("warn", f"RSS grew {int(m.group(1)) // 1024} MiB during the window"))
            next_skills.add("java-native-memory")
    else:
        md.append("No NMT snapshots (start the JVM with `-XX:NativeMemoryTracking=summary` to include them).")
    md.append("")

    # Thread dumps
    dumps = sorted((bundle / "jvm").glob("thread-dump-*.txt"))
    if dumps:
        md += ["## Thread dumps", ""]
        for dump in dumps:
            summary = thread_dump_summary(dump)
            md.append(f"- `{dump.name}`: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["states"].items())))
            if summary["blocked_top_frames"]:
                md.append("  - BLOCKED at: " + "; ".join(f"{f} ×{n}" for f, n in summary["blocked_top_frames"]))
                findings.append(("info", f"{dump.name}: {summary['states'].get('BLOCKED', 0)} BLOCKED threads"))
                next_skills.update({"java-async-profiler", "java-flight-recorder"})
        md.append("")

    head = ["## Findings", ""]
    if findings:
        head += [f"- **{sev}**: {text}" for sev, text in sorted(findings, key=lambda f: f[0] != "warn")]
    else:
        head.append("- No automatic findings crossed their thresholds. Read the sections below against the stated problem.")
    head += ["", "Automatic findings are prompts for investigation, not conclusions. Compare with a baseline capture "
             "from a healthy period on the same host when possible.", ""]
    head += ["## Suggested next skills", ""]
    head += [f"- `{s}`" for s in sorted(next_skills)] or ["- `java-performance-investigation` to decide the next step"]
    head.append("")
    analysis = args.output / "ANALYSIS.md"
    analysis.write_text("\n".join(md[:2] + head + md[2:]) + "\n")
    print(f"analysis={analysis}")
    print(f"bundle_dir={bundle}")
    print(f"integrity={'ok' if not problems else 'problems'} findings={len(findings)}")
    return 0 if not problems else 6


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
