#!/usr/bin/env python3
"""Tests for the Python helpers and the bundled validator. Standard library only."""
from __future__ import annotations

import json
import os
import random
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
VALIDATOR = REPO / "scripts/validate_skills.py"


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
        self.assertAlmostEqual(cand["intended_rate_per_s"], 1000.0, delta=1)
        self.assertLess(report["baseline"]["co_ratio_p99"], 1.5)
        self.assertIn("episodic stall", text)

    def test_single_column(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv") as handle:
            handle.write("latency_ns\n" + "\n".join(str(1000 + i) for i in range(1000)) + "\n")
            handle.flush()
            out = run(LAT, handle.name).stdout
        self.assertIn("cannot reveal coordinated omission", out)


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

    def test_rejects_missing_symlink_and_version_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.copy_repo(tmp)
            os.remove(repo / ".claude/skills/java-jit-codegen")
            (repo / "VERSION").write_text("9.9.9\n")
            result = run(VALIDATOR, repo, check=False)
        self.assertIn(".claude/skills: java-jit-codegen must be a symlink", result.stdout)
        self.assertIn("VERSION: must match", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
