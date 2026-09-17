#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

# Build the self-contained collector kit for a host without an AI agent.
# Runs on the analysis machine; bundles collect.sh with the read-only helper
# scripts it uses from sibling skills. Output is a reproducible tar.gz, and
# optionally a single self-extracting text file that can be pasted into a console.
usage() {
  cat <<EOF
Usage: ${0##*/} OUTPUT_DIR [--single-file] [--with-async-profiler TARBALL --async-profiler-sha256 HEX]
  Writes OUTPUT_DIR/jvm-collector-VERSION[-asprof].tar.gz and prints its sha256.
  --single-file             also write jvm-collector-VERSION[-asprof].run: one text file
                            (base64 payload) for hosts reachable only by console paste
  --with-async-profiler T   include async-profiler from an official release tarball
                            (async-profiler-X.Y-linux-x64.tar.gz or -linux-arm64.tar.gz) for
                            --asprof and for attach on JRE-only runtimes
  --async-profiler-sha256   the sha256 published for that tarball (required with the above)
EOF
}
out_dir=; single_file=0; asprof_tarball=; asprof_sha=
while (( $# )); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --single-file) single_file=1 ;;
    --with-async-profiler) asprof_tarball=${2:-}; shift ;;
    --async-profiler-sha256) asprof_sha=${2:-}; shift ;;
    -*) usage >&2; exit 2 ;;
    *) [[ -z "$out_dir" ]] || { usage >&2; exit 2; }; out_dir=$1 ;;
  esac
  shift
done
[[ -n "$out_dir" ]] || { usage >&2; exit 2; }
asprof_arch=
if [[ -n "$asprof_tarball" ]]; then
  [[ -f "$asprof_tarball" ]] || { printf 'Tarball not found: %s\n' "$asprof_tarball" >&2; exit 2; }
  [[ "$asprof_sha" =~ ^[0-9a-fA-F]{64}$ ]] || { printf -- '--async-profiler-sha256 must be the 64-hex sha256 of the tarball.\n' >&2; exit 2; }
  actual=$(sha256sum "$asprof_tarball" | awk '{print $1}')
  [[ "$actual" == "${asprof_sha,,}" ]] || { printf 'async-profiler sha256 mismatch: got %s\n' "$actual" >&2; exit 5; }
  case "${asprof_tarball##*/}" in
    async-profiler-*-linux-x64.tar.gz) asprof_arch=x86_64 ;;
    async-profiler-*-linux-arm64.tar.gz) asprof_arch=aarch64 ;;
    *) printf 'Expected an official async-profiler-X.Y-linux-{x64,arm64}.tar.gz release file.\n' >&2; exit 2 ;;
  esac
elif [[ -n "$asprof_sha" ]]; then
  usage >&2; exit 2
fi

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
  [gc-log-summary.py]=java-gc-tuning/scripts/gc-log-summary.py
)
for name in "${!helpers[@]}"; do
  [[ -f "$skills_root/${helpers[$name]}" ]] || {
    printf 'Missing helper %s. Install the skills listed in %s/requires.txt.\n' "${helpers[$name]}" "$skill_dir" >&2
    exit 3
  }
done

mkdir -p -- "$out_dir"
out_dir=$(cd "$out_dir" && pwd -P)
kit_name=jvm-collector-$version${asprof_arch:+-asprof}
archive=$out_dir/$kit_name.tar.gz
run_file=$out_dir/$kit_name.run
[[ ! -e "$archive" ]] || { printf 'Refusing to overwrite %s\n' "$archive" >&2; exit 4; }
(( ! single_file )) || [[ ! -e "$run_file" ]] || { printf 'Refusing to overwrite %s\n' "$run_file" >&2; exit 4; }

