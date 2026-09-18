#!/usr/bin/env python3
"""Supervise a trusted launch command, retaining partial evidence on failure."""
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--duration', type=int, required=True)
    p.add_argument('--max-mb', type=int, default=256)
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not command or not 1 <= a.duration <= 3600 or not 1 <= a.max_mb <= 4096:
        p.error('command required; duration 1..3600; max-mb 1..4096')
    os.umask(0o077)
    out = a.out.absolute()
    if any(x.is_symlink() for x in (out, *out.parents)):
        p.error('symlink output paths are not supported')
    try:
        out.mkdir(mode=0o700)  # atomic refusal of existing destinations
    except OSError as exc:
        p.error(f'cannot create private output directory: {exc}')
    budget = a.max_mb * 1024**2
    interrupted = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda s, f: interrupted.append(s))
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (budget, budget))
    def size():
        return sum(x.lstat().st_size for x in out.rglob('*') if not x.is_symlink() and x.is_file())
    status, reason, child = 1, 'launch_failed', None
    started = time.monotonic()
    (out / 'environment.json').write_text(json.dumps({
        'kernel': list(os.uname()), 'effective_cpus': sorted(os.sched_getaffinity(0)),
        'command': command,
        'perf_event_paranoid': Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip()
        if Path('/proc/sys/kernel/perf_event_paranoid').exists() else 'unavailable'
    }, indent=2) + '\n')
    env = dict(os.environ, CAPTURE_OUTPUT_DIR=str(out), LC_ALL='C')
    try:
        with (out / 'stdout.txt').open('wb') as stdout, (out / 'stderr.txt').open('wb') as stderr:
            child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env,
                                     start_new_session=True, preexec_fn=limits)
            while child.poll() is None:
                if interrupted:
                    status, reason = 128 + interrupted[0], 'interrupted'
                    break
                if size() >= budget:
                    status, reason = 125, 'storage_limit'
                    break
                if time.monotonic() - started >= a.duration:
                    status, reason = 124, 'timeout'
                    break
                time.sleep(0.05)
            else:
                status = child.returncode
                reason = 'completed' if status == 0 else 'command_failed'
    except OSError as exc:
        (out / 'error.txt').write_text(str(exc))
    finally:
        if child:
            # Only the process group created for this capture. Never signal the attached JVM.
            try:
                os.killpg(child.pid, signal.SIGTERM)
                time.sleep(0.2)
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        if size() >= budget:
            status, reason = 125, 'storage_limit'
        (out / 'manifest.json').write_text(json.dumps({
            'status': reason, 'exit_status': status, 'duration_limit_s': a.duration,
            'elapsed_s': time.monotonic() - started, 'max_mb': a.max_mb,
            'content_bytes': size(), 'complete': status == 0,
            'storage_policy': 'per-file hard limit; aggregate monitored every 50ms; not a filesystem quota'
        }, indent=2) + '\n')
    print(f'Evidence: {out} ({reason})')
    return status if status >= 0 else 128 - status


if __name__ == '__main__':
    raise SystemExit(main())
