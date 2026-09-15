#!/usr/bin/env python3
"""Run the fixed vendor-profiler fixture across explicitly supplied JDK homes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

MODES = ('allocation', 'branch', 'stream', 'chase', 'lock', 'park')
REQUIRED = ('measured_operations', 'checksum', 'elapsed_ns')


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jdk', action='append', required=True, help='JDK home; repeat for each JDK')
    parser.add_argument('--source', default=str(Path(__file__).with_name('VendorWorkload.java')))
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--modes', nargs='+', choices=MODES, default=list(MODES))
    parser.add_argument('--batches', type=int, default=4)
    parser.add_argument('--warmup-batches', type=int, default=2)
    parser.add_argument('--working-set-mib', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=30.0)
    return parser.parse_args()


def executable(home, name):
    path = Path(home).expanduser().resolve() / 'bin' / name
    return path if path.is_file() and os.access(path, os.X_OK) else None


def run(argv, timeout, stdout_path=None):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        if stdout_path:
            stdout_path.write_text(result.stdout, encoding='utf-8')
            stdout_path.with_suffix('.stderr').write_text(result.stderr, encoding='utf-8')
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ''
        err = exc.stderr or ''
        if isinstance(out, bytes):
            out = out.decode(errors='replace')
        if isinstance(err, bytes):
            err = err.decode(errors='replace')
        if stdout_path:
            stdout_path.write_text(out, encoding='utf-8')
            stdout_path.with_suffix('.stderr').write_text(err + '\ntimeout\n', encoding='utf-8')
        return 124, out, err + '\ntimeout\n'


def main():
    args = parse_args()
    if args.batches < 1 or args.warmup_batches < 0 or args.working_set_mib < 1 or args.timeout <= 0:
        print('batches, working set, and timeout must be positive; warmup cannot be negative', file=sys.stderr)
        return 2
    source = Path(args.source).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        print('source must be a regular file', file=sys.stderr)
        return 2
    output = Path(args.output_dir).expanduser().resolve()
    if output.exists() and output.is_symlink():
        print('output directory may not be a symlink', file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for index, home in enumerate(args.jdk, 1):
        java = executable(home, 'java')
        javac = executable(home, 'javac')
        row_base = {'jdk': str(Path(home).expanduser()), 'index': index}
        if not java or not javac:
            for mode in args.modes:
                results.append({**row_base, 'mode': mode, 'status': 'unavailable', 'error': 'java/javac not executable'})
            continue
        jdk_dir = output / ('jdk-%d' % index)
        classes = jdk_dir / 'classes'
        classes.mkdir(parents=True, exist_ok=True)
        rc, version, version_err = run([str(java), '-version'], args.timeout)
        version_line = (version_err or version).splitlines()[0] if (version_err or version).splitlines() else 'unknown'
        compile_rc, _, compile_err = run([str(javac), '-g', '-d', str(classes), str(source)], args.timeout)
        if compile_rc != 0:
            for mode in args.modes:
                results.append({**row_base, 'mode': mode, 'status': 'failed', 'java_version': version_line,
                                'error': 'javac failed: ' + compile_err[-500:]})
            continue
        for mode in args.modes:
            log = jdk_dir / (mode + '.stdout')
            command = [str(java), '-Xms128m', '-Xmx256m', '-XX:+PreserveFramePointer', '-cp', str(classes),
                       'VendorWorkload', mode, str(args.batches), str(args.warmup_batches), str(args.working_set_mib)]
            run_rc, stdout, stderr = run(command, args.timeout, log)
            data = {}
            try:
                data = dict(line.split('=', 1) for line in stdout.splitlines() if '=' in line)
                missing = [key for key in REQUIRED if key not in data]
                expected = args.batches * 1024
                if missing or int(data.get('measured_operations', -1)) != expected or int(data.get('elapsed_ns', 0)) <= 0:
                    raise ValueError('missing or invalid measurement fields')
                status, error = ('verified', '') if run_rc == 0 else ('failed', 'java exited %d' % run_rc)
            except (ValueError, TypeError) as exc:
                status, error = 'failed', str(exc)
            results.append({**row_base, 'mode': mode, 'status': status, 'java_version': version_line,
                            'measured_operations': data.get('measured_operations'), 'checksum': data.get('checksum'),
                            'elapsed_ns': data.get('elapsed_ns'), 'error': error, 'stderr': stderr[-500:]})
    summary = {'source': str(source), 'modes': args.modes, 'results': results,
               'verified': sum(r['status'] == 'verified' for r in results),
               'failed': sum(r['status'] == 'failed' for r in results),
               'unavailable': sum(r['status'] == 'unavailable' for r in results)}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary['failed'] == 0 and summary['unavailable'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
