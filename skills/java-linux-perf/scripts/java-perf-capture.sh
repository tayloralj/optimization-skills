#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

usage() { printf 'Usage: %s --out DIR --duration SEC [--max-mb MB] [--cpus LIST] [--record] -- java-command...\n' "${0##*/}"; }
out=; duration=; cpus=; record=0; max_mb=256
while (($#)); do
  case $1 in
    --max-mb) [[ $# -ge 2 ]] || exit 2; max_mb=$2; shift 2 ;;
    --out) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; out=$2; shift 2 ;;
    --duration) [[ $# -ge 2 && $2 =~ ^[1-9][0-9]{0,3}$ ]] || { usage >&2; exit 2; }; duration=$2; shift 2 ;;
    --cpus) [[ $# -ge 2 && $2 =~ ^[0-9,-]+$ ]] || { usage >&2; exit 2; }; cpus=$2; shift 2 ;;
    --record) record=1; shift ;;
    --help|-h) usage; exit 0 ;;
    --) shift; break ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n $out && -n $duration && $# -gt 0 ]] || { usage >&2; exit 2; }
command -v perf >/dev/null || { echo 'perf is required' >&2; exit 3; }
events=cycles:u,instructions:u,branches:u,branch-misses:u
prefix=()
[[ -n $cpus ]] && prefix=(taskset -c "$cpus")
if (( record )); then
  perf_cmd=(perf record -q -o "$out/perf.data" -F 99 -e cycles:u -g --call-graph 'dwarf,8192')
else
  perf_cmd=(perf stat -x ',' -o "$out/perf-stat.csv" -e "$events")
fi
here=$(cd "$(dirname "$0")" && pwd)
exec python3 "$here/bounded-capture.py" --out "$out" --duration "$duration" --max-mb "$max_mb" -- "${prefix[@]}" "${perf_cmd[@]}" -- "$@"
