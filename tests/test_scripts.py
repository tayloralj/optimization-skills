#!/usr/bin/env python3
"""Tests for the Python helpers and the bundled validator. Standard library only."""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
GC = REPO / "skills/java-gc-tuning/scripts/gc-log-summary.py"
JIT = REPO / "skills/java-jit-codegen/scripts/jit-log-summary.py"
NMT = REPO / "skills/java-native-memory/scripts/nmt-compare.py"
LAT = REPO / "skills/java-latency-measurement/scripts/latency-report.py"
ALLOC = REPO / "skills/java-flight-recorder/scripts/jfr-alloc-stacks.py"
VALIDATOR = REPO / "scripts/validate_skills.py"
PLAN = REPO / "skills/linux-low-latency-tuning/scripts/make-lab-plan.py"


def run(*args: object, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} exited {result.returncode}: {result.stderr}")
    return result


def run_json(*args: object) -> dict:
    return json.loads(run(*args, "--json").stdout)


class GcLogSummaryTest(unittest.TestCase):
    def test_g1_pauses_match_safepoints(self):
        s = run_json(GC, FIXTURES / "g1-jdk25.log")
        self.assertEqual(s["collectors"], ["G1"])
        self.assertEqual(s["pause_count"], 26)
        self.assertEqual(s["safepoints"]["total_ms"]["count"], 26)
        self.assertIn("Pause Young (Normal) (G1 Evacuation Pause)", s["pauses_by_type_ms"])
        self.assertGreater(s["approx_allocation_mib_per_s"], 0)
        self.assertEqual(s["alarms"], {})

    def test_generational_zgc_phases(self):
        s = run_json(GC, FIXTURES / "zgc-jdk25.log")
        self.assertEqual(s["pause_count"], 38)
        self.assertEqual(s["safepoints"]["total_ms"]["count"], 38)
        labels = set(s["pauses_by_type_ms"])
        self.assertTrue(any(label.startswith("y: ") for label in labels), labels)
        self.assertTrue(any(label.startswith("O: ") for label in labels), labels)
        self.assertEqual(s["collections"].get("Major Collection (Warmup)"), 3)
        self.assertNotIn("allocation_stall", s["alarms"])
        self.assertLess(s["pause_ms"]["max"], 1.0)

    def test_alarms_and_legacy_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "legacy.log"
            log.write_text(
                "[1.000s][info][gc] Using Shenandoah\n"
                "[1.100s][info][gc] GC(3) Allocation Stall (main) 12.5ms\n"
                "[1.200s][info][gc] GC(4) Pause Full (System.gc()) 100M->20M(512M) 45.1ms\n"
                "[1.300s][info][gc] GC(5) Pause Young (Normal) (G1 Humongous Allocation) 64M->30M(512M) 3.0ms\n"
                "[1.400s][info][gc] GC(6) Pause Degenerated GC (Mark) 400M->300M(512M) 30.0ms\n"
                # JDK 17/21 safepoint format has Cleanup and no Leaving field.
                '[1.500s][info][safepoint] Safepoint "Cleanup", Time since last: 1000 ns, '
                "Reaching safepoint: 2500000 ns, Cleanup: 10 ns, At safepoint: 300 ns, Total: 2500310 ns\n"
            )
            s = run_json(GC, log)
        self.assertEqual(s["pause_count"], 3)
        for alarm in ("allocation_stall", "full_gc", "system_gc", "humongous_allocation", "degenerated_gc"):
            self.assertEqual(s["alarms"].get(alarm), 1, alarm)
        self.assertAlmostEqual(s["safepoints"]["time_to_safepoint_ms"]["max"], 2.5)

    def test_uptime_window_excludes_warmup(self):
        s = run_json(GC, FIXTURES / "g1-jdk25.log", "--from-uptime", "0.5")
        self.assertLess(s["pause_count"], 26)
        self.assertTrue(all(p["uptime_s"] >= 0.5 for p in s["worst_pauses"]))

    def test_zero_pauses_is_success(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log") as handle:
            handle.write("[0.003s][info][gc] Using G1\n[0.004s][info][gc,init] Version: 25\n")
            handle.flush()
            result = run(GC, handle.name, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no pauses in this window", result.stdout)

    def test_unrecognised_input_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log") as handle:
            handle.write("hello\n")
            handle.flush()
            self.assertEqual(run(GC, handle.name, check=False).returncode, 4)


class JitLogSummaryTest(unittest.TestCase):
    def test_fixture_summary(self):
        s = run_json(JIT, FIXTURES / "jit-jdk25.txt", "--warmup-ms", "1000")
        self.assertGreater(s["compiles_by_tier"]["tier4"], 0)
        self.assertIn("not used", s["made_not_entrant_by_reason"])
        self.assertIn("uncommon trap", s["made_not_entrant_by_reason"])
        self.assertIn("callee is too large", s["inline_failures"])
        for bogus in ("(intrinsic)", "accessor", "force inline by annotation", "inline24"):
            self.assertNotIn(bogus, s["inline_failures"])
        self.assertGreater(s["inline_outcomes"]["intrinsic"], 0)
        self.assertGreaterEqual(s["late_compiles"]["count"], 1)

    def test_code_cache_full(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as handle:
            handle.write("  100   12       4       Foo::bar (40 bytes)\n")
            handle.write("CodeCache is full. Compiler has been disabled.\n")
            handle.flush()
            s = run_json(JIT, handle.name)
        self.assertEqual(s["code_cache_full_events"], 1)


class NmtCompareTest(unittest.TestCase):
    def test_before_after(self):
        s = run_json(NMT, FIXTURES / "nmt-before", FIXTURES / "nmt-after")
        self.assertTrue(s["nmt_enabled"])
        self.assertEqual(s["VmRSS_delta"], 35000)
        heap = next(r for r in s["categories"] if r["category"] == "Java Heap")
        self.assertEqual(heap["delta_kb"], -4096)
        self.assertEqual(s["anon_rss_minus_nmt_delta_kb"], 34000 - s["nmt_committed_delta_kb"])

    def test_disabled_nmt_still_reports_rss(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a", "b"):
                d = Path(tmp) / name
                d.mkdir()
                (d / "nmt-summary.txt").write_text("123:\nNative memory tracking is not enabled\n")
                shutil.copy(FIXTURES / f"nmt-{'before' if name == 'a' else 'after'}" / "proc-status.txt", d)
            out = run(NMT, Path(tmp) / "a", Path(tmp) / "b").stdout
        self.assertIn("NMT disabled", out)
        self.assertIn("VmRSS_delta: +35000 kB", out)


def write_latency_csv(path: Path, stall: bool, n: int = 3000) -> None:
    rng = random.Random(11)
    free = 0
    rows = ["intended_start_ns,actual_start_ns,end_ns"]
    for i in range(n):
        intended = i * 1_000_000
        start = max(intended, free)
        if stall and 1_500_000_000 <= intended and start < 1_600_000_000:
            start = max(start, 1_600_000_000)
        end = start + 200_000 + rng.randint(0, 50_000)
        free = end
        rows.append(f"{intended},{start},{end}")
    path.write_text("\n".join(rows) + "\n")


class LatencyReportTest(unittest.TestCase):
    def test_coordinated_omission_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            stall, base = Path(tmp) / "stall.csv", Path(tmp) / "base.csv"
            write_latency_csv(stall, True)
            write_latency_csv(base, False)
            report = json.loads(run(LAT, stall, "--baseline", base, "--json").stdout)
            text = run(LAT, stall, "--baseline", base).stdout
        cand = report["candidate"]
        self.assertLess(cand["service_ns"]["p99"], 300_000)
        self.assertGreater(cand["response_ns"]["p99"], 10_000_000)
        self.assertGreater(cand["co_ratio_p99"], 10)
        self.assertEqual(set(cand["co_ratios"]), {"p99", "p99.9", "p99.99"})
        self.assertAlmostEqual(cand["intended_rate_per_s"], 1000.0, delta=1)
        self.assertLess(report["baseline"]["co_ratio_p99"], 1.5)
        self.assertIn("episodic stall", text)

    def test_episode_groups_and_completeness_gate(self):
        # Synthetic recovery episodes: fault observable at i, detected 20 us later,
        # recovered after a size-dependent repair time.
        rows = ["intended_start_ns,actual_start_ns,end_ns,group"]
        for i in range(300):
            size = (1, 10, 1000)[i % 3]
            start = i * 1_000_000_000
            rows.append(f"{start},{start + 20_000},{start + 20_000 + size * 1_000},{size}")
        with tempfile.NamedTemporaryFile("w", suffix=".csv") as handle:
            handle.write("\n".join(rows) + "\n")
            handle.flush()
            report = json.loads(run(LAT, handle.name, "--episodes", "--expected", 300, "--json").stdout)
            text = run(LAT, handle.name, "--episodes").stdout
            short = run(LAT, handle.name, "--episodes", "--expected", 400, check=False)
        cand = report["candidate"]
        self.assertTrue(report["valid"])
        self.assertNotIn("intended_rate_per_s", cand)
        self.assertEqual(list(cand["groups"]), ["1", "10", "1000"])
        self.assertEqual(cand["groups"]["1000"]["p50"], 1_020_000)
        self.assertEqual(cand["queue_delay_ns"]["max"], 20_000)
        self.assertIn("episode mode", text)
        self.assertIn("group 1000", text)
        self.assertEqual(short.returncode, 5)
        self.assertIn("INVALID: only 300 of 400", short.stdout)

    def test_rejects_partial_group_labels(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv") as handle:
            handle.write("intended_start_ns,actual_start_ns,end_ns,group\n1,2,3,a\n4,5,6\n")
            handle.flush()
            result = run(LAT, handle.name, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("group label missing", result.stderr)
        with tempfile.NamedTemporaryFile("w", suffix=".csv") as handle:
            handle.write("1,2,3,a\n")
            handle.flush()
            headerless = run(LAT, handle.name, check=False)
        self.assertNotEqual(headerless.returncode, 0)
        self.assertIn("need the header", headerless.stderr)

    def test_single_column(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv") as handle:
            handle.write("latency_ns\n" + "\n".join(str(1000 + i) for i in range(1000)) + "\n")
            handle.flush()
            out = run(LAT, handle.name).stdout
        self.assertIn("cannot reveal coordinated omission", out)


class JfrAllocStacksTest(unittest.TestCase):
    # Trimmed real `jfr print --json` output (JDK 25) from a sequencer client probe:
    # only the fields the script reads are kept.
    FIXTURE = FIXTURES / "jfr-alloc-samples.json"

    def test_groups_by_thread_and_stack(self):
        report = run_json(ALLOC, self.FIXTURE, "--depth", "3")
        self.assertEqual(report["events"], 23)
        rows = {tuple(r["stack"]): r for r in report["rows"]}
        tracker = rows[("SequenceTracker$GapResult.none", "SequenceTracker.onSequence",
                        "SequencerClient.handleSequenced")]
        self.assertEqual(tracker["thread"], "main")
        self.assertEqual(tracker["samples"], 6)
        self.assertEqual(tracker["top_class"], "com.sequencer.client.SequenceTracker$GapResult")
        self.assertAlmostEqual(sum(r["share"] for r in report["rows"]), 1.0, places=6)
        text = run(ALLOC, self.FIXTURE, "--depth", "1").stdout
        self.assertIn("HashMap$KeySet.iterator", text)

    def test_thread_filter_and_bad_arguments(self):
        none = run(ALLOC, self.FIXTURE, "--thread", "^no-such-thread$", check=False)
        self.assertEqual(none.returncode, 3)
        self.assertIn("no jdk.ObjectAllocationSample samples", none.stderr)
        bad = run(ALLOC, self.FIXTURE, "--thread", "(", check=False)
        self.assertEqual(bad.returncode, 2)
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            handle.write('{"not": "jfr"}')
            handle.flush()
            wrong = run(ALLOC, handle.name, check=False)
        self.assertNotEqual(wrong.returncode, 0)


@unittest.skipUnless(shutil.which("java"), "java not installed")
class TcpDelayProxyTest(unittest.TestCase):
    PROXY = REPO / "skills/java-latency-measurement/scripts/TcpDelayProxy.java"

    def test_adds_round_trip_delay(self):
        import socket
        import threading
        import time
        server = socket.create_server(("127.0.0.1", 0))
        port = server.getsockname()[1]

        def echo():
            conn, _ = server.accept()
            with conn:
                while data := conn.recv(4096):
                    conn.sendall(data)

        threading.Thread(target=echo, daemon=True).start()
        proc = subprocess.Popen(["java", str(self.PROXY), "--target", f"127.0.0.1:{port}",
                                 "--delay-ms", "5", "--duration", "30"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            first = proc.stdout.readline()
            self.assertTrue(first.startswith("listening 127.0.0.1:"), first)
            proxy_port = int(first.split()[1].rsplit(":", 1)[1])
            with socket.create_connection(("127.0.0.1", proxy_port)) as sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                rtts = []
                for _ in range(5):
                    started = time.monotonic()
                    sock.sendall(b"ping")
                    self.assertEqual(sock.recv(16), b"ping")
                    rtts.append(time.monotonic() - started)
            self.assertGreaterEqual(min(rtts), 0.0095)
            self.assertLess(max(rtts), 1.0)
        finally:
            proc.kill()
            proc.communicate()
            server.close()

    def test_refuses_non_loopback_and_missing_target(self):
        missing = subprocess.run(["java", str(self.PROXY), "--delay-ms", "1"], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--target", missing.stderr)
        exposed = subprocess.run(["java", str(self.PROXY), "--target", "127.0.0.1:1", "--delay-ms", "1",
                                  "--listen", "0.0.0.0:0"], capture_output=True, text=True)
        self.assertEqual(exposed.returncode, 2)
        self.assertIn("non-loopback", exposed.stderr)


class MakeLabPlanTest(unittest.TestCase):
    def fake_host(self, tmp: str) -> Path:
        root = Path(tmp)
        files = {
            "sys/devices/system/cpu/online": "0-7",
            "sys/devices/system/cpu/cpu2/cpufreq/scaling_governor": "powersave",
            "sys/devices/system/cpu/cpu3/cpufreq/scaling_governor": "performance",
            "sys/devices/system/cpu/cpu2/cpuidle/state1/latency": "2",
            "sys/devices/system/cpu/cpu2/cpuidle/state1/disable": "0",
            "sys/devices/system/cpu/cpu2/cpuidle/state3/latency": "350",
            "sys/devices/system/cpu/cpu2/cpuidle/state3/name": "C3",
            "sys/devices/system/cpu/cpu2/cpuidle/state3/disable": "0",
            "sys/kernel/mm/transparent_hugepage/enabled": "[always] madvise never",
            "sys/kernel/mm/transparent_hugepage/defrag": "always defer [madvise] never",
            "proc/sys/kernel/numa_balancing": "1",
            "proc/sys/kernel/timer_migration": "0",
            "proc/sys/vm/stat_interval": "1",
            "proc/irq/9/smp_affinity_list": "0-7",
            "proc/irq/10/smp_affinity_list": "0-1",
            "sys/devices/virtual/workqueue/cpumask": "ff",
            "proc/sys/kernel/watchdog_cpumask": "0-7",
            "proc/sys/kernel/nmi_watchdog": "1",
        }
        for rel, value in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value + "\n")
        return root

    def plan(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(PLAN), *args], capture_output=True, text=True,
                              env={**os.environ, "HOST_ROOT": str(root)})

    def test_benchmark_host_emits_only_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.plan(self.fake_host(tmp), "benchmark-host", "--cpus", "2-3").stdout
        sets = [line for line in out.splitlines() if line.startswith("set ")]
        self.assertIn("set /sys/devices/system/cpu/cpu2/cpufreq/scaling_governor performance", sets)
        self.assertIn("set /sys/devices/system/cpu/cpu2/cpuidle/state3/disable 1", sets)
        self.assertIn("set /sys/kernel/mm/transparent_hugepage/enabled madvise", sets)
        self.assertIn("set /proc/sys/kernel/numa_balancing 0", sets)
        self.assertIn("set /proc/sys/vm/stat_interval 10", sets)
        joined = "\n".join(sets)
        self.assertNotIn("cpu3/cpufreq/scaling_governor", joined)   # already performance
        self.assertNotIn("state1/disable", joined)                  # shallow state kept
        self.assertNotIn("energy_performance_preference", joined)   # EPP never planned
        self.assertNotIn("transparent_hugepage/defrag", joined)     # already madvise
        self.assertNotIn("timer_migration", joined)                 # already 0

    def test_irq_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.plan(self.fake_host(tmp), "irq-isolation", "--cpus", "2-7", "--housekeeping", "0-1").stdout
        self.assertIn("set /proc/irq/9/smp_affinity_list 0-1", out)
        self.assertNotIn("/proc/irq/10/", out.replace("#   skipped", ""))
        self.assertIn("set /sys/devices/virtual/workqueue/cpumask 3", out)
        self.assertIn("set /proc/sys/kernel/watchdog_cpumask 0-1", out)

    def test_rejects_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fake_host(tmp)
            self.assertNotEqual(self.plan(root, "irq-isolation", "--cpus", "2-3").returncode, 0)
            self.assertNotEqual(self.plan(root, "benchmark-host", "--cpus", "2-3", "--housekeeping", "3").returncode, 0)
            self.assertNotEqual(self.plan(root, "benchmark-host", "--cpus", "12").returncode, 0)
            self.assertNotEqual(self.plan(root, "benchmark-host", "--cpus", "2;rm").returncode, 0)

    def test_plans_pass_lab_tune_validation(self):
        lab = REPO / "skills/linux-low-latency-tuning/scripts/lab-tune.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = self.fake_host(tmp)
            for args in (["benchmark-host", "--cpus", "2-3"], ["irq-isolation", "--cpus", "2-7", "--housekeeping", "0-1"],
                         ["quiet-watchdogs", "--cpus", "2-7", "--housekeeping", "0-1"]):
                plan_file = Path(tmp) / "plan.txt"
                plan_file.write_text(self.plan(root, *args).stdout)
                result = subprocess.run([str(lab), "plan", str(plan_file)], capture_output=True, text=True,
                                        env={**os.environ, "LAB_TUNE_TEST_ROOT": str(root)})
                self.assertEqual(result.returncode, 0, f"{args}: {result.stderr}")

    def test_hexmask(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_lab_plan", PLAN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.hexmask([0, 1, 12, 13]), "3003")
        self.assertEqual(module.hexmask(list(range(40))), "ff,ffffffff")
        self.assertEqual(module.hexmask([33]), "2,00000000")
        self.assertEqual(module.compact([0, 1, 2, 5, 7, 8]), "0-2,5,7-8")


ANALYZE = REPO / "skills/java-offline-capture/scripts/analyze-bundle.py"


def make_archive(path: Path, entries: dict, links: dict | None = None, top: str = "jvmcap-h-1-20260101T000000Z") -> None:
    import io
    import tarfile
    with tarfile.open(path, "w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name if name.startswith(("/", "..")) else f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(f"{top}/{name}")
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)


def minimal_bundle(tamper: bool = False, vendor: bool = False) -> dict:
    import hashlib
    files = {
        "MANIFEST.txt": b"bundle_format=1\nbundle=jvmcap-h-1-20260101T000000Z\npid=1\nduration_s=10\nclk_tck=100\nstep.proc-start=ok\n",
        "proc-start/uptime_s": b"100.0\n",
        "proc-end/uptime_s": b"110.0\n",
        "proc-start/threads.tsv": b"tid\tcomm\tutime\tstime\tvoluntary_ctxt\tnonvoluntary_ctxt\trun_delay_ns\tprocessor\n7\tworker\t100\t0\t1\t1\t0\t2\n",
        "proc-end/threads.tsv": b"tid\tcomm\tutime\tstime\tvoluntary_ctxt\tnonvoluntary_ctxt\trun_delay_ns\tprocessor\n7\tworker\t600\t0\t5\t90\t900000000\t2\n",
        "proc-start/vmstat": b"pswpin 0\npswpout 10\n",
        "proc-end/vmstat": b"pswpin 5\npswpout 50\n",
        "proc-start/net_snmp": b"Udp: InDatagrams InErrors RcvbufErrors\nUdp: 10 0 0\n",
        "proc-end/net_snmp": b"Udp: InDatagrams InErrors RcvbufErrors\nUdp: 90 7 7\n",
    }
    if vendor:
        files["vendor/vtune-report.txt"] = b"VendorWorkload.chaseBatch\n"
    sums = "".join(f"{hashlib.sha256(v).hexdigest()}  ./{k}\n" for k, v in sorted(files.items()))
    files["SHA256SUMS"] = sums.encode()
    if tamper:
        files["proc-end/vmstat"] = b"pswpin 0\npswpout 10\n"
    return files


class AnalyzeBundleTest(unittest.TestCase):
    def analyze(self, archive: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ANALYZE), str(archive), str(out), *extra], capture_output=True, text=True)

    def test_findings_from_proc_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "b.tar.gz"
            make_archive(archive, minimal_bundle())
            result = self.analyze(archive, Path(tmp) / "out")
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (Path(tmp) / "out" / "ANALYSIS.md").read_text()
        self.assertIn("Integrity: OK", text)
        self.assertIn("| worker (7) | 50.0 | 900.0 | 89 | 2 |", text)   # 500 ticks = 5 s CPU in 10 s; 0.9 s delay
        self.assertIn("swapping during the window", text)
        self.assertIn("UDP receive errors (RcvbufErrors=7", text)
        self.assertIn("waited 900 ms for a CPU", text)
        self.assertIn("`linux-ebpf-io-network`", text)

    def test_tampered_bundle_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "b.tar.gz"
            make_archive(archive, minimal_bundle(tamper=True))
            result = self.analyze(archive, Path(tmp) / "out")
            text = (Path(tmp) / "out" / "ANALYSIS.md").read_text()
        self.assertEqual(result.returncode, 6)
        self.assertIn("checksum mismatch proc-end/vmstat", text)

    def test_vendor_artifacts_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "b.tar.gz"
            make_archive(archive, minimal_bundle(vendor=True))
            result = self.analyze(archive, Path(tmp) / "out")
            text = (Path(tmp) / "out" / "ANALYSIS.md").read_text()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Vendor profiler artifacts", text)
        self.assertIn("vendor/vtune-report.txt", text)
        self.assertIn("`java-vtune-uprof`", text)

    def test_expected_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "b.tar.gz"
            make_archive(archive, minimal_bundle())
            result = self.analyze(archive, Path(tmp) / "out", "--expect-sha256", "0" * 64)
            self.assertEqual(result.returncode, 5)
            self.assertFalse((Path(tmp) / "out").exists())

    def test_rejects_unsafe_archives(self):
        cases = {
            "traversal": ({"../escape.txt": b"x"}, None, "jvmcap-a"),
            "absolute": ({"/tmp/abs.txt": b"x"}, None, "jvmcap-a"),
            "symlink": ({"MANIFEST.txt": b"x"}, {"link": "/etc/passwd"}, "jvmcap-a"),
            "not-a-bundle": ({"MANIFEST.txt": b"x"}, None, "something-else"),
        }
        for name, (entries, links, top) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "bad.tar.gz"
                make_archive(archive, entries, links, top)
                result = self.analyze(archive, Path(tmp) / "out")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((Path(tmp) / "out").exists() and any((Path(tmp) / "out").rglob("*passwd*")))
                self.assertFalse((Path(tmp) / "escape.txt").exists())

    def test_unlisted_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "b.tar.gz"
            files = minimal_bundle()
            files["extra.txt"] = b"not in sums"
            make_archive(archive, files)
            result = self.analyze(archive, Path(tmp) / "out")
            self.assertEqual(result.returncode, 6)
            self.assertIn("unlisted file extra.txt", (Path(tmp) / "out" / "ANALYSIS.md").read_text())


class ValidatorTest(unittest.TestCase):
    def copy_repo(self, tmp: str) -> Path:
        dest = Path(tmp) / "repo"
        shutil.copytree(REPO, dest, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return dest

    def test_repository_is_valid(self):
        self.assertEqual(run(VALIDATOR, REPO, check=False).returncode, 0)

    def test_rejects_codex_only_reference_and_bad_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.copy_repo(tmp)
            skill = repo / "skills/java-gc-tuning/SKILL.md"
            text = skill.read_text().replace("the `java-async-profiler` skill", "$java-async-profiler", 1)
            skill.write_text(text.replace("name: java-gc-tuning", "name: Java_GC", 1))
            (repo / "skills/java-gc-tuning/references/orphan.md").write_text("# orphan\n")
            result = run(VALIDATOR, repo, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("agent-neutral wording", result.stdout)
        self.assertIn("must be hyphen-case", result.stdout)
        self.assertIn("orphan.md is not referenced", result.stdout)

    def test_rejects_invalid_yaml_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.copy_repo(tmp)
            skill = repo / "skills/java-gc-tuning/SKILL.md"
            skill.write_text(re.sub(r"^description: ", "description: Tuning: ", skill.read_text(), count=1, flags=re.M))
            result = run(VALIDATOR, repo, check=False)
        self.assertIn("not valid YAML", result.stdout)

    def test_rejects_broken_doc_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.copy_repo(tmp)
            readme = repo / "README.md"
            readme.write_text(readme.read_text() + "\n[gone](docs/missing.md) [bad anchor](docs/examples.md#no-such-heading)\n")
            result = run(VALIDATOR, repo, check=False)
        self.assertIn("broken link docs/missing.md", result.stdout)
        self.assertIn("broken anchor docs/examples.md#no-such-heading", result.stdout)

    def test_rejects_missing_symlink_and_version_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.copy_repo(tmp)
            os.remove(repo / ".claude/skills/java-jit-codegen")
            (repo / "VERSION").write_text("9.9.9\n")
            codex = repo / ".codex-plugin/plugin.json"
            codex.write_text(codex.read_text().replace('"version": "', '"version": "9.', 1))
            result = run(VALIDATOR, repo, check=False)
        self.assertIn(".claude/skills: java-jit-codegen must be a symlink", result.stdout)
        self.assertIn("VERSION: must match", result.stdout)
        self.assertIn(".codex-plugin: plugin.json name and version must match", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
