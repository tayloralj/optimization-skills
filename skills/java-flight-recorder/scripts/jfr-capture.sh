#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

# Bounded JFR recording of a running JVM owned by the current user, via jcmd.
# No root, no restart. The target JVM writes the file itself, so the output
# directory must be visible and writable at the same path inside the target's
# mount namespace (not the case for most containers).
usage() {
  cat <<EOF
Usage: ${0##*/} PID DURATION_SECONDS OUTPUT.jfr [SETTINGS]
  SETTINGS  default | profile (default: profile) | path to a .jfc file
Environment: JFR_MAXSIZE (default 256M) bounds retained recording data, not exact file bytes.
  JCMD_TIMEOUT_SECONDS (default 10, maximum 60) bounds each diagnostic command.
Example: install -d -m 700 ./jfr && ${0##*/} 1234 120 ./jfr/run1.jfr
EOF
}
if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# -eq 3 || $# -eq 4 ]] || { usage >&2; exit 2; }
pid=$1; duration=$2; output=$3; settings=${4:-profile}
maxsize=${JFR_MAXSIZE:-256M}
jcmd_timeout=${JCMD_TIMEOUT_SECONDS:-10}
[[ "$jcmd_timeout" =~ ^[1-9][0-9]*$ ]] && (( jcmd_timeout <= 60 )) || {
  printf 'JCMD_TIMEOUT_SECONDS must be 1-60.\n' >&2; exit 2;
}
command -v timeout >/dev/null 2>&1 || { printf 'GNU timeout is required.\n' >&2; exit 3; }
run_jcmd() { timeout --kill-after=2s "${jcmd_timeout}s" jcmd "$@"; }

[[ "$pid" =~ ^[1-9][0-9]*$ ]] || { printf 'PID must be a positive integer.\n' >&2; exit 2; }
[[ "$duration" =~ ^[1-9][0-9]*$ ]] && (( duration <= 3600 )) || { printf 'DURATION must be 1-3600 seconds.\n' >&2; exit 2; }
[[ "$maxsize" =~ ^[1-9][0-9]*[kKmMgG]?$ ]] || { printf 'JFR_MAXSIZE must look like 256M.\n' >&2; exit 2; }
case "$settings" in
  default|profile) ;;
  *.jfc) [[ -f "$settings" && -r "$settings" ]] || { printf 'Settings file not readable: %s\n' "$settings" >&2; exit 2; }
         settings=$(cd "$(dirname "$settings")" && pwd -P)/$(basename "$settings") ;;
  *) printf 'SETTINGS must be default, profile, or a .jfc file.\n' >&2; exit 2 ;;
esac
[[ "$output" == *.jfr ]] || { printf 'OUTPUT must end in .jfr.\n' >&2; exit 2; }
[[ ! -e "$output" && ! -L "$output" ]] || { printf 'OUTPUT exists; refusing overwrite.\n' >&2; exit 4; }
command -v jcmd >/dev/null 2>&1 || { printf 'jcmd not found; use the JDK that matches the target.\n' >&2; exit 3; }

