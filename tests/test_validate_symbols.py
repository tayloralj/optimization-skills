import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills/java-vtune-uprof/scripts/validate-symbols.py"


class ValidateSymbolsTest(unittest.TestCase):
    def run_check(self, report, *args):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write(report)
            handle.flush()
            return subprocess.run([sys.executable, str(SCRIPT), handle.name, *args],
                                  capture_output=True, text=True)

    def test_accepts_required_java_method(self):
        run = self.run_check("VendorWorkload.chaseBatch\n", "--require", "VendorWorkload.chaseBatch")
        self.assertEqual(run.returncode, 0)
        self.assertEqual(json.loads(run.stdout)["status"], "ok")

    def test_rejects_missing_method_and_unknown_frame(self):
        run = self.run_check("[unknown]\n", "--require", "OrderHandler.handle")
        self.assertEqual(run.returncode, 1)
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["unresolved_marker_lines"], 1)


if __name__ == "__main__":
    unittest.main()
