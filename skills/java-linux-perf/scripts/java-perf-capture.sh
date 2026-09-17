#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

usage() { printf 'Usage: %s --out DIR --duration SEC [--cpus LIST] [--record] -- java-command...\n' "${0##*/}"; }
out=; duration=; cpus=; record=0
while (($#)); do
  case $1 in
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
[[ ! -e $out ]] || { echo "refusing existing output: $out" >&2; exit 2; }
mkdir -m 700 -- "$out"
trap 'rm -rf -- "$out"' INT TERM
{ date -u +%FT%TZ; uname -a; lscpu 2>/dev/null | grep -E 'Vendor ID|Model name|CPU\(s\)|Thread\(s\)|Core\(s\)|Socket\(s\)' || true; printf 'perf_event_paranoid='; cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || true; } >"$out/environment.txt"
events=cycles:u,instructions:u,branches:u,branch-misses:u
prefix=()
[[ -n $cpus ]] && prefix=(taskset -c "$cpus")
if (( record )); then
  perf_cmd=(perf record -q -o "$out/perf.data" -e "$events" -g --call-graph dwarf --timeout "$((duration * 1000))")
else
  perf_cmd=(perf stat -x, -o "$out/perf-stat.csv" -e "$events" --timeout "$((duration * 1000))")
fi
set +e
timeout --kill-after=5s "$((duration + 10))" "${prefix[@]}" "${perf_cmd[@]}" -- "$@" >"$out/workload.stdout" 2>"$out/workload.stderr"
status=$?
set -e
printf 'exit_status=%s\n' "$status" >"$out/manifest.txt"
printf 'duration_s=%s\n' "$duration" >>"$out/manifest.txt"
printf 'cpus=%s\n' "${cpus:-all}" >>"$out/manifest.txt"
printf 'record=%s\n' "$record" >>"$out/manifest.txt"
(( status == 0 )) || { echo "workload/perf failed; see $out/workload.stderr" >&2; exit "$status"; }
trap - INT TERM
echo "Evidence: $out"
