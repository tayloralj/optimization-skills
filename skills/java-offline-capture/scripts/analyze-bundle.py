#!/usr/bin/env python3
"""Analyse a JVM capture bundle produced by the collector kit (collect.sh), or a
directory of loose evidence files (JFR, GC logs, thread dumps, hs_err crash logs,
class histograms, collapsed stacks).

Runs on the analysis machine. It safely extracts the archive (no absolute paths,
no '..', no links or devices, size-capped), verifies SHA256SUMS, turns the
start/end /proc and cgroup snapshots and the sampled time series into deltas,
joins hot threads to their stacks, runs the sibling skills' analysers when they
are installed (GC log summary, JFR report, NMT comparison), and writes
ANALYSIS.md (findings first) and analysis.json (for agents and compare-bundles.py).

  analyze-bundle.py jvmcap-HOST-PID-TIME.tar.gz NEW_OUTPUT_DIR [--expect-sha256 HEX]
  analyze-bundle.py DIRECTORY NEW_OUTPUT_DIR          # extracted bundle or loose files
  cat jvmcap-...tar.gz.part-* > jvmcap-...tar.gz      # rejoin a split bundle first
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import zlib
from datetime import datetime
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
GC_SUMMARY = SKILLS_ROOT / "java-gc-tuning/scripts/gc-log-summary.py"
JFR_REPORT = SKILLS_ROOT / "java-flight-recorder/scripts/jfr-report.sh"
NMT_COMPARE = SKILLS_ROOT / "java-native-memory/scripts/nmt-compare.py"
SUPPORTED_FORMATS = {"1"}
MAX_UNPACKED = 8 * 1024**3
MAX_LOOSE_FILE = 2 * 1024**3
VMSTAT_KEYS = ("pgmajfault", "pswpin", "pswpout", "compact_stall", "thp_fault_alloc", "thp_collapse_alloc",
               "numa_hint_faults", "numa_pages_migrated", "pgscan_direct", "oom_kill")
SNMP_KEYS = {("Udp", "InErrors"), ("Udp", "RcvbufErrors"), ("Udp", "SndbufErrors"), ("Tcp", "RetransSegs"),
             ("Tcp", "InErrs"), ("TcpExt", "ListenDrops"), ("TcpExt", "ListenOverflows"), ("TcpExt", "TCPTimeouts")}
CPU_FIELDS = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")
IDLE_FRAMES = ("sun.nio.ch.EPoll.wait", "sun.nio.ch.EPollArrayWrapper.epollWait", "sun.nio.ch.Net.accept",
               "sun.nio.ch.Net.poll", "java.net.SocketInputStream.socketRead0", "sun.nio.ch.SocketDispatcher.read0",
               "sun.nio.ch.NioSocketImpl.read", "java.io.FileInputStream.readBytes", "sun.nio.ch.KQueue.poll",
               "java.lang.ref.Reference.waitForReferencePendingList", "java.lang.VirtualThread.takeVirtualThreadListToUnblock",
               "jdk.internal.misc.Signal.findSignal0", "java.lang.ProcessHandleImpl.waitForProcessExit0")
JFR_TABLE_VIEWS = ("hot-methods", "allocation-by-site")


class Report:
    """Collects Markdown lines, findings, next skills, and JSON data."""

    def __init__(self) -> None:
        self.md: list[str] = []
        self.findings: list[tuple[str, str]] = []
        self.next_skills: set[str] = set()
        self.data: dict = {}

    def find(self, severity: str, text: str, *skills: str) -> None:
        self.findings.append((severity, text))
        self.next_skills.update(skills)


# ---------------------------------------------------------------------------
# Input: archive, extracted bundle, or loose files

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, dest: Path) -> Path:
    try:
        tar = tarfile.open(archive, "r:gz")
        members = tar.getmembers()
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise SystemExit(f"cannot read {archive} as a complete .tar.gz bundle ({exc}); rejoin split parts with cat first")
    with tar:
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


def copy_tree(src: Path, dest: Path) -> None:
    """Copy regular files only (no symlinks), keeping private permissions."""
    total = 0
    for path in sorted(src.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"refusing symlink in input: {path}")
        rel = path.relative_to(src)
        if path.is_dir():
            (dest / rel).mkdir(mode=0o700, parents=True, exist_ok=True)
        elif path.is_file():
            total += path.stat().st_size
            if total > MAX_UNPACKED:
                raise SystemExit("input directory is larger than 8 GiB; refusing")
            (dest / rel).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(path, dest / rel)
            (dest / rel).chmod(0o600)


def sniff(path: Path) -> str:
    """Classify a loose evidence file by content."""
    with path.open("rb") as handle:
        head = handle.read(65536)
    if head.startswith(b"FLR\0") or path.suffix == ".jfr":
        return "jfr"
    text = head.decode("utf-8", "replace")
    if "A fatal error has been detected by the Java Runtime Environment" in text:
        return "crash"
    if "Full thread dump" in text:
        return "thread-dump"
    if text.lstrip().startswith("{") and '"threadDump"' in text:
        return "thread-dump-json"
    if re.search(r"^\s*num\s+#instances\s+#bytes", text, re.M):
        return "class-histogram"
    if "Native Memory Tracking:" in text:
        return "nmt"
    if re.search(r"^\[[^\]]*\]\[(?:[^\]]*\]\[)?(?:trace|debug|info|warning|error)\s*\]\[gc", text, re.M) or \
            re.search(r"\bGC\(\d+\) Pause", text):
        return "gc-log"
    lines = [line for line in text.splitlines()[:20] if line.strip()]
    if lines and all(re.fullmatch(r"\S.*;?.* \d+", line) for line in lines):
        return "collapsed"
    return "other"


def import_loose(src: Path, dest: Path) -> Path:
    """Arrange loose files into the bundle layout so the same analysis applies."""
    bundle = dest / f"jvmcap-loose-{re.sub(r'[^A-Za-z0-9._-]', '_', src.resolve().name)}"
    for sub in ("jvm", "logs", "crash", "other"):
        (bundle / sub).mkdir(mode=0o700, parents=True, exist_ok=True)
    counters: dict[str, int] = {}
    inventory = []
    total = 0
    for path in sorted(src.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if size > MAX_LOOSE_FILE or total > MAX_UNPACKED:
            raise SystemExit(f"loose input too large at {path}; refusing")
        kind = sniff(path)
        n = counters[kind] = counters.get(kind, 0) + 1
        target = {
            "jfr": bundle / "jvm" / f"{path.stem}.jfr",
            "thread-dump": bundle / "jvm" / f"thread-dump-{n:02d}.txt",
            "thread-dump-json": bundle / "jvm" / f"thread-dump-json-{n:02d}.json",
            "class-histogram": bundle / "jvm" / f"class-histogram-{n:02d}.txt",
            "nmt": bundle / "jvm" / f"nmt-{n:02d}.txt",
            "gc-log": bundle / "logs" / f"{n:02d}-{path.name}",
            "crash": bundle / "crash" / path.name,
            "collapsed": bundle / "jvm" / f"{path.stem}.collapsed",
        }.get(kind, bundle / "other" / path.name)
        if target.exists():
            target = target.with_name(f"{n:02d}-{target.name}")
        shutil.copyfile(path, target)
        target.chmod(0o600)
        inventory.append(f"{path.relative_to(src)} -> {kind}")
    (bundle / "MANIFEST.txt").write_text(
        "bundle_format=1\n"
        f"bundle={bundle.name}\n"
        "source=loose-files\n" + "".join(f"loose_file.{i}={line}\n" for i, line in enumerate(inventory)))
    return bundle


def verify_sums(bundle: Path) -> list[str]:
    problems = []
    sums = bundle / "SHA256SUMS"
    if not sums.is_file():
        return ["SHA256SUMS missing"]
    listed = set()
    for line in sums.read_text().splitlines():
        digest, _, name = line.partition("  ")
        name = name[2:] if name.startswith("./") else name
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


# ---------------------------------------------------------------------------
# Small parsers

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


def to_float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def load_tsv(path: Path) -> list[dict[str, str]]:
    lines = read(path).splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, cols)) for cols in (line.split("\t") for line in lines[1:]) if len(cols) == len(header)]


def pairs(bundle: Path, name: str) -> tuple[str, str]:
    return read(bundle / "proc-start" / name), read(bundle / "proc-end" / name)


def key_values(text: str) -> dict[str, int]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
            out[parts[0].rstrip(":")] = int(parts[1])
    return out


def psi_total(text: str) -> int | None:
    m = re.search(r"^some .*total=(\d+)", text, re.M)
    return int(m.group(1)) if m else None


def status_field(text: str, key: str) -> int | None:
    m = re.search(rf"^{key}:\s+(\d+)", text, re.M)
    return int(m.group(1)) if m else None


def proc_stat_ticks(text: str) -> int | None:
    rest = text.rpartition(")")[2].split()
    try:
        return int(rest[11]) + int(rest[12])
    except (IndexError, ValueError):
        return None


def cpu_lines(text: str) -> dict[str, list[int]]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].startswith("cpu"):
            out[parts[0]] = [int(v) for v in parts[1:9]]
    return out


def table_rows(text: str) -> list[tuple[str, float]]:
    """Rows of a `jfr view` table whose last column is a percentage."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"^(\S.*?)\s{2,}(?:[\d,]+\s+)?([\d.]+)%\s*$", line)
        if m:
            rows.append((m.group(1).strip(), float(m.group(2))))
    return rows