output_dir=$(dirname "$output")
[[ -d "$output_dir" && ! -L "$output_dir" ]] || { printf 'Create a private output directory first (install -d -m 700 DIR).\n' >&2; exit 4; }
output_dir=$(cd "$output_dir" && pwd -P)
[[ $(stat -c %u "$output_dir") -eq $(id -u) ]] || { printf 'Output directory is not owned by this user.\n' >&2; exit 4; }
(( (8#$(stat -c %a "$output_dir") & 077) == 0 )) || { printf 'Output directory must not grant group/other access.\n' >&2; exit 4; }
output=$output_dir/$(basename "$output")

proc_root=${PROC_ROOT:-/proc}
start_time() { local raw rest; raw=$(<"$proc_root/$pid/stat") || return 1; rest=${raw##*) }; read -ra f <<< "$rest"; printf '%s' "${f[19]}"; }
[[ -r "$proc_root/$pid/status" ]] || { printf 'Target PID is not visible.\n' >&2; exit 4; }
[[ $(awk '/^Uid:/ {print $2; exit}' "$proc_root/$pid/status") == "$(id -u)" ]] || { printf 'Target must be owned by the current user.\n' >&2; exit 4; }
[[ $(basename "$(readlink "$proc_root/$pid/exe" 2>/dev/null || true)") == java ]] || { printf 'Target is not a visible Java launcher.\n' >&2; exit 4; }
[[ "$(readlink "$proc_root/$pid/ns/mnt" 2>/dev/null)" == "$(readlink /proc/self/ns/mnt 2>/dev/null)" ]] || {
  printf 'Target runs in a different mount namespace; it cannot write %s. Record inside the container instead.\n' "$output" >&2; exit 4;
}
started=$(start_time) || exit 4

name=skill-capture-$$
run_jcmd "$pid" JFR.check >/dev/null 2>&1 || { printf 'jcmd cannot attach (attach disabled, different JDK, or namespace issue).\n' >&2; exit 4; }
recording_started=0
stop_recording() {
  local stopped_state
  if (( recording_started )) && [[ $(start_time 2>/dev/null) == "$started" ]]; then
    if ! run_jcmd "$pid" JFR.stop name="$name" >/dev/null 2>&1 ||
       ! stopped_state=$(run_jcmd "$pid" JFR.check name="$name" 2>&1) ||
       ! grep -Fq "Could not find $name" <<< "$stopped_state"; then
      printf 'WARNING: could not confirm recording stopped; inspect JFR.check name=%s on PID %s.\n' "$name" "$pid" >&2
    fi
  fi
}
trap 'exit 130' HUP INT TERM
trap stop_recording EXIT

[[ $(start_time) == "$started" ]] || { printf 'Target changed during preflight.\n' >&2; exit 5; }
recording_started=1
run_jcmd "$pid" JFR.start name="$name" settings="$settings" duration="${duration}s" \
  maxsize="$maxsize" filename="$output" >"$output_dir/.jcmd-$$.log" 2>&1 || {
  printf 'JFR.start failed: %s\n' "$(tr '\n' ' ' < "$output_dir/.jcmd-$$.log")" >&2; rm -f -- "$output_dir/.jcmd-$$.log"; exit 5;
}
rm -f -- "$output_dir/.jcmd-$$.log"
printf 'recording name=%s pid=%s duration=%ss settings=%s\n' "$name" "$pid" "$duration" "$settings"

deadline=$((SECONDS + duration + 60))
finished=0
while (( SECONDS < deadline )); do
  sleep 1
  [[ $(start_time 2>/dev/null) == "$started" ]] || { printf 'Target exited during recording.\n' >&2; exit 5; }
  # A finished recording disappears ("Could not find NAME"), so match the state line, not just the name.
  check_output=$(run_jcmd "$pid" JFR.check name="$name" 2>&1) || {
    printf 'JFR.check failed or timed out; recording completion is unverified.\n' >&2; exit 5;
  }
  if grep -Fq "Could not find $name" <<< "$check_output"; then
    finished=1
    break
  fi
  grep -Eq "name=$name .*\((running|delayed|new)\)" <<< "$check_output" || {
    printf 'Unrecognised JFR.check response; recording completion is unverified.\n' >&2; exit 5;
  }
done
(( finished )) || { printf 'Recording exceeded its completion deadline.\n' >&2; exit 5; }
[[ $(start_time) == "$started" ]] || { printf 'Target changed during recording.\n' >&2; exit 5; }
recording_started=0
trap - EXIT HUP INT TERM
[[ -s "$output" ]] || { printf 'Recording finished but %s was not written.\n' "$output" >&2; exit 5; }
chmod 600 "$output"
printf 'recording=%s bytes=%s\n' "$output" "$(stat -c %s "$output")"
printf 'next: scripts/jfr-report.sh %s DIR\n' "$output"
