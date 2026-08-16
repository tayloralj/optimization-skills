#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

usage() {
  printf 'Usage: %s PID DURATION_SECONDS EVENT NEW_OUTPUT_DIR MAX_FILES MAX_TOTAL_BYTES MIN_FREE_BYTES MAX_CAPTURE_BYTES\n' "${0##*/}" >&2
  printf 'Example: %s 1234 600 ctimer ./app-profiles-run1 12 2147483648 1073741824 536870912\n' "${0##*/}" >&2
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# -eq 8 ]] || { usage; exit 2; }
pid=$1; duration=$2; event=$3; output_dir=$4; max_files=$5; max_bytes=$6; min_free_bytes=$7; max_capture_bytes=$8
asprof_memlimit=${ASPROF_MEMLIMIT_BYTES:-134217728}

[[ "$pid" =~ ^[1-9][0-9]*$ ]] || { printf 'PID must be positive.\n' >&2; exit 2; }
[[ "$duration" =~ ^[1-9][0-9]*$ ]] && (( duration <= 3600 )) || { printf 'Duration must be 1 to 3600 seconds.\n' >&2; exit 2; }
case "$event" in cpu|ctimer|itimer|wall|alloc|lock) ;; *) printf 'Unsupported safe event.\n' >&2; exit 2 ;; esac
[[ "$max_files" =~ ^[1-9][0-9]*$ ]] && (( max_files <= 1000 )) || { printf 'MAX_FILES must be 1 to 1000.\n' >&2; exit 2; }
[[ "$max_bytes" =~ ^[1-9][0-9]*$ ]] || { printf 'MAX_TOTAL_BYTES must be positive.\n' >&2; exit 2; }
[[ "$min_free_bytes" =~ ^[1-9][0-9]*$ ]] || { printf 'MIN_FREE_BYTES must be positive.\n' >&2; exit 2; }
[[ "$max_capture_bytes" =~ ^[1-9][0-9]*$ ]] && (( max_capture_bytes <= max_bytes )) || {
  printf 'MAX_CAPTURE_BYTES must be positive and no larger than MAX_TOTAL_BYTES.\n' >&2; exit 2;
}
[[ "$asprof_memlimit" =~ ^[1-9][0-9]*$ ]] && (( asprof_memlimit <= 2147483648 )) || {
  printf 'ASPROF_MEMLIMIT_BYTES must be 1 to 2147483648.\n' >&2; exit 2;
}
[[ -n "$output_dir" && "$output_dir" != / && ! -e "$output_dir" && ! -L "$output_dir" ]] || {
  printf 'NEW_OUTPUT_DIR must not already exist and must not be a symlink.\n' >&2; exit 2;
}

if command -v asprof >/dev/null 2>&1; then asprof_bin=$(command -v asprof)
elif [[ -n "${ASYNC_PROFILER_HOME:-}" && -x "${ASYNC_PROFILER_HOME}/bin/asprof" ]]; then asprof_bin=${ASYNC_PROFILER_HOME}/bin/asprof
else printf 'asprof not found.\n' >&2; exit 3; fi
"$asprof_bin" --version >/dev/null

parent_dir=$(dirname "$output_dir")
[[ -d "$parent_dir" && ! -L "$parent_dir" ]] || { printf 'Parent output directory must exist and not be a symlink.\n' >&2; exit 4; }
mkdir -m 700 -- "$output_dir"
output_dir=$(cd "$output_dir" && pwd -P)
[[ $(stat -c %u "$output_dir") -eq $(id -u) ]] || { printf 'Output directory ownership mismatch.\n' >&2; exit 4; }