def collapsed_top(path: Path, limit: int = 15) -> tuple[int, list[tuple[str, float]]]:
    """Self (leaf) share per frame from collapsed stacks."""
    counts: dict[str, int] = {}
    total = 0
    for line in read(path).splitlines():
        stack, _, n = line.rpartition(" ")
        if not n.isdigit() or not stack:
            continue
        leaf = re.sub(r"_\[[^\]]*\]$", "", stack.rsplit(";", 1)[-1])
        counts[leaf] = counts.get(leaf, 0) + int(n)
        total += int(n)
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return total, [(frame, 100.0 * n / total) for frame, n in top] if total else []


def fmt_pct(value: float | None) -> str:
    return "?" if value is None else f"{value:.1f}%"


# ---------------------------------------------------------------------------
# Thread dumps

def parse_thread_dump(text: str) -> list[dict]:
    threads = []
    for block in re.split(r"\n(?=\")", text):
        header = re.match(r'"(?P<name>(?:[^"\\]|\\.)*)"(?P<rest>.*)', block)
        if not header:
            continue
        rest = header.group("rest")
        nid = None
        m = re.search(r"\bnid=(0x[0-9a-fA-F]+|\d+)", rest)
        if m:
            nid = str(int(m.group(1), 16) if m.group(1).startswith("0x") else int(m.group(1)))
        state = re.search(r"java\.lang\.Thread\.State: (\w+)", block)
        frames = re.findall(r"^\s+at (\S+)", block, re.M)
        threads.append({
            "name": header.group("name"), "nid": nid, "state": state.group(1) if state else None,
            "frames": [re.sub(r"\(.*$", "", f) for f in frames],
            "locked": re.findall(r"- locked <(0x[0-9a-f]+)>", block),
            "waiting_on": re.findall(r"- waiting to lock <(0x[0-9a-f]+)>", block),
        })
    return threads


def deadlock_text(text: str) -> str:
    m = re.search(r"^Found (?:one|\d+) Java-level deadlocks?:.*?(?=^Found \d+ deadlock|\Z)", text, re.M | re.S)
    return m.group(0).strip() if m else ""


def json_dump_summary(path: Path, platform_threads: int | None) -> dict:
    try:
        dump = json.loads(read(path))["threadDump"]
    except (ValueError, KeyError, TypeError):
        return {"error": "unreadable JSON thread dump"}
    total = 0
    flagged = 0
    has_flag = False
    tops: dict[str, int] = {}
    for container in dump.get("threadContainers", []):
        for thread in container.get("threads", []):
            total += 1
            if "virtual" in thread:
                has_flag = True
            if thread.get("virtual"):
                flagged += 1
                stack = thread.get("stack") or ["(no stack)"]
                frame = next((f for f in stack if not f.startswith("java.base/")), stack[0])
                tops[frame] = tops.get(frame, 0) + 1
    if has_flag:
        virtual, method = flagged, "reported by the JVM"
    elif platform_threads is not None:
        virtual, method = max(total - platform_threads, 0), "estimated: JSON threads minus the paired Thread.print"
    else:
        virtual, method = None, "unknown (JDK 21 JSON dumps do not mark virtual threads)"
    return {"runtime": dump.get("runtimeVersion"), "threads": total, "virtual": virtual, "virtual_method": method,
            "virtual_top_frames": sorted(tops.items(), key=lambda kv: -kv[1])[:5]}


# ---------------------------------------------------------------------------
# GC log events on the host-uptime axis

def gc_pause_events(logs: list[Path], jvm_start_host: float | None, wall_to_host) -> list[tuple[float, float, str]]:
    events = []
    for log in logs:
        for line in read(log).splitlines():
            m = re.search(r"(Pause.*?)\s(\d+(?:\.\d+)?)ms\s*$", line)
            if not m:
                continue
            host_t = None
            up = re.search(r"\[(\d+(?:\.\d+)?)s\]", line)
            if up and jvm_start_host is not None:
                host_t = float(up.group(1)) + jvm_start_host
            elif wall_to_host:
                wall = re.search(r"\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)([+-]\d{4}|Z)\]", line)
                if wall:
                    host_t = wall_to_host(wall.group(1), wall.group(2))
            if host_t is not None:
                events.append((host_t, float(m.group(2)), m.group(1)[:60]))
    return sorted(events)


def make_wall_to_host(bundle: Path):
    stamp = read(bundle / "proc-start/timestamp").strip()
    up = to_float(read(bundle / "proc-start/uptime_s").strip())
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z", stamp)
    if not m or up is None:
        return None
    base = datetime.strptime(m.group(1) + "+0000", "%Y-%m-%dT%H:%M:%S%z").timestamp() + float("0." + (m.group(2) or "0"))

    def convert(text: str, zone: str) -> float | None:
        whole, _, frac = text.partition(".")
        try:
            ts = datetime.strptime(whole + ("+0000" if zone == "Z" else zone), "%Y-%m-%dT%H:%M:%S%z").timestamp()
        except ValueError:
            return None
        return up + ts + float("0." + (frac or "0")) - base
    return convert


# ---------------------------------------------------------------------------
# Sections

def section_capture(r: Report, bundle: Path, manifest: dict, archive_sha: str | None, expected: bool,
                    problems: list[str], elapsed: float, loose: bool) -> None:
    md = r.md
    md += ["## Capture", ""]
    if loose:
        md.append("- Source: loose files (no collector manifest or checksums); classification:")
        md += [f"  - `{v}`" for k, v in manifest.items() if k.startswith("loose_file.")]
    else:
        if archive_sha:
            md.append(f"- Archive sha256: `{archive_sha}`" + (" (matches expected)" if expected else ""))
        md += [f"- Integrity: {'OK' if not problems else 'PROBLEMS: ' + '; '.join(problems[:5])}",
               f"- Host `{manifest.get('host', '?')}`, kernel `{manifest.get('kernel', '?')}`, "
               f"{manifest.get('logical_cpus', '?')} logical CPUs",
               f"- PID {manifest.get('pid', '?')}, window {manifest.get('duration_s', '?')} s "
               f"({manifest.get('started_utc', '?')} to {manifest.get('finished_utc', '?')}), measured {elapsed:.1f} s",
               f"- JFR mode `{manifest.get('jfr_mode', '?')}`, interrupted `{manifest.get('interrupted', '?')}`, "
               f"target alive at end `{manifest.get('target_alive_at_end', '?')}`"]
        if manifest.get("trigger_fired", "immediate") != "immediate":
            md.append(f"- Started by `{manifest['trigger_fired']}` after waiting {manifest.get('waited_s', '?')} s")
        if manifest.get("target_mount_ns") == "different":
            md.append("- Collected from another mount namespace (debug container or node)")
        if manifest.get("jcmd_source") == "async-profiler":
            md.append("- JVM diagnostics came through async-profiler's attach (no jcmd on the host)")
    version = next((line.strip() for line in read(bundle / "jvm/VM.version.txt").splitlines() if " version " in line), None)
    if version:
        md.append(f"- JVM: {version}")
    r.data["jvm_version"] = version
    failed = {k[5:]: v for k, v in manifest.items()
              if k.startswith("step.") and not (v == "ok" or v.startswith(("copied=", "rows=", "bytes=")))}
    if failed:
        md.append("- Steps not completed: " + ", ".join(f"`{k}`={v}" for k, v in failed.items()))
        for name, value in failed.items():
            if value.startswith(("failed", "timeout")):
                r.find("warn", f"collector step `{name}` did not complete: {value}; the evidence it would give is missing")
    if manifest.get("jvm_unresponsive") == "1":
        r.find("warn", "the JVM did not answer diagnostic commands (hung, stopped, or attach blocked); see thread states below",
               "java-performance-investigation")
    for key, value in manifest.items():
        if key.startswith("jfr_scrub.") and value not in ("ok",) and not value.startswith("source-disabled"):
            r.find("warn", f"JFR file {key[10:]} scrub status: {value}")
    if manifest.get("size_warning"):
        r.find("info", f"bundle contents ({manifest.get('content_bytes')} bytes) exceeded the --max-mb budget")
    if problems:
        r.find("warn", "bundle integrity problems: " + "; ".join(problems[:5]))
    md.append("")
    r.data["capture"] = {k: manifest.get(k) for k in (
        "bundle", "host", "kernel", "arch", "pid", "logical_cpus", "duration_s", "started_utc", "finished_utc",
        "trigger_fired", "waited_s", "jfr_mode", "jcmd_source", "target_mount_ns", "interrupted", "target_alive_at_end")}
    r.data["capture"].update({"elapsed_s": elapsed, "archive_sha256": archive_sha, "integrity_problems": problems,
                              "steps_not_completed": failed, "loose": loose})


