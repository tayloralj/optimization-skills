#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077
usage() { printf 'Usage: %s --tool NAME --out DIR --duration SEC [--max-mb MB] -- tool-command...\n' "${0##*/}"; }
tool=; out=; duration=; max_mb=256
while (($#)); do
  case $1 in
    --max-mb) [[ $# -ge 2 ]] || exit 2; max_mb=$2; shift 2 ;;
    --tool) [[ $# -ge 2 && $2 =~ ^[A-Za-z0-9_.-]+$ ]] || { usage >&2; exit 2; }; tool=$2; shift 2 ;;
    --out) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; out=$2; shift 2 ;;
    --duration) [[ $# -ge 2 && $2 =~ ^[1-9][0-9]{0,3}$ ]] || { usage >&2; exit 2; }; duration=$2; shift 2 ;;
    --) shift; break ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n $tool && -n $out && -n $duration && $# -gt 0 ]] || { usage >&2; exit 2; }
command -v "$1" >/dev/null || { echo "tool command not found: $1" >&2; exit 3; }
here=$(cd "$(dirname "$0")/../../java-linux-perf/scripts" && pwd)
exec python3 "$here/bounded-capture.py" --out "$out" --duration "$duration" --max-mb "$max_mb" -- "$@"
