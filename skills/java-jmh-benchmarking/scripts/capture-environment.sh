#!/usr/bin/env bash
set -uo pipefail

# Read-only context for interpreting a JMH result. It intentionally does not set
# affinity, governor, turbo/boost, JVM flags, or any kernel value.
if [[ ${1:-} == -h || ${1:-} == --help ]]; then
  printf 'Usage: %s [BENCHMARK_JAR]\n' "${0##*/}"
  exit 0
fi
[[ $# -le 1 ]] || { printf 'Usage: %s [BENCHMARK_JAR]\n' "${0##*/}" >&2; exit 2; }

printf 'captured_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'kernel=%s\n' "$(uname -srmo 2>/dev/null || printf unavailable)"
printf 'java_version_begin\n'
java -version 2>&1 || true
printf 'java_version_end\n'
if command -v lscpu >/dev/null 2>&1; then
  printf 'lscpu_begin\n'
  lscpu
  printf 'lscpu_end\n'
fi
if compgen -G '/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor' >/dev/null; then
  printf 'governors=%s\n' "$(sort -u /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | paste -sd, -)"
else
  printf 'governors=unavailable\n'
fi
printf 'perf_event_paranoid=%s\n' "$(if [[ -r /proc/sys/kernel/perf_event_paranoid ]]; then cat /proc/sys/kernel/perf_event_paranoid; else printf unavailable; fi)"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'git_commit=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf unavailable)"
  printf 'git_dirty=%s\n' "$(if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then printf true; else printf false; fi)"
else
  printf 'git_commit=unavailable\n'
  printf 'git_dirty=unavailable\n'
fi
if [[ $# -eq 1 ]]; then
  [[ -f "$1" ]] || { printf 'Benchmark JAR not found: %s\n' "$1" >&2; exit 3; }
  printf 'benchmark_jar=%s\n' "$1"
  if command -v sha256sum >/dev/null 2>&1; then
    printf 'benchmark_jar_sha256=%s\n' "$(sha256sum "$1" | awk '{print $1}')"
  else
    printf 'benchmark_jar_sha256=unavailable\n'
  fi
else
  printf 'benchmark_jar=not_supplied\n'
  printf 'benchmark_jar_sha256=not_supplied\n'
fi
printf 'jmh_version=record_from_pinned_build\n'
printf 'jvm_flags=record_from_benchmark_output\n'
printf 'benchmark_command=record_separately_after_redaction\n'
