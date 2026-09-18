"""Behavioral tests for capture boundaries and fresh subset installations."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / 'skills/java-linux-perf/scripts/bounded-capture.py'


class ReleaseSafety(unittest.TestCase):
    def test_limits_and_retained_evidence(self):
        for label, code, duration, expected in (
            ('timeout', 'import time; print("partial", flush=True); time.sleep(10)', 1, 124),
            ('bytes', 'import os; os.write(1, b"x" * 2000000)', 5, 125),
            ('failure', 'raise SystemExit(7)', 5, 7),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'capture'
                run = subprocess.run([sys.executable, str(SUPERVISOR), '--out', str(out),
                                      '--duration', str(duration), '--max-mb', '1', '--', sys.executable, '-c', code],
                                     capture_output=True, timeout=10)
                self.assertEqual(run.returncode, expected, run.stderr)
                self.assertFalse(json.loads((out / 'manifest.json').read_text())['complete'])
                self.assertTrue((out / 'stdout.txt').exists())

    def test_interrupt_preserves_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'capture'
            proc = subprocess.Popen([sys.executable, str(SUPERVISOR), '--out', str(out), '--duration', '30',
                                     '--', sys.executable, '-c', 'import time; print("partial",flush=True); time.sleep(30)'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if (out / 'stdout.txt').exists() and (out / 'stdout.txt').stat().st_size:
                        break
                    time.sleep(.02)
                proc.send_signal(signal.SIGTERM)
                proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, 143)
                self.assertEqual((out / 'stdout.txt').read_text().strip(), 'partial')
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_symlink_parent_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'link').symlink_to(root, target_is_directory=True)
            result = subprocess.run([sys.executable, str(SUPERVISOR), '--out', str(root / 'link/capture'),
                                     '--duration', '1', '--', 'true'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'capture').exists())

    def test_subset_copy_runs_outside_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CODEX_SKILLS_DIR=tmp + '/codex', CLAUDE_CONFIG_DIR=tmp + '/claude')
            subprocess.run([str(ROOT / 'install.sh'), '--copy', 'linux-jvm-debug', 'java-vtune-uprof'],
                           env=env, cwd=tmp, check=True, capture_output=True)
            for target in (Path(tmp) / 'codex', Path(tmp) / 'claude/skills'):
                for required in ('java-offline-capture', 'java-linux-perf', 'profiling-readiness'):
                    self.assertTrue((target / required / 'SKILL.md').is_file())
                result = subprocess.run([sys.executable, str(target / 'linux-jvm-debug/scripts/debug.py'),
                                         '--symptom', 'latency', '--json'], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)['hints'])

    def test_recommendations_have_provenance_and_no_diagnostic_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'analysis.json'
            source.write_text(json.dumps({'service_evidence': {'findings': [
                {'kind': 'oom', 'detail': 'kernel reported OOM kill'}]}}))
            raw = subprocess.check_output([sys.executable, str(ROOT / 'skills/linux-jvm-debug/scripts/recommendations.py'), str(source), '--json'])
            result = json.loads(raw)
            self.assertEqual(result['confidence'], 'unverified')
            rec = result['recommendations'][0]
            self.assertEqual(rec['evidence'][0]['source'], '/service_evidence/findings/0')
            self.assertTrue(rec['verification'])
            self.assertTrue(rec['uncertainty'])


if __name__ == '__main__':
    unittest.main()
