"""Checks for the bounded JDK compatibility matrix runner."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'skills/java-vtune-uprof/scripts/compatibility-matrix.py'
SOURCE = REPO / 'skills/java-vtune-uprof/scripts/VendorWorkload.java'


@unittest.skipUnless(shutil.which('java') and shutil.which('javac'), 'JDK unavailable')
class CompatibilityMatrixTest(unittest.TestCase):
    def jdk_home(self):
        java = Path(shutil.which('java')).resolve()
        return str(java.parents[1])

    def test_matrix_verifies_requested_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run(['python3', str(SCRIPT), '--jdk', self.jdk_home(), '--source', str(SOURCE),
                                  '--output-dir', directory, '--modes', 'lock', 'park', '--batches', '1',
                                  '--warmup-batches', '0', '--timeout', '15'],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            self.assertEqual(summary['verified'], 2)
            self.assertEqual({row['status'] for row in summary['results']}, {'verified'})
            self.assertTrue((Path(directory) / 'jdk-1' / 'lock.stdout').is_file())

    def test_missing_jdk_is_unavailable_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run(['python3', str(SCRIPT), '--jdk', os.path.join(directory, 'missing'),
                                  '--source', str(SOURCE), '--output-dir', directory, '--modes', 'branch'],
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 1)
            summary = json.loads((Path(directory) / 'summary.json').read_text())
            self.assertEqual(summary['unavailable'], 1)


if __name__ == '__main__':
    unittest.main()
