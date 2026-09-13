#!/usr/bin/env python3
"""Synthetic failure fixtures: no live host mutations or agent API calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]


class RegressionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'])

    def script(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o700)
        return path

    def run_tool(self, path, *args):
        return subprocess.run([str(REPO / path), *map(str, args)], env=self.env,
                              cwd=self.root, capture_output=True, text=True, timeout=20)

    def test_interrupted_rollback_can_be_retried(self):
        knob = self.root / 'host/proc/sys/kernel/timer_migration'
        knob.parent.mkdir(parents=True)
        knob.write_text('0\n')
        plan = self.root / 'plan'
        plan.write_text('set /proc/sys/kernel/timer_migration 1\n')
        ready = self.root / 'ready'
        self.env.update(LAB_TUNE_TEST_ROOT=str(self.root / 'host'),
                        LAB_HOST_ACK=os.uname().nodename, REVIEW_READY=str(ready))
        self.script('tr', '''#!/usr/bin/env python3
import sys, os, pathlib, time
raw = sys.stdin.read()
if raw.strip() == '1' and not pathlib.Path(os.environ['REVIEW_READY']).exists():
    pathlib.Path(os.environ['REVIEW_READY']).touch()
    time.sleep(1)
sys.stdout.write(raw.replace('\\n', ''))
''')
        tool = 'skills/linux-low-latency-tuning/scripts/lab-tune.sh'
        state = self.root / 'state'
        proc = subprocess.Popen([str(REPO / tool), 'apply', str(plan), str(state)],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists())
            knob.unlink()
            knob.mkdir()  # restoration must fail, even when the test runner is root
            proc.send_signal(signal.SIGTERM)
            out = proc.communicate(timeout=10)[0]
            self.assertEqual(proc.returncode, 7, out)
            self.assertIn('status=rollback_incomplete', (state / 'meta.txt').read_text())
            knob.rmdir()
            knob.write_text('1\n')
            retry = self.run_tool(tool, 'rollback', state)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(knob.read_text().strip(), '0')
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate()

    def test_latency_rejects_invalid_rows_and_preserves_integers(self):
        tool = 'skills/java-latency-measurement/scripts/latency-report.py'
        csv = self.root / 'input.csv'
        for raw in ('1000,1100,900\n', '1000,900,1100\n', '-1\n', '1,2,3,4\n', '1.5\n', 'garbage\n'):
            with self.subTest(raw=raw):
                csv.write_text(raw)
                self.assertNotEqual(self.run_tool(tool, csv).returncode, 0)
        csv.write_text('9007199254740993,9007199254740994,9007199254740995\n')
        result = self.run_tool(tool, csv, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)['candidate']
        self.assertEqual(data['response_ns']['p50'], 2)
        self.assertEqual(data['service_ns']['p50'], 1)
        self.assertIn('p99.99', data['indicative_percentiles'])
        self.assertNotEqual(self.run_tool(tool, csv, '--blocks', '0').returncode, 0)

    def test_jfr_failed_views_fail_report(self):
        self.script('jfr', '''#!/usr/bin/env bash
if [[ $1 == summary ]]; then echo 'Version: 2.1'; exit 0; fi
if [[ $# == 1 ]]; then echo 'hot-methods gc-pauses safepoints'; exit 0; fi
exit 1
''')
        recording = self.root / 'input.jfr'
        recording.touch()
        result = self.run_tool('skills/java-flight-recorder/scripts/jfr-report.sh', recording, self.root / 'out', '--focus', 'latency')
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn('views_succeeded=0 views_failed=2', result.stdout)

    def test_jfr_unavailable_views_do_not_hide_success(self):
        self.script('jfr', '''#!/usr/bin/env bash
if [[ $# == 1 ]]; then echo 'hot-methods gc-pauses'; else echo 'valid report'; fi
''')
        recording = self.root / 'input.jfr'
        recording.touch()
        result = self.run_tool('skills/java-flight-recorder/scripts/jfr-report.sh', recording, self.root / 'out', '--focus', 'latency')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('views_succeeded=1 views_failed=0', result.stdout)

    def test_jfr_attach_timeout_is_bounded(self):
        proc = self.root / 'proc/123'
        (proc / 'ns').mkdir(parents=True)
        (proc / 'status').write_text(f'Uid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n')
        (proc / 'stat').write_text('123 (java) S ' + ' '.join(['0'] * 18 + ['42']) + '\n')
        (proc / 'exe').symlink_to('/synthetic/java')
        (proc / 'ns/mnt').symlink_to(os.readlink('/proc/self/ns/mnt'))
        self.script('jcmd', '#!/usr/bin/env bash\nsleep 20\n')
        out = self.root / 'private'
        out.mkdir(mode=0o700)
        self.env.update(PROC_ROOT=str(self.root / 'proc'), JCMD_TIMEOUT_SECONDS='1')
        start = time.monotonic()
        result = self.run_tool('skills/java-flight-recorder/scripts/jfr-capture.sh', '123', '1', out / 'out.jfr')
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertLess(time.monotonic() - start, 5)

    def test_jfr_failed_check_attempts_named_cleanup(self):
        proc = self.root / 'proc/123'
        (proc / 'ns').mkdir(parents=True)
        (proc / 'status').write_text(f'Uid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n')
        (proc / 'stat').write_text('123 (java) S ' + ' '.join(['0'] * 18 + ['42']) + '\n')
        (proc / 'exe').symlink_to('/synthetic/java')
        (proc / 'ns/mnt').symlink_to(os.readlink('/proc/self/ns/mnt'))
        self.env.update(PROC_ROOT=str(self.root / 'proc'), REVIEW_JCMD_LOG=str(self.root / 'jcmd.log'))
        self.script('jcmd', """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$REVIEW_JCMD_LOG"