def section_vendor(r: Report, bundle: Path) -> None:
    vendor_files = sorted((bundle / "vendor").rglob("*") if (bundle / "vendor").is_dir() else [])
    if not vendor_files:
        return
    r.md += ["## Vendor profiler artifacts", "",
             "These files were preserved and checksum-verified. Open them with the matching vendor tool; "
             "this analyser does not parse proprietary databases.", ""]
    for path in vendor_files:
        if path.is_file():
            r.md.append(f"- `{path.relative_to(bundle)}` ({path.stat().st_size} bytes, sha256 `{sha256(path)}`)")
    r.md.append("")
    r.next_skills.add("java-vtune-uprof")


def section_service_evidence(r: Report, bundle: Path) -> None:
    """Parse optional service files into the same findings/JSON output."""
    try:
        from service_evidence import analyse
    except ImportError:
        return
    result = analyse(bundle)
    if not any(result["files"].values()):
        return
    r.md += ["## Service evidence", "", "Optional systemd, journal, and coredump evidence was parsed locally.", ""]
    for finding in result["findings"]:
        r.md.append(f"- **{finding['severity']}** `{finding['kind']}`: {finding['detail']}")
        skill = {"oom": "java-native-memory", "crash": "java-offline-capture", "restart": "java-offline-capture"}.get(finding["kind"])
        if skill:
            r.next_skills.add(skill)
        r.find(finding["severity"], finding["detail"], skill or "java-performance-investigation")
    r.data["service_evidence"] = result
    r.md.append("")


def thread_deltas(bundle: Path, clk_tck: int, elapsed: float) -> list[dict]:
    start = {row["tid"]: row for row in load_tsv(bundle / "proc-start/threads.tsv")}
    out = []
    for e in load_tsv(bundle / "proc-end/threads.tsv"):
        s = start.get(e["tid"])
        if not s:
            continue

        def d(key: str) -> int:
            try:
                return int(e[key]) - int(s[key])
            except (ValueError, KeyError):
                return 0
        cpu_ticks = d("utime") + d("stime")
        out.append({
            "tid": e["tid"], "name": e["comm"],
            "cpu_pct": 100.0 * cpu_ticks / clk_tck / elapsed if elapsed else 0.0,
            "run_delay_ms": d("run_delay_ns") / 1e6,
            "nonvoluntary": d("nonvoluntary_ctxt"), "voluntary": d("voluntary_ctxt"),
            "last_cpu": e.get("processor", "?"), "state": e.get("state"), "wchan": e.get("wchan"),
        })
    return out


def section_process(r: Report, bundle: Path, clk_tck: int, elapsed: float, dumps: list[tuple[Path, list[dict]]]) -> None:
    md = r.md
    threads = thread_deltas(bundle, clk_tck, elapsed)
    s_status, e_status = pairs(bundle, "pid_status")
    rss_start, rss_end = status_field(s_status, "VmRSS"), status_field(e_status, "VmRSS")
    s_ticks, e_ticks = (proc_stat_ticks(t) for t in pairs(bundle, "pid_stat"))
    s_io, e_io = (key_values(t) for t in pairs(bundle, "pid_io"))
    proc = {}
    md += ["## Process", ""]
    if rss_start is not None and rss_end is not None:
        md.append(f"- RSS {rss_start // 1024} MiB → {rss_end // 1024} MiB ({(rss_end - rss_start) // 1024:+d} MiB over the window)")
        proc.update(rss_start_kib=rss_start, rss_end_kib=rss_end)
    if s_ticks is not None and e_ticks is not None and elapsed:
        proc["cpu_pct"] = 100.0 * (e_ticks - s_ticks) / clk_tck / elapsed
        md.append(f"- Process CPU {proc['cpu_pct']:.0f}% of one core (all threads, including ones that exited)")
    if s_io and e_io:
        read_mb = (e_io.get("read_bytes", 0) - s_io.get("read_bytes", 0)) / 1048576
        write_mb = (e_io.get("write_bytes", 0) - s_io.get("write_bytes", 0)) / 1048576
        proc.update(read_mib=read_mb, write_mib=write_mb)
        md.append(f"- Block I/O by the process: read {read_mb:.1f} MiB, write {write_mb:.1f} MiB")
    if threads:
        total_cpu = sum(t["cpu_pct"] for t in threads)
        md.append(f"- {len(threads)} threads alive throughout; their CPU {total_cpu:.0f}% of one core")
        md += ["", "| Thread (tid) | CPU % | Run-queue delay ms | Involuntary switches | Last CPU |", "| --- | ---: | ---: | ---: | ---: |"]
        for t in sorted(threads, key=lambda t: -t["cpu_pct"])[:10]:
            md.append(f"| {t['name']} ({t['tid']}) | {t['cpu_pct']:.1f} | {t['run_delay_ms']:.1f} | {t['nonvoluntary']} | {t['last_cpu']} |")
        worst_delay = max(threads, key=lambda t: t["run_delay_ms"])
        if elapsed and worst_delay["run_delay_ms"] > 0.01 * elapsed * 1000:
            r.find("warn", f"thread {worst_delay['name']} ({worst_delay['tid']}) waited {worst_delay['run_delay_ms']:.0f} ms "
                           f"for a CPU during {elapsed:.0f} s (run-queue delay >1% of the window)",
                   "linux-low-latency-tuning", "linux-ebpf-io-network")
        states: dict[str, int] = {}
        wchans: dict[str, int] = {}
        for t in threads:
            if t["state"]:
                states[t["state"]] = states.get(t["state"], 0) + 1
            if t["state"] == "D" and t["wchan"]:
                wchans[t["wchan"]] = wchans.get(t["wchan"], 0) + 1
        if states:
            md += ["", "- Kernel thread states at the end: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items()))
                   + " (R running, S sleeping, D uninterruptible I/O, T stopped)"]
            if states.get("D", 0):
                md.append("  - Uninterruptible (D) wait channels: " + ", ".join(f"`{k}` ×{v}" for k, v in wchans.items()))
                r.find("info", f"{states['D']} thread(s) in uninterruptible kernel wait (D) at the end of the window",
                       "linux-ebpf-io-network")
            if states.get("T", 0):
                r.find("warn", f"{states['T']} thread(s) stopped (T): the process was paused by a signal or debugger")
        proc["threads_alive"] = len(threads)
        proc["thread_states_end"] = states
    md.append("")
    hot_stacks(r, [t for t in sorted(threads, key=lambda t: -t["cpu_pct"]) if t["cpu_pct"] >= 5][:5], dumps)
    groups: dict[str, float] = {}
    for t in threads:
        key = re.sub(r"[#-]?\d+$", "#N", t["name"])
        groups[key] = groups.get(key, 0.0) + t["cpu_pct"]
    r.data["process"] = proc
    r.data["threads"] = sorted(threads, key=lambda t: -t["cpu_pct"])[:25]
    r.data["thread_groups_cpu_pct"] = dict(sorted(groups.items(), key=lambda kv: -kv[1]))


def hot_stacks(r: Report, hot: list[dict], dumps: list[tuple[Path, list[dict]]]) -> None:
    """Join the busiest OS threads to their Java stacks through the thread dumps' nid."""
    if not hot or not dumps:
        return
    md = r.md
    joined = []
    md += ["## Hot threads and their stacks", "",
           "The busiest threads by OS CPU time, matched to thread dumps by native id (nid).", ""]
    for t in hot:
        stacks = []
        for path, threads in dumps:
            match = next((th for th in threads if th["nid"] == t["tid"]), None)
            if match:
                stacks.append((path.name, match))
        if not stacks:
            continue
        name = stacks[0][1]["name"]
        md.append(f"- **{name}** (tid {t['tid']}, {t['cpu_pct']:.0f}% CPU)")
        tops = [tuple(m["frames"][:5]) for _, m in stacks]
        same = len(stacks) > 1 and len(set(tops)) == 1 and bool(tops[0])
        for dump_name, match in stacks[:3]:
            frames = match["frames"][:6] or ["(no Java frames: VM or native thread)"]
            md.append(f"  - `{dump_name}` {match['state'] or ''}: " + " ← ".join(f"`{f}`" for f in frames))
        if same:
            md.append("  - Same top frames in every dump: this thread is likely stuck in, or looping through, that code.")
        joined.append({"tid": t["tid"], "name": name, "cpu_pct": t["cpu_pct"], "same_top_frames": same,
                       "frames": list(tops[0]) if tops else []})
    md.append("")
    if joined:
        r.next_skills.add("java-async-profiler")
    r.data["hot_thread_stacks"] = joined


