import json
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).parents[1] / "skills/linux-jvm-debug/scripts/debug-hints.py"


class DebugHintsTest(unittest.TestCase):
    def run_hints(self, *args):
        return subprocess.run(["python3", str(SCRIPT), *args], capture_output=True, text=True, check=False)

    def test_routes_common_symptoms(self):
        run = self.run_hints("--symptom", "p99 latency spikes and high CPU", "--json")
        self.assertEqual(run.returncode, 0)
        data = json.loads(run.stdout)
        self.assertEqual(data["readiness"], "profiling-readiness")
        self.assertEqual([h["skill"] for h in data["hints"]], ["java-latency-measurement", "java-flight-recorder"])

    def test_unknown_routes_to_investigation(self):
        run = self.run_hints("--symptom", "something is wrong")
        self.assertEqual(run.returncode, 0)
        self.assertIn("java-performance-investigation", run.stdout)

    def test_rejects_empty_symptom(self):
        self.assertNotEqual(self.run_hints("--symptom", " ").returncode, 0)
