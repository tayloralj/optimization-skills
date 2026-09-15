import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/java-vtune-uprof/scripts/profile-compare.py"


class ProfileCompareTest(unittest.TestCase):
    def test_interleaves_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result"
            command = f"{sys.executable} -c 'print(\"measured_operations=4\\nchecksum=9\\nelapsed_ns=10\")'"
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--baseline-cmd", command,
                 "--profiled-cmd", command, "--pairs", "2", "--timeout", "10",
                 "--output-dir", str(out)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["pair_count"], 2)
            self.assertEqual(summary["mean_overhead_percent"], 0.0)
            self.assertTrue((out / "pair-01-baseline.stdout").exists())

    def test_rejects_mismatched_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result"
            base = f"{sys.executable} -c 'print(\"measured_operations=4\\nchecksum=9\\nelapsed_ns=10\")'"
            prof = f"{sys.executable} -c 'print(\"measured_operations=4\\nchecksum=8\\nelapsed_ns=10\")'"
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--baseline-cmd", base,
                 "--profiled-cmd", prof, "--output-dir", str(out)],
                capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("checksums differ", run.stderr)


if __name__ == "__main__":
    unittest.main()
