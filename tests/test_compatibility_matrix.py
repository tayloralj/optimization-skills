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
                                  '--output-dir', str(Path(directory) / 'new'), '--modes', 'lock', 'park', '--batches', '1',
                                  '--warmup-batches', '0', '--timeout', '15'],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = json.loads((Path(directory) / 'new' / 'summary.json').read_text())
            self.assertEqual(summary['verified'], 2)
            self.assertEqual({row['status'] for row in summary['results']}, {'verified'})
            self.assertIn('host', summary)
            self.assertIn('java.vm.vendor', summary['results'][0]['jvm'])
            self.assertEqual((Path(directory) / 'new').stat().st_mode & 0o777, 0o700)
            self.assertTrue((Path(directory) / 'new' / 'jdk-1' / 'lock.stdout').is_file())

    def test_refuses_existing_output_symlinks_and_invalid_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'link').symlink_to(root, target_is_directory=True)
            for output, timeout in ((root, '30'), (root / 'link' / 'new', '30'),
                                    (root / 'new', 'nan'), (root / 'new', 'inf')):
                result = subprocess.run(['python3', str(SCRIPT), '--jdk', self.jdk_home(),
                                         '--output-dir', str(output), '--timeout', timeout],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((root / 'new').exists())

    def test_missing_jdk_is_unavailable_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run(['python3', str(SCRIPT), '--jdk', os.path.join(directory, 'missing'),
                                  '--source', str(SOURCE), '--output-dir', str(Path(directory) / 'new'), '--modes', 'branch'],
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 1)
            summary = json.loads((Path(directory) / 'new' / 'summary.json').read_text())
            self.assertEqual(summary['unavailable'], 1)


if __name__ == '__main__':
    unittest.main()