stage=$(mktemp -d "${TMPDIR:-/tmp}/jvm-collector.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
kit=$stage/$kit_name
mkdir -p "$kit/lib"
install -m 755 "$skill_dir/assets/collector/collect.sh" "$kit/collect.sh"
install -m 644 "$skill_dir/assets/collector/README.txt" "$kit/README.txt"
for name in "${!helpers[@]}"; do
  install -m 755 "$skills_root/${helpers[$name]}" "$kit/lib/$name"
done
printf '%s\n' "$version" > "$kit/VERSION"
chmod 644 "$kit/VERSION"

if [[ -n "$asprof_tarball" ]]; then
  # Take only the launcher, the agent library, and the licence; refuse odd archive entries.
  unpack=$stage/asprof-unpack
  mkdir "$unpack"
  while IFS= read -r entry; do
    [[ "$entry" != /* && "$entry" != *..* ]] || { printf 'Unsafe path in tarball: %s\n' "$entry" >&2; exit 5; }
  done < <(tar -tzf "$asprof_tarball")
  top=$(tar -tzf "$asprof_tarball" | awk -F/ '{tops[$1]} END {n = 0; for (t in tops) {n++; name = t}; if (n == 1) print name}')
  [[ -n "$top" ]] || { printf 'Tarball must contain one top-level directory.\n' >&2; exit 5; }
  tar -xzf "$asprof_tarball" -C "$unpack" --no-same-owner --no-same-permissions \
    "$top/bin/asprof" "$top/lib/libasyncProfiler.so" "$top/LICENSE" || { printf 'Tarball lacks bin/asprof, lib/libasyncProfiler.so, or LICENSE.\n' >&2; exit 5; }
  for f in bin/asprof lib/libasyncProfiler.so LICENSE; do
    [[ -f "$unpack/$top/$f" && ! -L "$unpack/$top/$f" ]] || { printf 'Not a regular file in tarball: %s\n' "$f" >&2; exit 5; }
  done
  install -d -m 755 "$kit/async-profiler/bin" "$kit/async-profiler/lib"
  install -m 755 "$unpack/$top/bin/asprof" "$kit/async-profiler/bin/asprof"
  install -m 644 "$unpack/$top/lib/libasyncProfiler.so" "$kit/async-profiler/lib/libasyncProfiler.so"
  install -m 644 "$unpack/$top/LICENSE" "$kit/async-profiler/LICENSE"
  printf '%s\n' "$asprof_arch" > "$kit/async-profiler/ARCH"
  printf 'source=%s\nsha256=%s\n' "${asprof_tarball##*/}" "${asprof_sha,,}" > "$kit/async-profiler/SOURCE"
  chmod 644 "$kit/async-profiler/ARCH" "$kit/async-profiler/SOURCE"
fi

( cd "$kit" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
chmod 644 "$kit/SHA256SUMS"

# Reproducible archive: fixed order, owner, and timestamps.
epoch=${SOURCE_DATE_EPOCH:-0}
tar -C "$stage" --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$epoch" \
  -cf - "$kit_name" | gzip -n -9 > "$archive"
chmod 644 "$archive"
kit_sha=$(sha256sum "$archive" | awk '{print $1}')
printf 'kit=%s\n' "$archive"
printf 'sha256=%s\n' "$kit_sha"
printf 'files=%s\n' "$(tar -tzf "$archive" | grep -vc '/$')"

if (( single_file )); then
  {
    cat <<EOF
#!/usr/bin/env bash
# JVM performance collector kit $kit_name (self-extracting; payload is base64 text).
# Usage: bash ${run_file##*/} [DIRECTORY]   (default: current directory)
# Then: cd DIRECTORY/$kit_name && bash collect.sh --list    (see README.txt)
set -euo pipefail
umask 077
dest=\${1:-.}
[[ -d "\$dest" && ! -L "\$dest" ]] || { printf 'Directory not found: %s\n' "\$dest" >&2; exit 2; }
[[ ! -e "\$dest/$kit_name" ]] || { printf 'Refusing to overwrite %s\n' "\$dest/$kit_name" >&2; exit 4; }
payload=\$(mktemp "\${TMPDIR:-/tmp}/jvm-collector-kit.XXXXXX")
trap 'rm -f -- "\$payload"' EXIT
damaged() { printf 'Payload damaged in transfer (%s). Copy the file again.\n' "\$1" >&2; exit 5; }
sed '1,/^__PAYLOAD_BELOW__\$/d' "\$0" | base64 -d > "\$payload" 2>/dev/null || damaged "not valid base64"
printf '%s  %s\n' "$kit_sha" "\$payload" | sha256sum -c --quiet - >/dev/null 2>&1 || damaged "sha256 mismatch"
tar -xzf "\$payload" -C "\$dest"
( cd "\$dest/$kit_name" && sha256sum -c --quiet SHA256SUMS )
printf 'kit=%s\n' "\$(cd "\$dest/$kit_name" && pwd -P)"
exit 0
__PAYLOAD_BELOW__
EOF
    base64 -w 76 "$archive"
  } > "$run_file"
  chmod 644 "$run_file"
  printf 'single_file=%s\n' "$run_file"
  printf 'single_file_sha256=%s\n' "$(sha256sum "$run_file" | awk '{print $1}')"
  printf 'single_file_lines=%s\n' "$(wc -l < "$run_file")"
fi
