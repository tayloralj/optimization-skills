#!/usr/bin/env bash
set -uo pipefail
export LC_ALL=C
umask 077

# Read-only: render a curated set of `jfr view` reports (JDK 21+) from one
# recording into a new directory, plus an index of what was produced. Views the
# installed jfr tool does not offer are skipped and listed.
usage() {
  cat <<EOF
Usage: ${0##*/} RECORDING.jfr NEW_OUTPUT_DIR [--focus latency|cpu|memory|all]
  latency  gc-pauses safepoints vm-operations contention-by-site latencies-by-type pinned-threads deoptimizations-by-reason
  cpu      hot-methods cpu-time-hot-methods thread-cpu-load cpu-load compiler-statistics container-cpu-throttling
  memory   gc allocation-by-site allocation-by-class memory-leaks-by-site native-memory-committed tlabs
  all      every group above plus jvm-information, jvm-flags, system-information (default)
Use the JDK whose jfr tool is at least as new as the JVM that recorded the file.
EOF
}
if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# -eq 2 || $# -eq 4 ]] || { usage >&2; exit 2; }
recording=$1; out=$2; focus=all
if [[ $# -eq 4 ]]; then
  [[ $3 == --focus ]] || { usage >&2; exit 2; }
  focus=$4
fi
command -v jfr >/dev/null 2>&1 || { printf 'jfr tool not found (it ships with the JDK).\n' >&2; exit 3; }
[[ -f "$recording" && -r "$recording" ]] || { printf 'Recording not readable: %s\n' "$recording" >&2; exit 2; }
[[ -n "$out" && ! -e "$out" && ! -L "$out" ]] || { printf 'NEW_OUTPUT_DIR must not exist.\n' >&2; exit 2; }

latency=(gc-pauses safepoints vm-operations contention-by-site latencies-by-type pinned-threads deoptimizations-by-reason)
cpu=(hot-methods cpu-time-hot-methods thread-cpu-load cpu-load compiler-statistics container-cpu-throttling)
memory=(gc allocation-by-site allocation-by-class memory-leaks-by-site native-memory-committed tlabs)
context=(jvm-information jvm-flags system-information)
case "$focus" in
  latency) views=("${latency[@]}") ;;
  cpu) views=("${cpu[@]}") ;;
  memory) views=("${memory[@]}") ;;
  all) views=("${context[@]}" "${latency[@]}" "${cpu[@]}" "${memory[@]}") ;;
  *) usage >&2; exit 2 ;;
esac

available=$(jfr view 2>&1 || true)
if [[ "$available" != *"hot-methods"* ]]; then
  printf 'This jfr tool has no "view" command (JDK 21+ needed). Use: jfr summary / jfr print --events TYPE\n' >&2
  exit 3
fi

mkdir -m 700 -- "$out"
jfr summary "$recording" > "$out/00-summary.txt" 2>&1 || { printf 'jfr summary failed; is the file a complete recording?\n' >&2; exit 5; }
index=$out/INDEX.txt
{
  printf 'recording=%s\n' "$recording"
  printf 'jfr_tool=%s\n' "$(command -v jfr)"
  printf 'focus=%s\n' "$focus"
} > "$index"
n=1
succeeded=0
failed=0
for view in "${views[@]}"; do
  if ! grep -qw -- "$view" <<< "$available"; then
    printf 'skipped_unavailable=%s\n' "$view" >> "$index"
    continue
  fi
  printf -v file '%02d-%s.txt' "$n" "$view"
  if jfr view --width 160 "$view" "$recording" > "$out/$file" 2>&1; then
    succeeded=$((succeeded + 1))
    lines=$(grep -cvE '^\s*$' "$out/$file")
    printf 'view=%s file=%s lines=%s\n' "$view" "$file" "$lines" >> "$index"
  else
    failed=$((failed + 1))
    printf 'failed=%s\n' "$view" >> "$index"
  fi
  n=$((n + 1))
done
printf 'views_succeeded=%s views_failed=%s\n' "$succeeded" "$failed" >> "$index"
cat "$index"
printf 'report_dir=%s\n' "$out"
(( succeeded > 0 && failed == 0 )) || exit 5