def section_host(r: Report, bundle: Path, manifest: dict, elapsed: float) -> None:
    md = r.md
    host: dict = {}
    md += ["## Host counters over the window", ""]
    s_cpu, e_cpu = (cpu_lines(t) for t in pairs(bundle, "stat"))
    if "cpu" in s_cpu and "cpu" in e_cpu:
        d = [b - a for a, b in zip(s_cpu["cpu"], e_cpu["cpu"])]
        total = sum(d)
        if total > 0:
            share = {name: 100.0 * v / total for name, v in zip(CPU_FIELDS, d)}
            host["cpu_pct"] = share
            md.append(f"- Host CPU: user {share['user'] + share['nice']:.1f}%, system {share['system']:.1f}%, "
                      f"iowait {share['iowait']:.1f}%, irq+softirq {share['irq'] + share['softirq']:.1f}%, "
                      f"steal {share['steal']:.1f}%, idle {share['idle']:.1f}%")
            if share["steal"] >= 5:
                r.find("warn", f"hypervisor steal was {share['steal']:.1f}% of host CPU time: the VM lost CPU to other tenants",
                       "linux-low-latency-tuning")
            elif share["steal"] >= 1:
                r.find("info", f"hypervisor steal {share['steal']:.1f}% of host CPU time", "linux-low-latency-tuning")
            if share["iowait"] >= 10:
                r.find("info", f"host iowait {share['iowait']:.1f}%: CPUs idle waiting for storage", "linux-ebpf-io-network")
        busy = {}
        for name, values in e_cpu.items():
            if name == "cpu" or name not in s_cpu:
                continue
            dd = [b - a for a, b in zip(s_cpu[name], values)]
            if sum(dd) > 0:
                busy[name[3:]] = 100.0 * (sum(dd) - dd[3] - dd[4]) / sum(dd)
        if busy:
            hot = sorted(busy.items(), key=lambda kv: -kv[1])
            host["busiest_cpus"] = hot[:8]
            md.append("- Busiest CPUs: " + ", ".join(f"cpu{c} {v:.0f}%" for c, v in hot[:6]))
            saturated = [c for c, v in hot if v >= 90]
            if saturated:
                r.find("info", f"CPU(s) {','.join(saturated[:8])} were at least 90% busy for the whole window")
    load = read(bundle / "proc-end/loadavg").split()
    cpus = to_float(manifest.get("logical_cpus", ""))
    if load and cpus:
        host["loadavg_1m"] = to_float(load[0])
        md.append(f"- Load average (1 min) at the end: {load[0]} on {int(cpus)} logical CPUs")
        if (host["loadavg_1m"] or 0) > cpus:
            r.find("info", f"1-minute load average {load[0]} exceeds {int(cpus)} logical CPUs (run queue backlog)",
                   "linux-low-latency-tuning")
    meminfo = key_values(read(bundle / "proc-end/meminfo"))
    if meminfo.get("MemTotal") and "MemAvailable" in meminfo:
        avail = 100.0 * meminfo["MemAvailable"] / meminfo["MemTotal"]
        host["mem_available_pct"] = avail
        md.append(f"- Memory available at the end: {avail:.1f}% of {meminfo['MemTotal'] // 1048576} GiB")
        if avail < 5:
            r.find("warn", f"only {avail:.1f}% of host memory was available: reclaim and OOM risk", "java-native-memory")
    irqs = interrupt_deltas(bundle)
    if irqs and elapsed:
        md.append("- Top interrupts/s: " + ", ".join(f"{n} {d / elapsed:.0f}/s{(' (' + desc[:30] + ')') if desc else ''}" for n, d, desc in irqs[:6]))
        host["top_interrupts_per_s"] = [(n, d / elapsed) for n, d, _ in irqs[:10]]
    soft = softirq_deltas(bundle)
    if soft and elapsed:
        md.append("- Softirqs/s: " + ", ".join(f"{n} {d / elapsed:.0f}" for n, d in soft[:5]))
        host["softirqs_per_s"] = {n: d / elapsed for n, d in soft}
    vm = vmstat_deltas(bundle)
    if vm:
        host["vmstat"] = vm
        md.append("- vmstat deltas: " + ", ".join(f"{k}={v}" for k, v in vm.items()))
        if vm.get("pswpin", 0) or vm.get("pswpout", 0):
            r.find("warn", f"swapping during the window (pswpin={vm.get('pswpin')}, pswpout={vm.get('pswpout')})",
                   "linux-low-latency-tuning")
        if vm.get("compact_stall", 0) or vm.get("allocstall_total", 0):
            r.find("info", f"memory reclaim/compaction stalls (compact_stall={vm.get('compact_stall', 0)}, "
                           f"allocstall={vm.get('allocstall_total', 0)})")
        if vm.get("pgmajfault", 0) > 100:
            r.find("info", f"{vm['pgmajfault']} major page faults host-wide")
    disks = disk_deltas(bundle, elapsed)
    if disks:
        host["disks"] = disks[:8]
        md.append("- Busiest block devices: " + ", ".join(
            f"{d['device']} util {d['util_pct']:.0f}% ({d['iops']:.0f} IO/s, {d['await_ms']:.1f} ms avg)" for d in disks[:4]))
        for d in disks:
            if d["util_pct"] >= 80:
                r.find("info", f"device {d['device']} was busy {d['util_pct']:.0f}% of the window "
                               f"(average I/O {d['await_ms']:.1f} ms)", "linux-ebpf-io-network")
    net = snmp_deltas(bundle)
    if net:
        host["network_errors"] = net
        md.append("- Network error deltas: " + ", ".join(f"{k}={v}" for k, v in net.items()))
        if net.get("Udp.RcvbufErrors", 0) > 0 or net.get("Udp.InErrors", 0) > 0:
            r.find("warn", f"UDP receive errors (RcvbufErrors={net.get('Udp.RcvbufErrors', 0)}, InErrors={net.get('Udp.InErrors', 0)})",
                   "linux-ebpf-io-network")
        if net.get("Tcp.RetransSegs", 0) > 0:
            r.find("info", f"TCP retransmitted segments: {net['Tcp.RetransSegs']}")
    psi = {}
    for kind in ("cpu", "io", "memory"):
        s, e = (psi_total(t) for t in pairs(bundle, f"pressure_{kind}"))
        if s is not None and e is not None and elapsed:
            psi[kind] = 100.0 * (e - s) / 1e6 / elapsed
    if psi:
        host["pressure_some_pct"] = psi
        md.append("- Pressure stall (some): " + ", ".join(f"{k} {v:.2f}%" for k, v in psi.items()))
        for kind, value in psi.items():
            if value > 5:
                r.find("warn", f"{kind} pressure: tasks stalled {value:.1f}% of the window")
    cgroup = section_cgroup(r, bundle, elapsed)
    audit = read(bundle / "host/audit.txt")
    audit_findings = [line.removeprefix("finding=") for line in audit.splitlines() if line.startswith("finding=")]
    if audit_findings:
        md += ["", "Host audit findings:", ""] + [f"- {f}" for f in audit_findings]
        if any(f.startswith("warn:cfs_throttled") for f in audit_findings) and "throttled_ms" not in cgroup:
            r.find("info", "the cgroup has been CPU-throttled at some point since it was created (no window delta available)")
        if any(f.startswith("warn:cfs_quota") for f in audit_findings):
            r.find("info", "the JVM runs under a CFS CPU quota: bursts above the quota are throttled", "linux-low-latency-tuning")
    readiness = kv_file(bundle / "host/readiness.txt")
    if readiness:
        md.append(f"- Readiness status on the source host: `{readiness.get('status', '?')}`")
    md.append("")
    host["audit_findings"] = audit_findings
    r.data["host"] = host


