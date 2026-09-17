#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077
usage() { printf 'Usage: %s --tool NAME --out DIR --duration SEC -- tool-command...\n' "${0##*/}"; }
tool=; out=; duration=
while (($#)); do
  case $1 in
    --tool) [[ $# -ge 2 && $2 =~ ^[A-Za-z0-9_.-]+$ ]] || { usage >&2; exit 2; }; tool=$2; shift 2 ;;
    --out) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; out=$2; shift 2 ;;
    --duration) [[ $# -ge 2 && $2 =~ ^[1-9][0-9]{0,3}$ ]] || { usage >&2; exit 2; }; duration=$2; shift 2 ;;
    --) shift; break ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n $tool && -n $out && -n $duration && $# -gt 0 ]] || { usage >&2; exit 2; }
[[ ! -e $out ]] || { echo "refusing existing output: $out" >&2; exit 2; }
command -v "$1" >/dev/null || { echo "tool command not found: $1" >&2; exit 3; }
mkdir -m 700 -- "$out"
trap 'rm -rf -- "$out"' INT TERM
{ date -u +%FT%TZ; uname -a; lscpu 2>/dev/null | grep -E 'Vendor ID|Model name|CPU\(s\)' || true; command -v "$1"; "$1" --version 2>&1 || true; } >"$out/environment.txt"
set +e
timeout --kill-after=5s "$((duration + 10))" "$@" >"$out/stdout.txt" 2>"$out/stderr.txt"
status=$?
set -e
printf 'tool=%s\nduration_s=%s\nexit_status=%s\n' "$tool" "$duration" "$status" >"$out/manifest.txt"
(( status == 0 )) || { echo "vendor capture failed; see $out/stderr.txt" >&2; exit "$status"; }
trap - INT TERM
echo "Evidence: $out"
