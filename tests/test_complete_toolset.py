import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_scripts import make_archive, minimal_bundle

ROOT = Path(__file__).resolve().parents[1]


class CompleteToolsetTests(unittest.TestCase):
    def test_service_evidence_finds_oom_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "host").mkdir()
            (root / "host/systemd-unit.txt").write_text("ActiveState=failed\nResult=signal\n")
            (root / "host/systemd-journal.txt").write_text("Main process exited\nKilled process 42 (java) OOM\n")
            out = subprocess.check_output(["python3", str(ROOT / "skills/java-offline-capture/scripts/service-evidence.py"), str(root), "--json"], text=True)
            kinds = {item["kind"] for item in json.loads(out)["findings"]}
            self.assertTrue({"service-state", "service-result", "oom", "restart"} <= kinds)

    def test_recovery_compare_rejects_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            proc = subprocess.run(["python3", str(ROOT / "skills/java-latency-measurement/scripts/recovery-compare.py"), "--out", str(out), "--reps", "1", "--", "bash", "-c", "echo DONE delivered=1/2"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 5)

    def test_debug_cli_routes(self):
        out = subprocess.check_output(["python3", str(ROOT / "skills/linux-jvm-debug/scripts/debug.py"), "--symptom", "high CPU and p99 latency", "--json"], text=True)
        data = json.loads(out)
        self.assertEqual(data["hints"]["hints"][0]["skill"], "java-latency-measurement")
        self.assertIn("status=", data["readiness"])

    def test_target_guard_rejects_example_pid(self):
        proc = subprocess.run(["python3", str(ROOT / "skills/linux-jvm-debug/scripts/target-guard.py"), "--pid", "12345", "--user", "ajt", "--start-ticks", "1"], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("placeholder", proc.stderr)

    def test_debug_cli_plain_text_reports_evidence(self):
        out = subprocess.check_output([
            "python3", str(ROOT / "skills/linux-jvm-debug/scripts/debug.py"),
            "--symptom", "high CPU and p99 latency"], text=True)
        self.assertIn("java-latency-measurement: measurement validity, JFR and host jitter", out)
        self.assertIn("java-flight-recorder: JFR CPU, GC, JIT and safepoint context", out)
        self.assertIn("Readiness: status=", out)

    def test_evidence_report_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "analysis.json").write_text(json.dumps({"findings": [{"severity": "warn", "text": "oom"}]}))
            out = subprocess.check_output(["python3", str(ROOT / "skills/linux-jvm-debug/scripts/evidence-report.py"), str(root), "--json"], text=True)
            self.assertEqual(json.loads(out)["confidence"], "unverified")

    def test_offline_runbook_rejects_placeholder(self):
        proc = subprocess.run(["python3", str(ROOT / "skills/java-offline-capture/scripts/offline-runbook.py"), "--pid", "12345"], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)

    def test_offline_runbook_checks_target_before_capture(self):
        out = subprocess.check_output(["python3", str(ROOT / "skills/java-offline-capture/scripts/offline-runbook.py"), "--pid", "234", "--unit", "app.service"], text=True)
        self.assertIn("./collect.sh --check --pid 234", out)
        self.assertIn("--systemd-unit app.service --coredump --dry-run", out)
        self.assertIn("--systemd-unit app.service --coredump --yes", out)

    def test_service_evidence_rejects_archive_and_missing_evidence(self):
        script = ROOT / "skills/java-offline-capture/scripts/service-evidence.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "bundle.tar.gz"
            archive.write_bytes(b"not an archive")
            for path in (archive, root):
                proc = subprocess.run(["python3", str(script), str(path), "--json"], capture_output=True, text=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertFalse(proc.stdout)

    def test_bundle_analysis_includes_service_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = minimal_bundle()
            files["host/systemd-unit.txt"] = b"ActiveState=failed\nResult=signal\n"
            files["host/systemd-journal.txt"] = b"Killed process 42 (java) OOM\n"
            files["SHA256SUMS"] = "".join(
                f"{hashlib.sha256(data).hexdigest()}  ./{name}\n"
                for name, data in sorted(files.items()) if name != "SHA256SUMS"
            ).encode()
            archive = root / "bundle.tar.gz"
            make_archive(archive, files)
            output = root / "analysis"
            proc = subprocess.run(["python3", str(ROOT / "skills/java-offline-capture/scripts/analyze-bundle.py"), str(archive), str(output)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads((output / "analysis.json").read_text())
            self.assertIn("service_evidence", data)
            kinds = {finding["kind"] for finding in data["service_evidence"]["findings"]}
            self.assertTrue({"service-state", "service-result", "oom"} <= kinds)
            self.assertIn("## Service evidence", (output / "ANALYSIS.md").read_text())


if __name__ == "__main__":
    unittest.main()