def section_cgroup(r: Report, bundle: Path, elapsed: float) -> dict:
    out: dict = {}
    s_cpu, e_cpu = (key_values(t) for t in pairs(bundle, "cgroup_cpu.stat"))
    if "nr_throttled" in s_cpu and "nr_throttled" in e_cpu:
        out["nr_throttled"] = e_cpu["nr_throttled"] - s_cpu["nr_throttled"]
        out["throttled_ms"] = (e_cpu.get("throttled_usec", 0) - s_cpu.get("throttled_usec", 0)) / 1000
        r.md.append(f"- cgroup CPU throttling in the window: {out['nr_throttled']} periods, {out['throttled_ms']:.0f} ms"
                    f" (cpu.max `{read(bundle / 'proc-end/cgroup_cpu.max').strip() or '?'}`)")
        if out["nr_throttled"] > 0:
            r.find("warn", f"cgroup CPU quota throttled the JVM {out['nr_throttled']} times "
                           f"({out['throttled_ms']:.0f} ms) during the window", "linux-low-latency-tuning")
    s_ev, e_ev = (key_values(t) for t in pairs(bundle, "cgroup_memory.events"))
    if e_ev:
        delta = {k: e_ev[k] - s_ev.get(k, 0) for k in e_ev}
        out["memory_events"] = delta
        current = read(bundle / "proc-end/cgroup_memory.current").strip()
        limit = read(bundle / "proc-end/cgroup_memory.max").strip()
        r.md.append(f"- cgroup memory {int(current) // 1048576 if current.isdigit() else '?'} MiB of "
                    f"{str(int(limit) // 1048576) + ' MiB' if limit.isdigit() else limit or '?'}; events in window: "
                    + ", ".join(f"{k}={v}" for k, v in delta.items()))
        if delta.get("oom_kill", 0) or delta.get("oom", 0):
            r.find("warn", f"cgroup OOM events during the window (oom={delta.get('oom', 0)}, oom_kill={delta.get('oom_kill', 0)})",
                   "java-native-memory")
        elif delta.get("max", 0) or delta.get("high", 0):
            r.find("info", f"cgroup memory hit its limit (max={delta.get('max', 0)}, high={delta.get('high', 0)}): reclaim stalls likely",
                   "java-native-memory")
    for kind in ("cpu", "io", "memory"):
        s, e = (psi_total(t) for t in pairs(bundle, f"cgroup_{kind}.pressure"))
        if s is not None and e is not None and elapsed:
            out.setdefault("pressure_some_pct", {})[kind] = 100.0 * (e - s) / 1e6 / elapsed
    if out.get("pressure_some_pct"):
        r.md.append("- cgroup pressure stall (some): " + ", ".join(f"{k} {v:.2f}%" for k, v in out["pressure_some_pct"].items()))
    r.data["cgroup"] = out
    return out


def interrupt_deltas(bundle: Path) -> list[tuple[str, int, str]]:
    def load(text: str) -> dict[str, tuple[int, str]]:
        lines = text.splitlines()
        if not lines:
            return {}
        ncpu = len(lines[0].split())
        rows = {}
        for line in lines[1:]:
            name, _, rest = line.partition(":")
            fields = rest.split()
            counts = [int(f) for f in fields[:ncpu] if f.isdigit()]
            rows[name.strip()] = (sum(counts), " ".join(fields[len(counts):]))
        return rows

    start, end = (load(t) for t in pairs(bundle, "interrupts"))
    deltas = [(k, v[0] - start[k][0], v[1]) for k, v in end.items() if k in start]
    return sorted(deltas, key=lambda t: -t[1])


def softirq_deltas(bundle: Path) -> list[tuple[str, int]]:
    def load(text: str) -> dict[str, int]:
        out = {}
        for line in text.splitlines()[1:]:
            name, _, rest = line.partition(":")
            out[name.strip()] = sum(int(f) for f in rest.split() if f.isdigit())
        return out

    start, end = (load(t) for t in pairs(bundle, "softirqs"))
    return sorted(((k, v - start[k]) for k, v in end.items() if k in start and v - start[k] > 0), key=lambda t: -t[1])


def vmstat_deltas(bundle: Path) -> dict[str, int]:
    start, end = (key_values(t) for t in pairs(bundle, "vmstat"))
    result = {k: end[k] - start[k] for k in VMSTAT_KEYS if k in end and k in start}
    if any(k.startswith("allocstall") for k in end):
        result["allocstall_total"] = sum(end[k] - start.get(k, 0) for k in end if k.startswith("allocstall"))
    return result


def disk_deltas(bundle: Path, elapsed: float) -> list[dict]:
    def load(text: str) -> dict[str, list[int]]:
        out = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 14 and not re.match(r"(loop|ram|zram)\d", parts[2]):
                out[parts[2]] = [int(v) for v in parts[3:14]]
        return out

    start, end = (load(t) for t in pairs(bundle, "diskstats"))
    rows = []
    for dev, e in end.items():
        s = start.get(dev)
        if not s or not elapsed:
            continue
        d = [b - a for a, b in zip(s, e)]
        ios = d[0] + d[4]
        if ios <= 0:
            continue
        rows.append({"device": dev, "iops": ios / elapsed, "util_pct": min(100.0, d[9] / (elapsed * 10)),
                     "await_ms": (d[3] + d[7]) / ios})
    return sorted(rows, key=lambda row: -row["util_pct"])


def snmp_deltas(bundle: Path) -> dict[str, int]:
    def load(*texts: str) -> dict[tuple[str, str], int]:
        out = {}
        for text in texts:
            lines = text.splitlines()
            for header, values in zip(lines[0::2], lines[1::2]):
                proto, _, names = header.partition(":")
                _, _, nums = values.partition(":")
                for name, num in zip(names.split(), nums.split()):
                    if num.lstrip("-").isdigit():
                        out[(proto, name)] = int(num)
        return out

    start = load(read(bundle / "proc-start/net_snmp"), read(bundle / "proc-start/net_netstat"))
    end = load(read(bundle / "proc-end/net_snmp"), read(bundle / "proc-end/net_netstat"))
    return {f"{p}.{n}": end[(p, n)] - start[(p, n)] for (p, n) in sorted(SNMP_KEYS) if (p, n) in end and (p, n) in start}


