import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/linux-ebpf-io-network/scripts/runqueue-delta.py"


class RunqueueDeltaTest(unittest.TestCase):
    def test_reports_schedstat_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "42"
            (proc / "task/42").mkdir(parents=True)
            (proc / "stat").write_text("42 (java) S " + " ".join(["0"] * 19) + " 77\n")
            (proc / "task/42/schedstat").write_text("100 50 2\n")
            run = subprocess.Popen(["python3", str(SCRIPT), "--pid", "42", "--duration", "0.5"],
                                   env={**os.environ, "PROC_ROOT": str(root)},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(0.1)
            (proc / "task/42/schedstat").write_text("150 80 3\n")
            stdout, stderr = run.communicate(timeout=5)
            self.assertEqual(run.returncode, 0, stderr)
            result = json.loads(stdout)
            self.assertEqual(result["totals"]["run_queue_ns"], 30)
            self.assertEqual(result["threads"][0]["timeslices"], 1)


if __name__ == "__main__":
    unittest.main()
