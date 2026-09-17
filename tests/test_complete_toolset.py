import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