if [[ $2 == JFR.check && $# == 3 ]]; then exit 1; fi
exit 0
""")
        out = self.root / 'private'
        out.mkdir(mode=0o700)
        result = self.run_tool('skills/java-flight-recorder/scripts/jfr-capture.sh', '123', '1', out / 'out.jfr')
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertIn('JFR.stop name=skill-capture-', (self.root / 'jcmd.log').read_text())
        self.assertIn('could not confirm recording stopped', result.stderr)

    def test_install_lifecycle_from_unrelated_directory(self):
        self.env.update(CODEX_SKILLS_DIR=str(self.root / 'codex/skills'),
                        CLAUDE_CONFIG_DIR=str(self.root / 'claude'))
        tool = 'install.sh'
        result = self.run_tool(tool)
        self.assertEqual(result.returncode, 0, result.stderr)
        names = [p.name for p in (REPO / 'skills').iterdir() if p.is_dir()]
        for base in (self.root / 'codex/skills', self.root / 'claude/skills'):
            self.assertEqual(sorted(p.name for p in base.iterdir()), sorted(names))
            for name in names:
                self.assertEqual((base / name).resolve(), REPO / 'skills' / name)
        installed = self.root / 'codex/skills/java-latency-measurement/scripts/latency-report.py'
        csv = self.root / 'lat.csv'
        csv.write_text('10\n20\n')
        self.assertEqual(subprocess.run([str(installed), str(csv)], cwd=self.root, capture_output=True).returncode, 0)
        self.assertEqual(self.run_tool(tool, '--copy').returncode, 0)
        self.assertFalse((self.root / 'codex/skills/java-gc-tuning').is_symlink())
        (self.root / 'codex/skills/unrelated').mkdir()
        self.assertEqual(self.run_tool(tool, '--uninstall').returncode, 0)
        self.assertEqual([p.name for p in (self.root / 'codex/skills').iterdir()], ['unrelated'])
        self.assertEqual(list((self.root / 'claude/skills').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