target_start_time() {
  local raw rest
  raw=$(<"/proc/$pid/stat") || return 1
  rest=${raw##*) }
  set -- $rest
  printf '%s' "${20}"
}
verify_target() {
  [[ -r "/proc/$pid/status" && -r "/proc/$pid/stat" ]] || return 1
  [[ $(awk '/^Uid:/ {print $2; exit}' "/proc/$pid/status") == "$(id -u)" ]] || return 1
  [[ $(basename "$(readlink "/proc/$pid/exe" 2>/dev/null || true)") == java ]] || return 1
}
verify_target || { printf 'Target must be a visible Java process owned by this user.\n' >&2; exit 4; }
start_time_before=$(target_start_time) || exit 4
initial_status=$("$asprof_bin" status "$pid" 2>&1) || {
  printf 'Cannot verify target profiler state; check attach policy and namespaces.\n' >&2; exit 4;
}
[[ "$initial_status" == *"Profiler is not active"* ]] || {
  printf 'A profiler session may already be active; refusing to interfere.\n' >&2; exit 4;
}
[[ $(target_start_time) == "$start_time_before" ]] || { printf 'Target changed during preflight.\n' >&2; exit 4; }

stopping=0; child_pid=; profiling_started=0; partial=
stop_capture() {
  stopping=1
  [[ -z "$child_pid" ]] || kill -TERM "$child_pid" 2>/dev/null || true
}
cleanup() {
  local cleanup_status=0 current_status
  stop_capture
  [[ -z "$child_pid" ]] || wait "$child_pid" 2>/dev/null || true
  if (( profiling_started )) && verify_target && [[ $(target_start_time) == "$start_time_before" ]]; then
    current_status=$("$asprof_bin" status "$pid" 2>&1) || current_status=unavailable
    if [[ "$current_status" != *"Profiler is not active"* ]]; then
      "$asprof_bin" stop "$pid" >/dev/null 2>&1 || cleanup_status=1
      current_status=$("$asprof_bin" status "$pid" 2>&1) || current_status=unavailable
      [[ "$current_status" == *"Profiler is not active"* ]] || cleanup_status=1
    fi
  fi
  [[ -z "$partial" ]] || rm -f -- "$partial"
  if (( cleanup_status )); then
    printf 'WARNING: could not verify that the target profiler stopped; escalate to the operator.\n' >&2
  fi
  return "$cleanup_status"
}
trap stop_capture HUP INT TERM
trap cleanup EXIT

declare -a profiles=()
total_bytes=0
sequence=0
while (( ! stopping )); do
  verify_target || { printf 'Target exited or identity changed.\n' >&2; exit 5; }
  [[ $(target_start_time) == "$start_time_before" ]] || { printf 'Target PID was reused.\n' >&2; exit 5; }
  available_kib=$(df -Pk "$output_dir" | awk 'NR==2 {print $4}')
  available_bytes=$((available_kib * 1024))
  (( available_bytes >= min_free_bytes + max_capture_bytes )) || {
    printf 'Free space is below MIN_FREE_BYTES plus MAX_CAPTURE_BYTES; stopping.\n' >&2; exit 6;
  }

  sequence=$((sequence + 1))
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  printf -v serial '%06d' "$sequence"
  partial=$output_dir/.partial-$serial.jfr
  final=$output_dir/profile-$serial-$timestamp.jfr
  [[ ! -e "$partial" && ! -L "$partial" && ! -e "$final" && ! -L "$final" ]] || { printf 'Unexpected file collision.\n' >&2; exit 6; }

  profiling_started=1
  "$asprof_bin" -d "$duration" -e "$event" --memlimit "$asprof_memlimit" -f "$partial" "$pid" &
  child_pid=$!
  capture_status=0
  budget_exceeded=0
  while kill -0 "$child_pid" 2>/dev/null; do
    partial_bytes=$(stat -c %s "$partial" 2>/dev/null || printf 0)
    if (( partial_bytes > max_capture_bytes )); then
      budget_exceeded=1
      kill -TERM "$child_pid" 2>/dev/null || true
      break
    fi
    sleep 1
  done
  wait "$child_pid" || capture_status=$?
  child_pid=
  if (( budget_exceeded )); then
    printf 'In-flight capture exceeded MAX_CAPTURE_BYTES; stopping and removing the partial file.\n' >&2
    exit 6
  elif (( capture_status != 0 )); then
    (( stopping )) && break
    printf 'Capture failed; partial artifact removed.\n' >&2
    exit 5
  fi
  profiling_started=0
  [[ -s "$partial" ]] || { printf 'Profiler created no usable JFR.\n' >&2; exit 5; }
  chmod 600 "$partial"
  mv -- "$partial" "$final"
  partial=
  profile_bytes=$(stat -c %s "$final")
  if (( profile_bytes > max_capture_bytes || profile_bytes > max_bytes )); then
    rm -f -- "$final"
    printf 'Single profile exceeded its capture or total byte budget and was removed.\n' >&2
    exit 6
  fi
  profiles+=("$final")
  total_bytes=$((total_bytes + profile_bytes))

  while (( ${#profiles[@]} > max_files || total_bytes > max_bytes )); do
    oldest=${profiles[0]}
    oldest_bytes=$(stat -c %s "$oldest" 2>/dev/null || printf 0)
    rm -f -- "$oldest"
    total_bytes=$((total_bytes - oldest_bytes))
    profiles=("${profiles[@]:1}")
  done
  printf 'captured=%s retained_files=%s retained_bytes=%s\n' "$final" "${#profiles[@]}" "$total_bytes"
done

trap - EXIT HUP INT TERM
cleanup
