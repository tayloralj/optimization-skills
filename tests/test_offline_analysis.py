#!/usr/bin/env python3
"""Tests for the offline capture analyser, bundle comparison, and collector
helpers. All bundle contents here are synthetic: small hand-written /proc,
cgroup, thread dump, GC log, and crash log excerpts in the real formats."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_scripts import ANALYZE, make_archive, minimal_bundle

REPO = Path(__file__).resolve().parents[1]
COMPARE = REPO / "skills/java-offline-capture/scripts/compare-bundles.py"
COLLECT = REPO / "skills/java-offline-capture/assets/collector/collect.sh"
TOP = "jvmcap-h-1-20260101T000000Z"
THREADS_HEADER = "tid\tcomm\tutime\tstime\tvoluntary_ctxt\tnonvoluntary_ctxt\trun_delay_ns\tprocessor\tstate\twchan\n"
HOST_HEADER = ("uptime_s\tcpu_user\tcpu_nice\tcpu_system\tcpu_idle\tcpu_iowait\tcpu_irq\tcpu_softirq\tcpu_steal\t"
               "proc_utime\tproc_stime\trss_kb\tpsi_cpu_some_us\tpsi_io_some_us\tpsi_memory_some_us\tcg_nr_throttled\tcg_throttled_usec\n")

# JDK 17-style dump (hex nid) with a monitor held by "worker" and a deadlock report.
DUMP_1 = '''Full thread dump OpenJDK 64-Bit Server VM (17.0.9 mixed mode):

"worker" #12 prio=5 os_prio=0 cpu=900.00ms elapsed=10.00s tid=0x1 nid=0x7 runnable  [0x1]
   java.lang.Thread.State: RUNNABLE
\tat com.example.Pricing.compute(Pricing.java:10)
\tat com.example.Pricing.run(Pricing.java:5)
\t- locked <0x00000000aa> (a java.lang.Object)

"waiter-1" #13 prio=5 os_prio=0 cpu=1.00ms elapsed=10.00s tid=0x2 nid=0x8 waiting for monitor entry  [0x2]
   java.lang.Thread.State: BLOCKED (on object monitor)
\tat com.example.Pricing.run(Pricing.java:5)
\t- waiting to lock <0x00000000aa> (a java.lang.Object)

"waiter-2" #14 prio=5 os_prio=0 cpu=1.00ms elapsed=10.00s tid=0x3 nid=0x9 waiting for monitor entry  [0x3]
   java.lang.Thread.State: BLOCKED (on object monitor)
\tat com.example.Pricing.run(Pricing.java:5)
\t- waiting to lock <0x00000000aa> (a java.lang.Object)

Found one Java-level deadlock:
=============================
"a":
  waiting to lock monitor 0x1 (object 0xbb, a java.lang.Object),
  which is held by "b"

Found 1 deadlock.
'''
# JDK 21+-style dump (decimal nid), same busy stack for "worker".
DUMP_2 = '''Full thread dump OpenJDK 64-Bit Server VM (21.0.5 mixed mode):

"worker" #12 [7] prio=5 os_prio=0 cpu=1900.00ms elapsed=15.00s tid=0x1 nid=7 runnable  [0x1]
   java.lang.Thread.State: RUNNABLE
\tat com.example.Pricing.compute(Pricing.java:10)
\tat com.example.Pricing.run(Pricing.java:5)

"waiter-1" #13 [8] prio=5 os_prio=0 cpu=1.00ms elapsed=15.00s tid=0x2 nid=8 waiting on condition  [0x2]
   java.lang.Thread.State: WAITING (parking)
\tat jdk.internal.misc.Unsafe.park(java.base@21/Native Method)
'''
# JDK 21 JSON dump: no "virtual" flag, so virtual threads are estimated against DUMP_2 (2 platform threads).
JSON_DUMP = json.dumps({"threadDump": {"processId": "1", "time": "t", "runtimeVersion": "21.0.5", "threadContainers": [
    {"container": "<root>", "parent": None, "owner": None, "threads": [
        {"tid": "12", "name": "worker", "stack": ["com.example.Pricing.compute(Pricing.java:10)"]},
        {"tid": "13", "name": "waiter-1", "stack": []},
        {"tid": "40", "name": "", "stack": ["java.base/java.lang.VirtualThread.park(VirtualThread.java:1)"]},
        {"tid": "41", "name": "", "stack": ["java.base/java.lang.VirtualThread.park(VirtualThread.java:1)"]},
    ], "threadCount": "4"}]}})
HISTOGRAM_START = " num     #instances         #bytes  class name (module)\n   1:          10       1048576  [B (java.base)\nTotal 10 1048576\n"
HISTOGRAM_END = (" num     #instances         #bytes  class name (module)\n   1:        1000     209715200  [B (java.base)\n"
                 "   2:          50          4000  com.example.Order\nTotal 1050 209719200\n")
GC_LOG = "".join(f"{line}\n" for line in (
    "[0.005s][info][gc] Using G1",
    "[95.000s][info][gc] GC(1) Pause Young (Normal) (G1 Evacuation Pause) 24M->3M(128M) 2.000ms",
    "[96.000s][info][gc] GC(2) Pause Young (Normal) (G1 Evacuation Pause) 24M->3M(128M) 25.000ms",
    "[99.500s][info][gc] GC(3) Pause Young (Normal) (G1 Evacuation Pause) 24M->3M(128M) 1.000ms",
))


def cpu_stat(user: int, idle: int, steal: int) -> str:
    return (f"cpu  {user} 0 0 {idle} 0 0 0 {steal} 0 0\n"
            f"cpu0 {user} 0 0 {idle // 2} 0 0 0 {steal} 0 0\n"
            f"cpu1 0 0 0 {idle // 2} 0 0 0 0 0 0\n")


def rich_bundle() -> dict:
    files = {
        "MANIFEST.txt": ("bundle_format=1\nbundle=jvmcap-h-1-20260101T000000Z\nhost=h\npid=1\nduration_s=10\nclk_tck=100\n"
                         "target_start_ticks=1000\nlogical_cpus=2\njfr_mode=none\nstep.proc-start=ok\n"
                         "step.host-audit=ok\nstep.samples=rows=4\ntrigger_fired=process CPU 150% >= 100%\nwaited_s=42\n"),
        "proc-start/uptime_s": "100.0\n", "proc-end/uptime_s": "110.0\n",
        "proc-start/timestamp": "2026-01-01T00:00:00.000000000Z\n",
        "proc-start/stat": cpu_stat(1000, 1000, 0), "proc-end/stat": cpu_stat(1800, 1900, 300),
        "proc-start/pid_stat": "1 (java) S " + " ".join(["0"] * 10) + " 100 20 " + " ".join(["0"] * 30) + "\n",
        "proc-end/pid_stat": "1 (java) S " + " ".join(["0"] * 10) + " 1000 120 " + " ".join(["0"] * 30) + "\n",
        "proc-start/pid_status": "VmRSS:\t102400 kB\n", "proc-end/pid_status": "VmRSS:\t204800 kB\n",
        "proc-start/threads.tsv": THREADS_HEADER + "7\tworker\t100\t0\t1\t1\t0\t0\tR\t0\n8\twaiter-1\t0\t0\t1\t1\t0\t1\tS\tfutex_wait\n",
        "proc-end/threads.tsv": THREADS_HEADER + "7\tworker\t900\t0\t5\t9\t10000000\t0\tR\t0\n8\twaiter-1\t0\t0\t9\t1\t0\t1\tD\tio_schedule\n",
        "proc-start/cgroup_cpu.stat": "usage_usec 10\nnr_periods 100\nnr_throttled 5\nthrottled_usec 1000000\n",
        "proc-end/cgroup_cpu.stat": "usage_usec 20\nnr_periods 200\nnr_throttled 9\nthrottled_usec 1500000\n",
        "proc-end/cgroup_cpu.max": "200000 100000\n",
        "proc-start/cgroup_memory.events": "low 0\nhigh 0\nmax 3\noom 0\noom_kill 0\n",
        "proc-end/cgroup_memory.events": "low 0\nhigh 0\nmax 9\noom 1\noom_kill 1\n",
        "proc-end/cgroup_memory.current": "524288000\n", "proc-end/cgroup_memory.max": "536870912\n",
        "samples/host.tsv": HOST_HEADER + "".join(
            f"{up}\t{user}\t0\t0\t{idle}\t0\t0\t0\t{steal}\t{ticks}\t0\t{rss}\t\t\t\t{nr}\t{thr}\n"
            for up, user, idle, steal, ticks, rss, nr, thr in (
                (100.0, 1000, 1000, 0, 100, 102400, 5, 1000000),
                (103.0, 1100, 1180, 0, 130, 110000, 5, 1000000),
                (106.0, 1200, 1360, 20, 160, 150000, 6, 1100000),
                (110.0, 1800, 1400, 300, 1120, 204800, 9, 1500000))),
        "samples/threads.tsv": "uptime_s\ttid\tcomm\tcpu_ticks\n100.0\t7\tworker\t100\n100.0\t8\twaiter-1\t0\n"
                               "103.0\t7\tworker\t130\n106.0\t7\tworker\t160\n110.0\t7\tworker\t900\n",
        "logs/00-gc.log": GC_LOG,
        "jvm/thread-dump-01.txt": DUMP_1, "jvm/thread-dump-02.txt": DUMP_2, "jvm/thread-dump-02.json": JSON_DUMP,
        "jvm/class-histogram-start.txt": HISTOGRAM_START, "jvm/class-histogram-end.txt": HISTOGRAM_END,
    }
    data = {k: v.encode() for k, v in files.items()}
    data["SHA256SUMS"] = "".join(f"{hashlib.sha256(v).hexdigest()}  ./{k}\n" for k, v in sorted(data.items())).encode()
    return data


def analyze(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ANALYZE), *map(str, args)], capture_output=True, text=True)


class RichBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        make_archive(root / "rich.tar.gz", rich_bundle())
        cls.result = analyze(root / "rich.tar.gz", root / "out")
        cls.text = (root / "out/ANALYSIS.md").read_text() if (root / "out/ANALYSIS.md").exists() else ""
        cls.data = json.loads((root / "out/analysis.json").read_text()) if (root / "out/analysis.json").exists() else {}
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exit_and_integrity(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        self.assertIn("Integrity: OK", self.text)
        self.assertIn("Started by `process CPU 150% >= 100%` after waiting 42 s", self.text)

    def test_host_and_cgroup_findings(self):
        self.assertIn("hypervisor steal was 15.0% of host CPU time", self.text)   # 300 of 2000 ticks
        self.assertIn("cgroup CPU quota throttled the JVM 4 times (500 ms)", self.text)
        self.assertIn("cgroup OOM events during the window (oom=1, oom_kill=1)", self.text)
        self.assertEqual(self.data["cgroup"]["nr_throttled"], 4)

    def test_process_and_thread_states(self):
        self.assertIn("Process CPU 100% of one core", self.text)   # 1000 ticks in 10 s
        self.assertIn("1 thread(s) in uninterruptible kernel wait (D)", self.text)
        self.assertIn("`io_schedule` ×1", self.text)
        self.assertEqual(self.data["thread_groups_cpu_pct"]["worker"], 80.0)

    def test_hot_thread_joined_across_hex_and_decimal_nids(self):
        self.assertIn("**worker** (tid 7, 80% CPU)", self.text)
        self.assertIn("`com.example.Pricing.compute` ← `com.example.Pricing.run`", self.text)
        self.assertIn("Same top frames in every dump", self.text)
        self.assertTrue(self.data["hot_thread_stacks"][0]["same_top_frames"])

    def test_time_series_aligns_gc_pauses(self):
        self.assertIn("## Time series", self.text)
        # JVM started at host uptime 10 s: pauses at JVM 95 s and 96 s land in (103, 106], 99.5 s in (106, 110].
        self.assertIn("| 106.0–110.0 | 240% | worker (7) 185% |", self.text)
        self.assertIn("103.0–106.0 s: 27.0 ms (max 25.0 ms)", self.text)
        self.assertIn("CPU burst: 240% at 106.0–110.0 s", self.text)
        self.assertIn("steal reached 30% at 106.0–110.0 s", self.text)

    def test_gc_window_from_process_start(self):
        self.assertIn("During the capture window", self.text)
        self.assertIn("GC pause up to 25.0 ms in the window", self.text)
        self.assertEqual(self.data["gc"]["pause_count"], 3)

    def test_thread_dump_details(self):
        self.assertIn("Monitor `0x00000000aa` held by **worker**", self.text)
        self.assertIn("wanted by 2: waiter-1, waiter-2", self.text)
        self.assertIn("the JVM reports a Java-level deadlock", self.text)
        self.assertIn("virtual threads: 2 (estimated", self.text)

    def test_histogram_growth(self):
        self.assertIn("| `[B` | +990 | +199.0 |", self.text)

    def test_compare_against_minimal_bundle(self):
        make_archive(self.root / "min.tar.gz", minimal_bundle())
        self.assertEqual(analyze(self.root / "min.tar.gz", self.root / "base").returncode, 0)
        result = subprocess.run([sys.executable, str(COMPARE), str(self.root / "base"), str(self.root / "out")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Findings only in the incident", result.stdout)
        self.assertIn("cgroup OOM events", result.stdout)
        self.assertIn("| `worker` | 50.0 | 80.0 | +30.0 |", result.stdout)
        js = json.loads(subprocess.run([sys.executable, str(COMPARE), str(self.root / "base"), str(self.root / "out"), "--json"],
                                       capture_output=True, text=True).stdout)
        cpu = next(m for m in js["metrics"] if m["metric"] == "Host steal")
        self.assertAlmostEqual(cpu["incident"], 15.0, places=2)


class AnalyzerInputTest(unittest.TestCase):
    def test_rejects_unknown_bundle_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = minimal_bundle()
            files["MANIFEST.txt"] = files["MANIFEST.txt"].replace(b"bundle_format=1", b"bundle_format=2")
            make_archive(Path(tmp) / "b.tar.gz", files)
            result = analyze(Path(tmp) / "b.tar.gz", Path(tmp) / "out")
        self.assertEqual(result.returncode, 7)
        self.assertIn("unsupported bundle_format=2", result.stderr)

    def test_missing_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze(Path(tmp) / "nope.tar.gz", Path(tmp) / "out")
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", result.stderr)

    def test_split_parts_need_rejoining(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_archive(Path(tmp) / "b.tar.gz", minimal_bundle())
            data = (Path(tmp) / "b.tar.gz").read_bytes()
            (Path(tmp) / "b.tar.gz.part-000").write_bytes(data[: len(data) // 2])
            result = analyze(Path(tmp) / "b.tar.gz.part-000", Path(tmp) / "out")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rejoin split parts", result.stderr)

    def test_extracted_bundle_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "in" / TOP
            for name, data in minimal_bundle().items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(data)
            result = analyze(root, Path(tmp) / "out")
            text = (Path(tmp) / "out/ANALYSIS.md").read_text()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Integrity: OK", text)
        self.assertIn("swapping during the window", text)

    def test_loose_files_are_classified(self):
        with tempfile.TemporaryDirectory() as tmp:
            loose = Path(tmp) / "loose"
            (loose / "nested").mkdir(parents=True)
            (loose / "nested/gc.log.1").write_text(GC_LOG)
            (loose / "dump.out").write_text(DUMP_1)
            (loose / "vt.json").write_text(JSON_DUMP)
            (loose / "histo.txt").write_text(HISTOGRAM_END)
            (loose / "stacks.txt").write_text("java/lang/Thread.run;com/example/Pricing.compute 90\njava/lang/Thread.run;Other.x 10\n")
            (loose / "hs_err_pid9.log").write_text(
                "#\n# There is insufficient memory for the Java Runtime Environment to continue.\n"
                "# A fatal error has been detected by the Java Runtime Environment:\n# JRE version: synthetic\n#\n"
                "Command Line: -Dpassword=do-not-print\n")
            (loose / "notes.md").write_text("ops notes\n")
            (loose / "link").symlink_to("/etc/passwd")
            result = analyze(loose, Path(tmp) / "out")
            text = (Path(tmp) / "out/ANALYSIS.md").read_text()
            data = json.loads((Path(tmp) / "out/analysis.json").read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in ("`nested/gc.log.1 -> gc-log`", "`dump.out -> thread-dump`", "`vt.json -> thread-dump-json`",
                     "`histo.txt -> class-histogram`", "`stacks.txt -> collapsed`", "`hs_err_pid9.log -> crash`",
                     "`notes.md -> other`"):
            self.assertIn(line, text)
        self.assertNotIn("link", "".join(v for k, v in data.items() if isinstance(v, str)))
        self.assertIn("the JVM ran out of native memory", text)
        self.assertIn("`java-native-memory`", text)
        self.assertNotIn("do-not-print", text)
        self.assertIn(" 90.00%  com/example/Pricing.compute", text)
        self.assertTrue(data["capture"]["loose"])


class CollectorHelperTest(unittest.TestCase):
    def test_gc_logs_from_command_line(self):
        args = ['-Xlog:gc*,safepoint:file="/var/log/a b/gc.log":time,uptime', "-Xloggc:/old/gc.log",
                "-Xlog:gc:stdout", "-Xlog:safepoint:/plain/sp.log:uptime", "-Xlog:disable"]
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *args])
        try:
            time.sleep(0.3)
            script = ("source <(sed -n '/^cmdline_gc_logs()/,/^}/p' \"$1\"); pid=$2; cmdline_gc_logs")
            out = subprocess.run(["bash", "-c", script, "_", str(COLLECT), str(proc.pid)],
                                 capture_output=True, text=True, check=True).stdout.splitlines()
        finally:
            proc.kill()
            proc.wait()
        self.assertEqual(out, ["/var/log/a b/gc.log", "/old/gc.log", "/plain/sp.log"])

    def test_multi_pid_rejects_check(self):
        result = subprocess.run(["bash", str(COLLECT), "--check", "--pid", "1", "--pid", "2"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--check takes at most one --pid", result.stderr)

    def test_json_dumps_need_thread_dumps(self):
        result = subprocess.run(["bash", str(COLLECT), "--pid", "1", "--json-thread-dumps"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--json-thread-dumps needs --thread-dumps N", result.stderr)


if __name__ == "__main__":
    unittest.main()
