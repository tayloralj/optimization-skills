#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

# Build the self-contained collector kit for a host without an AI agent.
# Runs on the analysis machine; bundles collect.sh with the read-only helper
# scripts it uses from sibling skills. Output is a reproducible tar.gz.
usage() { printf 'Usage: %s OUTPUT_DIR\n  Writes OUTPUT_DIR/jvm-collector-VERSION.tar.gz and prints its sha256.\n' "${0##*/}"; }
if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
[[ $# -eq 1 ]] || { usage >&2; exit 2; }
out_dir=$1

skill_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
skills_root=$(dirname "$skill_dir")
version=$(tr -d '[:space:]' < "$(dirname "$skills_root")/VERSION" 2>/dev/null || true)
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || version=0.0.0-dev

declare -A helpers=(
  [check-profiling-readiness.sh]=profiling-readiness/scripts/check-profiling-readiness.sh
  [latency-host-audit.sh]=linux-low-latency-tuning/scripts/latency-host-audit.sh
  [jfr-capture.sh]=java-flight-recorder/scripts/jfr-capture.sh
  [native-memory-snapshot.sh]=java-native-memory/scripts/native-memory-snapshot.sh
  [asprof-capture.sh]=java-async-profiler/scripts/capture.sh
)
for name in "${!helpers[@]}"; do
  [[ -f "$skills_root/${helpers[$name]}" ]] || {
    printf 'Missing helper %s. Install the skills listed in %s/requires.txt.\n' "${helpers[$name]}" "$skill_dir" >&2
    exit 3
  }
done

mkdir -p -- "$out_dir"
out_dir=$(cd "$out_dir" && pwd -P)
archive=$out_dir/jvm-collector-$version.tar.gz
[[ ! -e "$archive" ]] || { printf 'Refusing to overwrite %s\n' "$archive" >&2; exit 4; }

stage=$(mktemp -d "${TMPDIR:-/tmp}/jvm-collector.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
kit=$stage/jvm-collector-$version
mkdir -p "$kit/lib"
install -m 755 "$skill_dir/assets/collector/collect.sh" "$kit/collect.sh"
install -m 644 "$skill_dir/assets/collector/README.txt" "$kit/README.txt"
for name in "${!helpers[@]}"; do
  install -m 755 "$skills_root/${helpers[$name]}" "$kit/lib/$name"
done
printf '%s\n' "$version" > "$kit/VERSION"
chmod 644 "$kit/VERSION"
( cd "$kit" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
chmod 644 "$kit/SHA256SUMS"

# Reproducible archive: fixed order, owner, and timestamps.
epoch=${SOURCE_DATE_EPOCH:-0}
tar -C "$stage" --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$epoch" \
  -cf - "jvm-collector-$version" | gzip -n -9 > "$archive"
chmod 644 "$archive"
printf 'kit=%s\n' "$archive"
printf 'sha256=%s\n' "$(sha256sum "$archive" | awk '{print $1}')"
printf 'files=%s\n' "$(tar -tzf "$archive" | grep -vc '/$')"