def section_timeseries(r: Report, bundle: Path, clk_tck: int, pauses: list[tuple[float, float, str]]) -> None:
    rows = load_tsv(bundle / "samples/host.tsv")
    if len(rows) < 2:
        return
    thread_rows = load_tsv(bundle / "samples/threads.tsv")
    by_time: dict[str, list[dict]] = {}
    for row in thread_rows:
        by_time.setdefault(row["uptime_s"], []).append(row)
    last: dict[str, int] = {}
    names: dict[str, str] = {}
    intervals = []
    for i, row in enumerate(rows):
        changed = by_time.get(row["uptime_s"], [])
        thread_delta: dict[str, int] = {}
        for t in changed:
            ticks = int(t["cpu_ticks"]) if t["cpu_ticks"].isdigit() else 0
            if i > 0:
                thread_delta[t["tid"]] = ticks - last.get(t["tid"], 0)
            last[t["tid"]] = ticks
            names[t["tid"]] = t["comm"]
        if i == 0:
            continue
        prev = rows[i - 1]
        t0, t1 = float(prev["uptime_s"]), float(row["uptime_s"])
        dt = t1 - t0
        if dt <= 0:
            continue

        def diff(key: str) -> float | None:
            a, b = to_float(prev.get(key, "")), to_float(row.get(key, ""))
            return None if a is None or b is None else b - a
        cpu_d = [diff("cpu_" + f) or 0 for f in CPU_FIELDS]
        cpu_total = sum(cpu_d)
        proc = (diff("proc_utime") or 0) + (diff("proc_stime") or 0)
        top_tid = max(thread_delta, key=thread_delta.get) if thread_delta else None
        interval = {
            "from_s": t0, "to_s": t1,
            "process_cpu_pct": 100.0 * proc / clk_tck / dt,
            "host_busy_pct": 100.0 * (cpu_total - cpu_d[3] - cpu_d[4]) / cpu_total if cpu_total else None,
            "steal_pct": 100.0 * cpu_d[7] / cpu_total if cpu_total else None,
            "iowait_pct": 100.0 * cpu_d[4] / cpu_total if cpu_total else None,
            "rss_mib": (to_float(row.get("rss_kb", "")) or 0) / 1024,
            "psi_cpu_pct": (diff("psi_cpu_some_us") or 0) / 1e4 / dt if row.get("psi_cpu_some_us") else None,
            "psi_io_pct": (diff("psi_io_some_us") or 0) / 1e4 / dt if row.get("psi_io_some_us") else None,
            "throttled_ms": (diff("cg_throttled_usec") or 0) / 1000 if row.get("cg_throttled_usec") else None,
            "top_thread": f"{names[top_tid]} ({top_tid}) {100.0 * thread_delta[top_tid] / clk_tck / dt:.0f}%" if top_tid else None,
            "gc_pause_ms": sum(ms for t, ms, _ in pauses if t0 < t <= t1),
            "gc_max_pause_ms": max((ms for t, ms, _ in pauses if t0 < t <= t1), default=0.0),
        }
        intervals.append(interval)
    if not intervals:
        return
    cpu_values = [iv["process_cpu_pct"] for iv in intervals]
    median = statistics.median(cpu_values)
    md = r.md
    md += ["## Time series", "",
           f"{len(intervals)} intervals of about {statistics.median(iv['to_s'] - iv['from_s'] for iv in intervals):.1f} s "
           f"(times are host uptime in seconds). Process CPU: min {min(cpu_values):.0f}%, median {median:.0f}%, "
           f"max {max(cpu_values):.0f}% of one core. RSS {min(iv['rss_mib'] for iv in intervals):.0f}–"
           f"{max(iv['rss_mib'] for iv in intervals):.0f} MiB.", "",
           "Busiest intervals:", "",
           "| Interval (s) | Process CPU | Busiest thread | Host busy | Steal | iowait | CPU pressure | Throttled ms | GC pause ms (max) |",
           "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for iv in sorted(intervals, key=lambda iv: -iv["process_cpu_pct"])[:5]:
        throttled_cell = "-" if iv["throttled_ms"] is None else f"{iv['throttled_ms']:.0f}"
        md.append(f"| {iv['from_s']:.1f}–{iv['to_s']:.1f} | {iv['process_cpu_pct']:.0f}% | {iv['top_thread'] or '-'} | "
                  f"{fmt_pct(iv['host_busy_pct'])} | {fmt_pct(iv['steal_pct'])} | {fmt_pct(iv['iowait_pct'])} | "
                  f"{fmt_pct(iv['psi_cpu_pct'])} | {throttled_cell} | "
                  f"{iv['gc_pause_ms']:.1f} ({iv['gc_max_pause_ms']:.1f}) |")
    gc_heavy = sorted((iv for iv in intervals if iv["gc_pause_ms"] > 0), key=lambda iv: -iv["gc_pause_ms"])[:3]
    if gc_heavy:
        md += ["", "Intervals with the most GC pause time: " + "; ".join(
            f"{iv['from_s']:.1f}–{iv['to_s']:.1f} s: {iv['gc_pause_ms']:.1f} ms (max {iv['gc_max_pause_ms']:.1f} ms)" for iv in gc_heavy)]
    md.append("")
    peak = max(intervals, key=lambda iv: iv["process_cpu_pct"])
    if peak["process_cpu_pct"] >= 50 and peak["process_cpu_pct"] >= 2 * max(median, 1):
        r.find("info", f"CPU burst: {peak['process_cpu_pct']:.0f}% at {peak['from_s']:.1f}–{peak['to_s']:.1f} s "
                       f"against a median of {median:.0f}% (busiest thread {peak['top_thread']})", "java-async-profiler")
    worst_steal = max(intervals, key=lambda iv: iv["steal_pct"] or 0)
    if (worst_steal["steal_pct"] or 0) >= 10:
        r.find("warn", f"steal reached {worst_steal['steal_pct']:.0f}% at {worst_steal['from_s']:.1f}–{worst_steal['to_s']:.1f} s",
               "linux-low-latency-tuning")
    throttled = [iv for iv in intervals if (iv["throttled_ms"] or 0) > 0]
    if throttled:
        r.find("info", f"cgroup throttling occurred in {len(throttled)} of {len(intervals)} intervals "
                       f"(worst {max(iv['throttled_ms'] for iv in throttled):.0f} ms)", "linux-low-latency-tuning")
    r.data["timeseries"] = {"intervals": intervals, "process_cpu_median_pct": median}


def section_gc(r: Report, bundle: Path, reports: Path, window: tuple[float, float] | None) -> None:
    md = r.md
    logs = sorted((bundle / "logs").glob("*")) if (bundle / "logs").is_dir() else []
    md += ["## GC and safepoints", ""]
    gc: dict = {}
    if logs and GC_SUMMARY.is_file():
        run_tool([sys.executable, str(GC_SUMMARY), *map(str, logs)], reports / "gc-summary-full.txt")
        out = read(reports / "gc-summary-full.txt")
        window_out = ""
        args = []
        if window:
            args = ["--from-uptime", f"{window[0]:.3f}", "--to-uptime", f"{window[1]:.3f}"]
            _, window_out = run_tool([sys.executable, str(GC_SUMMARY), *args, *map(str, logs)], reports / "gc-summary-window.txt")
        pick = (window_out or out).replace(str(bundle) + "/", "")
        rc, js = run_tool([sys.executable, str(GC_SUMMARY), "--json", *args, *map(str, logs)], reports / "gc-summary.json")
        if rc == 0:
            try:
                parsed = json.loads(js)
                gc = {k: parsed.get(k) for k in ("collectors", "pause_count", "pause_total_ms", "pause_fraction",
                                                 "pause_ms", "approx_allocation_mib_per_s", "safepoints", "alarms")}
            except ValueError:
                pass
        md += ["During the capture window" if window_out else "Whole log", "", "```text"]
        md += [line for line in pick.splitlines() if re.match(r"^(collectors|pauses_ms|pause_fraction|approx_allocation|time_to_safepoint_ms|safepoint_total_ms)", line)]
        worst = pick.split("worst_pauses:", 1)[-1].splitlines()[1:4] if "worst_pauses:" in pick else []
        md += ["worst pauses:", *worst]
        alarm_lines = pick.split("alarms:", 1)[-1].strip().splitlines() if "alarms:" in pick else []
        md += ["alarms: " + (", ".join(a.strip() for a in alarm_lines) or "none"), "```",
               "", "Full reports: `reports/gc-summary-full.txt`" + (", `reports/gc-summary-window.txt`" if window_out else "")]
        frac = re.search(r"^pause_fraction: ([\d.]+)%", pick, re.M)
        if frac and float(frac.group(1)) >= 5:
            r.find("warn", f"GC pauses took {float(frac.group(1)):.1f}% of wall time (high allocation or small heap)", "java-gc-tuning")
        ttsp = re.search(r"^time_to_safepoint_ms: .*max=([\d.]+)", pick, re.M)
        if ttsp and float(ttsp.group(1)) >= 10:
            r.find("info", f"time-to-safepoint reached {float(ttsp.group(1)):.1f} ms (threads slow to stop)", "java-jit-codegen")
        m = re.search(r"^pauses_ms: .*max=([\d.]+)", pick, re.M)
        if m and float(m.group(1)) >= 10:
            r.find("warn", f"GC pause up to {float(m.group(1)):.1f} ms in the {'window' if window_out else 'log'}", "java-gc-tuning")
        if any(a.strip().startswith(("full_gc", "evacuation_failure", "allocation_stall")) for a in alarm_lines):
            r.find("warn", "GC alarms: " + ", ".join(a.strip() for a in alarm_lines), "java-gc-tuning")
    elif logs:
        md.append(f"{len(logs)} log file(s) in `logs/`; install the `java-gc-tuning` skill to summarise them.")
    else:
        md.append("No GC logs in the bundle (the JVM was not started with `-Xlog:gc*`).")
    md.append("")
    r.data["gc"] = gc


def find_jfrconv(explicit: str | None) -> str | None:
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("jfrconv")
    home = os.environ.get("ASYNC_PROFILER_HOME")
    if not found and home and os.access(Path(home) / "bin/jfrconv", os.X_OK):
        found = str(Path(home) / "bin/jfrconv")
    return found if found and shutil.which("java") else None


def jfrconv_mode(name: str) -> str:
    for mode in ("alloc", "lock", "wall"):
        if f"asprof-{mode}" in name:
            return mode
    return "cpu"


def section_profiles(r: Report, bundle: Path, reports: Path, jfrconv: str | None) -> None:
    md = r.md
    md += ["## Profiles (JDK Flight Recorder and async-profiler)", ""]
    jfr_files = sorted((bundle / "jvm").glob("*.jfr")) if (bundle / "jvm").is_dir() else []
    collapsed_files = sorted((bundle / "jvm").glob("*.collapsed")) if (bundle / "jvm").is_dir() else []
    profiles: dict = {}
    collapsed_paths = [str(path.resolve()) for path in collapsed_files]
    if jfr_files and JFR_REPORT.is_file() and shutil.which("jfr"):
        for jfr in jfr_files:
            report_dir = reports / f"jfr-{jfr.stem}"
            rc, _ = run_tool(["bash", str(JFR_REPORT), str(jfr), str(report_dir)], reports / f"jfr-{jfr.stem}.log")
            if not report_dir.is_dir():
                md.append(f"- `{jfr.name}`: report failed (see `reports/jfr-{jfr.stem}.log`; the analysis JDK may be older than the recording JDK)")
                continue
            md.append(f"- `{jfr.name}` → `reports/jfr-{jfr.stem}/` ({len(list(report_dir.glob('*.txt')))} views"
                      f"{'' if rc == 0 else '; some views failed, see INDEX.txt'})")
            tables = {}
            for view in ("hot-methods", "allocation-by-site", "contention-by-site", "gc-pauses"):
                files = [f for f in report_dir.glob("*.txt") if re.fullmatch(rf"\d+-{view}\.txt", f.name)]
                if files:
                    text = read(files[0])
                    rows = [line for line in text.splitlines() if line.strip() and not set(line.strip()) <= set("-")][:8]
                    md += ["", f"`{view}`:", "", "```text", *rows, "```"]
                    if view in JFR_TABLE_VIEWS:
                        tables[view] = table_rows(text)[:30]
            profiles[jfr.name] = tables
            contention = list(report_dir.glob("*-contention-by-site.txt"))
            if contention and len([line for line in read(contention[0]).splitlines() if line.strip()]) > 3:
                r.next_skills.add("java-flight-recorder")
    elif jfr_files:
        md.append(f"{len(jfr_files)} recording(s) in `jvm/`; install a JDK (for `jfr`) and the `java-flight-recorder` skill to render reports.")
    for path in collapsed_files:
        total, top = collapsed_top(path)
        if not total:
            continue
        md += ["", f"`{path.name}` ({total} samples), top frames by self share:", "", "```text",
               *[f"{pct:6.2f}%  {frame}" for frame, pct in top[:10]], "```"]
        profiles[path.name] = {"self": top}
    if jfrconv:
        graphs = []
        for source in jfr_files + collapsed_files:
            mode = jfrconv_mode(source.name)
            html = reports / f"flamegraph-{source.stem}.html"
            args = [jfrconv] + ([] if source.suffix == ".collapsed" else [f"--{mode}"]) + [str(source), str(html)]
            rc, _ = run_tool(args, reports / f"flamegraph-{source.stem}.log")
            if rc == 0 and html.is_file():
                graphs.append(html.name)
            if source.suffix == ".jfr":
                coll = reports / f"{source.stem}-{mode}.collapsed"
                rc, _ = run_tool([jfrconv, f"--{mode}", "-o", "collapsed", str(source), str(coll)], reports / f"collapsed-{source.stem}.log")
                if rc == 0 and coll.is_file():
                    total, top = collapsed_top(coll)
                    if total:
                        profiles.setdefault(source.name, {})["self"] = top
                        collapsed_paths.append(str(coll.resolve()))
        if graphs:
            md += ["", "Flame graphs (open in a browser): " + ", ".join(f"`reports/{g}`" for g in graphs)]
    elif jfr_files or collapsed_files:
        md += ["", "Flame graphs: install async-profiler (its `jfrconv`) and a JDK, or pass `--jfrconv PATH`."]
    if not jfr_files and not collapsed_files:
        md.append("No JFR recording or profile (collector ran with `--jfr none`, or no jcmd on the source host).")
    md.append("")
    r.data["profiles"] = profiles
    r.data["collapsed_profiles"] = collapsed_paths


def section_nmt(r: Report, bundle: Path, reports: Path) -> None:
    md = r.md
    md += ["## Native memory", ""]
    nmt: dict = {}
    if (bundle / "jvm/nmt-start").is_dir() and (bundle / "jvm/nmt-end").is_dir() and NMT_COMPARE.is_file():
        _, out = run_tool([sys.executable, str(NMT_COMPARE), str(bundle / "jvm/nmt-start"), str(bundle / "jvm/nmt-end")], reports / "nmt-compare.txt")
        md += ["```text", *out.splitlines()[:14], "```"]
        m = re.search(r"^VmRSS_delta: ([+-]\d+)", out, re.M)
        if m:
            nmt["rss_delta_kib"] = int(m.group(1))
            if int(m.group(1)) > 256 * 1024:
                r.find("warn", f"RSS grew {int(m.group(1)) // 1024} MiB during the window", "java-native-memory")
    elif list((bundle / "jvm").glob("nmt-*.txt")) if (bundle / "jvm").is_dir() else False:
        md.append("NMT summaries were supplied as loose files; compare two of them with `nmt-compare.py` (the `java-native-memory` skill).")
    else:
        md.append("No NMT snapshots (start the JVM with `-XX:NativeMemoryTracking=summary` to include them).")
    md.append("")
    r.data["nmt"] = nmt


def histogram(text: str) -> dict[str, tuple[int, int]]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*\d+:\s+(\d+)\s+(\d+)\s+(\S+)", line)
        if m:
            out[m.group(3)] = (int(m.group(1)), int(m.group(2)))
    return out


def section_histograms(r: Report, bundle: Path) -> None:
    files = sorted((bundle / "jvm").glob("class-histogram-*.txt")) if (bundle / "jvm").is_dir() else []
    if len(files) < 2:
        if files:
            top = sorted(histogram(read(files[0])).items(), key=lambda kv: -kv[1][1])[:10]
            r.md += ["## Class histogram", "", "| Class | Instances | MiB |", "| --- | ---: | ---: |"]
            r.md += [f"| `{c}` | {n} | {b / 1048576:.1f} |" for c, (n, b) in top] + [""]
        return
    first, last = files[0], files[-1]
    if (bundle / "jvm/class-histogram-start.txt").is_file() and (bundle / "jvm/class-histogram-end.txt").is_file():
        first, last = bundle / "jvm/class-histogram-start.txt", bundle / "jvm/class-histogram-end.txt"
    start, end = histogram(read(first)), histogram(read(last))
    growth = sorted(((c, end[c][0] - start.get(c, (0, 0))[0], end[c][1] - start.get(c, (0, 0))[1]) for c in end),
                    key=lambda t: -t[2])[:10]
    total = sum(b for _, b in end.values()) - sum(b for _, b in start.values())
    r.md += ["## Class histogram growth", "",
             f"`{first.name}` → `{last.name}`: live+unreached heap objects changed by {total / 1048576:+.1f} MiB "
             "(histograms taken with `-all` include garbage not yet collected, so compare trends, not single values).", "",
             "| Class | Instances Δ | MiB Δ |", "| --- | ---: | ---: |"]
    r.md += [f"| `{c}` | {n:+d} | {b / 1048576:+.1f} |" for c, n, b in growth if b > 0] + [""]
    r.data["class_histogram_growth"] = [{"class": c, "instances": n, "bytes": b} for c, n, b in growth]


def section_thread_dumps(r: Report, bundle: Path, dumps: list[tuple[Path, list[dict]]]) -> None:
    json_dumps = sorted((bundle / "jvm").glob("thread-dump-*.json")) if (bundle / "jvm").is_dir() else []
    if not dumps and not json_dumps:
        return
    md = r.md
    md += ["## Thread dumps", ""]
    summary = []
    for path, threads in dumps:
        states: dict[str, int] = {}
        blocked: dict[str, int] = {}
        owners: dict[str, str] = {}
        waiters: dict[str, list[str]] = {}
        for t in threads:
            if t["state"]:
                states[t["state"]] = states.get(t["state"], 0) + 1
            if t["state"] == "BLOCKED" and t["frames"]:
                blocked[t["frames"][0]] = blocked.get(t["frames"][0], 0) + 1
            for lock in t["locked"]:
                owners[lock] = t["name"]
            for lock in t["waiting_on"]:
                waiters.setdefault(lock, []).append(t["name"])
        md.append(f"- `{path.name}`: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items())))
        if blocked:
            md.append("  - BLOCKED at: " + "; ".join(f"`{f}` ×{n}" for f, n in sorted(blocked.items(), key=lambda kv: -kv[1])[:5]))
            r.find("info", f"{path.name}: {states.get('BLOCKED', 0)} BLOCKED threads", "java-async-profiler", "java-flight-recorder")
        for lock, names in sorted(waiters.items(), key=lambda kv: -len(kv[1]))[:3]:
            owner = owners.get(lock, "unknown")
            owner_frames = next((t["frames"][:3] for t in threads if t["name"] == owner), [])
            md.append(f"  - Monitor `{lock}` held by **{owner}**"
                      + (f" (at {' ← '.join(f'`{f}`' for f in owner_frames)})" if owner_frames else "")
                      + f", wanted by {len(names)}: " + ", ".join(names[:5]))
        deadlock = deadlock_text(read(path))
        if deadlock:
            md += ["  - **Deadlock reported by the JVM:**", "", "```text", *deadlock.splitlines()[:30], "```"]
            r.find("warn", f"{path.name}: the JVM reports a Java-level deadlock", "java-performance-patterns")
        summary.append({"file": path.name, "states": states, "contended_monitors": {k: {"owner": owners.get(k), "waiters": v}
                                                                                   for k, v in waiters.items()},
                        "deadlock": bool(deadlock)})
    if len(dumps) > 1:
        stuck = []
        for t in dumps[0][1]:
            if t["state"] not in ("RUNNABLE", "BLOCKED") or not t["frames"] or t["frames"][0] in IDLE_FRAMES:
                continue
            top = t["frames"][:5]
            others = [next((o for o in threads if o["name"] == t["name"] and o["nid"] == t["nid"]), None) for _, threads in dumps[1:]]
            if all(o and o["frames"][:5] == top and o["state"] == t["state"] for o in others):
                stuck.append((t["name"], t["state"], top))
        if stuck:
            md.append(f"- Same {'RUNNABLE/BLOCKED'} stack in all {len(dumps)} dumps (possible stuck or spinning threads):")
            md += [f"  - **{n}** {s}: " + " ← ".join(f"`{f}`" for f in top[:4]) for n, s, top in stuck[:8]]
            r.find("info", f"{len(stuck)} thread(s) show the same busy or blocked stack in every dump", "java-async-profiler")
        r.data["stuck_threads"] = [{"name": n, "state": s, "frames": top} for n, s, top in stuck]
    platform = {p.stem: len(ts) for p, ts in dumps}
    for path in json_dumps:
        info = json_dump_summary(path, platform.get(path.stem))
        if "error" in info:
            md.append(f"- `{path.name}`: {info['error']}")
            continue
        md.append(f"- `{path.name}`: {info['threads']} threads, virtual threads: "
                  f"{'?' if info['virtual'] is None else info['virtual']} ({info['virtual_method']})")
        if info["virtual_top_frames"]:
            md.append("  - Virtual threads by first application frame: "
                      + "; ".join(f"`{f}` ×{n}" for f, n in info["virtual_top_frames"]))
        summary.append({"file": path.name, **info})
    md.append("")
    r.data["thread_dumps"] = summary


def section_crashes(r: Report, bundle: Path) -> None:
    files = sorted((bundle / "crash").glob("*")) if (bundle / "crash").is_dir() else []
    if not files:
        return
    md = r.md
    md += ["## JVM crash logs (hs_err)", ""]
    crashes = []
    for path in files:
        text = read(path)
        header = [line[1:].strip() for line in text.splitlines()[:40] if line.startswith("#")]
        error = next((h for h in header if re.match(r"(SIG[A-Z]+|EXCEPTION_|Internal Error|Out of Memory Error|"
                                                   r"There is insufficient memory|Native memory allocation)", h)), "")
        version = next((h for h in header if h.startswith("JRE version:")), "")
        frame = ""
        m = re.search(r"^# Problematic frame:\n#\s*(.+)$", text, re.M)
        if m:
            frame = m.group(1).strip()
        current = re.search(r"^Current thread \([^)]*\):\s*(.+)$", text, re.M)
        md.append(f"- `{path.name}`: {error or 'error line not found'}")
        if version:
            md.append(f"  - {version}")
        if frame:
            md.append(f"  - Problematic frame: `{frame}`")
        if current:
            md.append(f"  - Current thread: `{current.group(1).strip()[:120]}`")
        if "insufficient memory" in error or "Out of Memory" in error or "allocation" in error:
            r.find("warn", f"{path.name}: the JVM ran out of native memory", "java-native-memory")
        elif frame.startswith("J ") or frame.startswith("j "):
            r.find("warn", f"{path.name}: crash in Java or JIT-compiled code ({frame[:80]})", "java-jit-codegen")
        else:
            r.find("warn", f"{path.name}: JVM crash ({re.sub(r',? pid=.*', '', error)[:60]}; frame {frame[:60] or 'unknown'})")
        crashes.append({"file": path.name, "error": error, "jre_version": version, "problematic_frame": frame})
    md += ["", "Crash logs contain the command line and environment; they were read but these fields are not repeated here.", ""]
    r.data["crashes"] = crashes


def run_tool(cmd: list[str], out: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        out.write_text(f"# failed to run: {exc}\n")
        return 1, ""
    out.write_text(result.stdout + (("\n# stderr\n" + result.stderr) if result.stderr.strip() else ""))
    return result.returncode, result.stdout


# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="bundle .tar.gz, extracted bundle directory, or directory of loose files")
    parser.add_argument("output", type=Path, help="new directory for the extracted bundle, reports, ANALYSIS.md, and analysis.json")
    parser.add_argument("--expect-sha256", help="sha256 printed by collect.sh on the source host")
    parser.add_argument("--jfrconv", help="async-profiler jfrconv for flame graphs (default: PATH or ASYNC_PROFILER_HOME)")
    parser.add_argument("--json", action="store_true", help="also print analysis.json to stdout")
    args = parser.parse_args(argv)

    if args.output.exists():
        parser.error(f"{args.output} already exists")
    if not args.input.exists():
        parser.error(f"{args.input} does not exist")
    archive_sha = None
    loose = False
    if args.input.is_dir():
        if args.expect_sha256:
            parser.error("--expect-sha256 applies to an archive, not a directory")
        args.output.mkdir(mode=0o700)
        if (args.input / "MANIFEST.txt").is_file() and "bundle_format=" in read(args.input / "MANIFEST.txt"):
            bundle = args.output / args.input.resolve().name
            bundle.mkdir(mode=0o700)
            copy_tree(args.input, bundle)
        else:
            bundle = import_loose(args.input, args.output)
            loose = True
    else:
        archive_sha = sha256(args.input)
        if args.expect_sha256 and archive_sha != args.expect_sha256.lower():
            print(f"sha256 mismatch: got {archive_sha}, expected {args.expect_sha256}", file=sys.stderr)
            return 5
        bundle = safe_extract(args.input, args.output)
    manifest = kv_file(bundle / "MANIFEST.txt")
    if manifest.get("bundle_format", "1") not in SUPPORTED_FORMATS:
        print(f"unsupported bundle_format={manifest['bundle_format']}; use a newer analyze-bundle.py", file=sys.stderr)
        return 7
    problems = [] if loose else verify_sums(bundle)
    reports = args.output / "reports"
    reports.mkdir(mode=0o700)

    clk_tck = int(manifest.get("clk_tck", "100") or 100)
    up_start = to_float(read(bundle / "proc-start/uptime_s").strip())
    up_end = to_float(read(bundle / "proc-end/uptime_s").strip())
    elapsed = (up_end - up_start) if up_start is not None and up_end is not None else float(manifest.get("duration_s", "0") or 0)
    # JVM uptime on the host-uptime axis: process start (clock ticks since boot). Works without jcmd.
    start_ticks = to_float(manifest.get("target_start_ticks", ""))
    jvm_start_host = start_ticks / clk_tck if start_ticks is not None else None
    window = None
    if jvm_start_host is not None and up_start is not None and elapsed:
        window = (max(up_start - jvm_start_host, 0.0), up_start - jvm_start_host + elapsed)
    else:
        m = re.search(r"([\d.]+)\s*s", read(bundle / "jvm/VM.uptime.txt"))
        if m and elapsed:
            window = (float(m.group(1)), float(m.group(1)) + elapsed)

    dumps = [(p, parse_thread_dump(read(p))) for p in sorted((bundle / "jvm").glob("thread-dump-*.txt"))] \
        if (bundle / "jvm").is_dir() else []
    logs = sorted((bundle / "logs").glob("*")) if (bundle / "logs").is_dir() else []
    pauses = gc_pause_events(logs, jvm_start_host, make_wall_to_host(bundle))

    r = Report()
    section_capture(r, bundle, manifest, archive_sha, bool(args.expect_sha256), problems, elapsed, loose)
    section_crashes(r, bundle)
    section_vendor(r, bundle)
    section_service_evidence(r, bundle)
    if not loose:
        section_process(r, bundle, clk_tck, elapsed, dumps)
        section_timeseries(r, bundle, clk_tck, pauses)
        section_host(r, bundle, manifest, elapsed)
    section_gc(r, bundle, reports, None if loose else window)
    section_profiles(r, bundle, reports, find_jfrconv(args.jfrconv))
    section_nmt(r, bundle, reports)
    section_histograms(r, bundle)
    section_thread_dumps(r, bundle, dumps)

    title = [f"# Analysis of {manifest.get('bundle', args.input.name)}", ""]
    head = ["## Findings", ""]
    order = {"warn": 0, "info": 1}
    if r.findings:
        head += [f"- **{sev}**: {text}" for sev, text in sorted(r.findings, key=lambda f: order.get(f[0], 2))]
    else:
        head.append("- No automatic findings crossed their thresholds. Read the sections below against the stated problem.")
    head += ["", "Automatic findings are prompts for investigation, not conclusions. Compare with a baseline capture "
             "from a healthy period on the same host when possible (`compare-bundles.py`).", ""]
    head += ["## Suggested next skills", ""]
    head += [f"- `{s}`" for s in sorted(r.next_skills)] or ["- `java-performance-investigation` to decide the next step"]
    head.append("")
    analysis = args.output / "ANALYSIS.md"
    analysis.write_text("\n".join(title + head + r.md) + "\n")
    r.data.update({
        "analysis_format": 1,
        "bundle_dir": str(bundle),
        "findings": [{"severity": s, "text": t} for s, t in sorted(r.findings, key=lambda f: order.get(f[0], 2))],
        "next_skills": sorted(r.next_skills),
    })
    json_path = args.output / "analysis.json"
    json_path.write_text(json.dumps(r.data, indent=2, default=str) + "\n")
    if args.json:
        print(json_path.read_text(), end="")
    else:
        print(f"analysis={analysis}")
        print(f"json={json_path}")
        print(f"bundle_dir={bundle}")
        print(f"integrity={'not-applicable' if loose else 'ok' if not problems else 'problems'} findings={len(r.findings)}")
    return 0 if not problems else 6


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
