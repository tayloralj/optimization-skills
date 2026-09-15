"""Real JVM correctness checks for the synthetic vendor-profiler fixture."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'skills/java-vtune-uprof/scripts/VendorWorkload.java'


@unittest.skipUnless(os.environ.get('LIVE_JDK_TESTS', '1') == '1'
                     and shutil.which('java') and shutil.which('javac'), 'JDK tests disabled or unavailable')
class VendorWorkloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        subprocess.run(['javac', '-d', cls.temp.name, str(SOURCE)], check=True,
                       capture_output=True, text=True, timeout=30)

    def run_fixture(self, *args):
        return subprocess.run(['java', '-Xmx128m', '-cp', self.temp.name, 'VendorWorkload', *args],
                              capture_output=True, text=True, timeout=15)

    def test_modes_complete_fixed_work_and_repeat_checksum(self):
        for mode in ('allocation', 'branch', 'stream', 'chase'):
            with self.subTest(mode=mode):
                results = []
                for _ in range(2):
                    run = self.run_fixture(mode, '32', '4', '1')
                    self.assertEqual(run.returncode, 0, run.stderr)
                    data = dict(line.split('=', 1) for line in run.stdout.splitlines())
                    self.assertEqual(int(data['measured_operations']), 32 * 1024)
                    self.assertGreater(int(data['elapsed_ns']), 0)
                    self.assertGreaterEqual(int(data['measurement_end_uptime_ms']),
                                            int(data['measurement_start_uptime_ms']))
                    results.append(data['checksum'])
                self.assertEqual(results[0], results[1])

    def test_allocation_checksum_accounts_for_every_operation(self):
        run = self.run_fixture('allocation', '2', '0', '1')
        self.assertEqual(run.returncode, 0, run.stderr)
        # Each complete cycle of signed byte values sums to -128.
        data = dict(line.split('=', 1) for line in run.stdout.splitlines())
        self.assertEqual(int(data['checksum']), -128 * (2 * 1024 // 256))

    def test_rejects_invalid_or_unbounded_arguments(self):
        for args in ((), ('bad', '1', '0', '1'), ('chase', '0', '0', '1'),
                     ('chase', '1000001', '0', '1'), ('stream', '1', '-1', '1'),
                     ('stream', '1', '0', '257'), ('stream', '1', '0', 'NaN')):
            with self.subTest(args=args):
                self.assertEqual(self.run_fixture(*args).returncode, 2)

    def test_source_launcher(self):
        run = subprocess.run(['java', str(SOURCE), 'stream', '2', '0', '1'],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('measured_operations=2048', run.stdout)
