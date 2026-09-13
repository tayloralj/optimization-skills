#!/usr/bin/env bash
set -uo pipefail
export LC_ALL=C

# Offline tests for the skill scripts. No root, no network, no host changes:
# host-facing scripts run against fake /proc and /sys trees, stub BCC tools, or
# short-lived JVMs owned by the current user. Set LIVE_JDK_TESTS=0 to skip JVM runs.
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/skill-tests.XXXXXX")
trap 'chmod -R u+w "$work" 2>/dev/null; rm -rf -- "$work"' EXIT
passed=0; failed=0

ok() { passed=$((passed + 1)); printf 'ok   %s\n' "$1"; }
fail() { failed=$((failed + 1)); printf 'FAIL %s\n' "$1"; [[ -z "${2:-}" ]] || printf '%s\n' "$2" | sed 's/^/     /' | head -20; }
expect_rc() { # name expected_rc command...
  local name=$1 expected=$2 out rc
  shift 2
  out=$("$@" 2>&1); rc=$?
  if [[ "$rc" == "$expected" ]]; then ok "$name"; else fail "$name (rc=$rc want $expected)" "$out"; fi
  LAST_OUT=$out
}
expect_contains() { # name needle haystack
  if [[ "$3" == *"$2"* ]]; then ok "$1"; else fail "$1 (missing: $2)" "$3"; fi
}

printf '== python unit tests\n'
if python3 "$repo/tests/test_scripts.py" >"$work/py.log" 2>&1; then ok "python unittest"; else fail "python unittest" "$(tail -30 "$work/py.log")"; fi

printf '== lab-tune.sh (fake sysfs)\n'
lab=$repo/skills/linux-low-latency-tuning/scripts/lab-tune.sh
root=$work/labroot
mkdir -p "$root/sys/kernel/mm/transparent_hugepage" "$root/proc/sys/kernel" "$root/proc/irq/42" \
  "$root/sys/devices/system/cpu/cpu3/cpufreq" "$root/sys/devices/system/cpu/smt"
printf 'always [madvise] never\n' > "$root/sys/kernel/mm/transparent_hugepage/enabled"
printf '1\n' > "$root/proc/sys/kernel/numa_balancing"
printf '0-23\n' > "$root/proc/irq/42/smp_affinity_list"
printf 'powersave\n' > "$root/sys/devices/system/cpu/cpu3/cpufreq/scaling_governor"
printf 'on\n' > "$root/sys/devices/system/cpu/smt/control"
cat > "$work/plan.txt" <<'EOF'
# comment
set /sys/kernel/mm/transparent_hugepage/enabled never
set /proc/sys/kernel/numa_balancing 0
set /proc/irq/42/smp_affinity_list 0-1
set /sys/devices/system/cpu/cpu3/cpufreq/scaling_governor performance
EOF
export LAB_TUNE_TEST_ROOT=$root
host=$(hostname 2>/dev/null || uname -n)
expect_rc "lab plan is read-only" 0 "$lab" plan "$work/plan.txt"
expect_contains "lab plan shows transition" "madvise -> never" "$LAST_OUT"
[[ $(<"$root/proc/sys/kernel/numa_balancing") == 1 ]] && ok "lab plan changed nothing" || fail "lab plan changed nothing"
expect_rc "lab apply refuses without ack" 5 "$lab" apply "$work/plan.txt" "$work/state0"
[[ ! -e "$work/state0" ]] && ok "no state dir without ack" || fail "no state dir without ack"
expect_rc "lab apply" 0 env LAB_HOST_ACK="$host" "$lab" apply "$work/plan.txt" "$work/state1"
[[ $(<"$root/proc/irq/42/smp_affinity_list") == 0-1 && $(<"$root/sys/kernel/mm/transparent_hugepage/enabled") == never ]] \
  && ok "lab apply wrote values" || fail "lab apply wrote values"
expect_rc "lab status" 0 "$lab" status "$work/state1"
expect_contains "lab status reports live" "original=0-23 requested=0-1 live=0-1" "$LAST_OUT"
expect_rc "lab apply refuses existing state dir" 2 env LAB_HOST_ACK="$host" "$lab" apply "$work/plan.txt" "$work/state1"
expect_rc "lab rollback" 0 env LAB_HOST_ACK="$host" "$lab" rollback "$work/state1"
[[ $(<"$root/proc/irq/42/smp_affinity_list") == 0-23 && $(<"$root/sys/devices/system/cpu/cpu3/cpufreq/scaling_governor") == powersave \
   && $(<"$root/sys/kernel/mm/transparent_hugepage/enabled") == madvise ]] && ok "lab rollback restored originals" || fail "lab rollback restored originals"
expect_rc "lab rollback is not replayed" 0 env LAB_HOST_ACK="$host" "$lab" rollback "$work/state1"
expect_contains "lab rollback replay message" "already rolled back" "$LAST_OUT"
chmod 444 "$root/sys/devices/system/cpu/cpu3/cpufreq/scaling_governor"
if [[ -w "$root/sys/devices/system/cpu/cpu3/cpufreq/scaling_governor" ]]; then
  ok "lab failure rollback (skipped: running as root, cannot simulate write failure)"
else
  expect_rc "lab failure triggers rollback" 6 env LAB_HOST_ACK="$host" "$lab" apply "$work/plan.txt" "$work/state2"
  [[ $(<"$root/proc/sys/kernel/numa_balancing") == 1 && $(<"$root/proc/irq/42/smp_affinity_list") == 0-23 ]] \
    && ok "lab failure restored earlier entries" || fail "lab failure restored earlier entries"
  grep -q '^status=rolled_back_after_failure' "$work/state2/meta.txt" && ok "lab failure status recorded" || fail "lab failure status recorded"
fi
chmod 644 "$root/sys/devices/system/cpu/cpu3/cpufreq/scaling_governor"
for bad in 'set /etc/shadow x' 'set /sys/devices/system/cpu/smt/control forceoff' \
           'set /proc/sys/kernel/../../../etc/x 1' 'set /proc/sys/kernel/numa_balancing 9' \
           'set /proc/sys/kernel/numa_balancing 0 extra' 'unset /proc/sys/kernel/numa_balancing 0'; do
  printf '%s\n' "$bad" > "$work/bad.txt"
  expect_rc "lab rejects: $bad" 2 "$lab" plan "$work/bad.txt"
done
mkdir -p "$root/proc/irq/43"
printf '0-23\n' > "$root/proc/irq/43/smp_affinity_list"
chmod 444 "$root/proc/irq/43/smp_affinity_list"
printf 'set /proc/irq/42/smp_affinity_list 0\nset /proc/irq/43/smp_affinity_list 0\nset /proc/sys/kernel/numa_balancing 0\n' > "$work/irq.txt"
if [[ ! -w "$root/proc/irq/43/smp_affinity_list" ]]; then
  expect_rc "lab skips refused IRQ affinity write" 0 env LAB_HOST_ACK="$host" "$lab" apply "$work/irq.txt" "$work/state3"
  expect_contains "lab reports skipped IRQ" "skipped /proc/irq/43/smp_affinity_list" "$LAST_OUT"
  grep -q '/proc/irq/43' "$work/state3/rollback.tsv" && fail "skipped IRQ excluded from rollback record" || ok "skipped IRQ excluded from rollback record"
  expect_rc "lab rollback after IRQ skip" 0 env LAB_HOST_ACK="$host" "$lab" rollback "$work/state3"
  [[ $(<"$root/proc/irq/42/smp_affinity_list") == 0-23 && $(<"$root/proc/sys/kernel/numa_balancing") == 1 ]] \
    && ok "lab rollback after IRQ skip restored values" || fail "lab rollback after IRQ skip restored values"
fi
chmod 644 "$root/proc/irq/43/smp_affinity_list"
printf 'set /proc/sys/vm/swappiness 10\n' > "$work/missing.txt"
expect_rc "lab rejects path absent on host" 3 "$lab" plan "$work/missing.txt"
unset LAB_TUNE_TEST_ROOT

printf '== latency-host-audit.sh (fake host)\n'
audit=$repo/skills/linux-low-latency-tuning/scripts/latency-host-audit.sh
h=$work/host
mkdir -p "$h/proc/irq/10" "$h/proc/irq/11" "$h/proc/sys/kernel" "$h/proc/sys/vm" "$h/etc" \
  "$h/sys/devices/system/clocksource/clocksource0" "$h/sys/kernel/mm/transparent_hugepage" \
  "$h/sys/devices/system/cpu/cpu2/cpufreq" "$h/sys/devices/system/cpu/cpu2/cpuidle/state2" \
  "$h/sys/devices/system/cpu/cpu2/topology"
printf 'BOOT_IMAGE=/vmlinuz nohz_full=2 quiet\n' > "$h/proc/cmdline"
printf '2\n' > "$h/sys/devices/system/cpu/nohz_full"
: > "$h/sys/devices/system/cpu/isolated"
printf 'hpet\n' > "$h/sys/devices/system/clocksource/clocksource0/current_clocksource"
printf '[always] madvise never\n' > "$h/sys/kernel/mm/transparent_hugepage/enabled"
printf 'always defer [madvise] never\n' > "$h/sys/kernel/mm/transparent_hugepage/defrag"
printf 'powersave\n' > "$h/sys/devices/system/cpu/cpu2/cpufreq/scaling_governor"
printf 'C3\n' > "$h/sys/devices/system/cpu/cpu2/cpuidle/state2/name"
printf '350\n' > "$h/sys/devices/system/cpu/cpu2/cpuidle/state2/latency"
printf '0\n' > "$h/sys/devices/system/cpu/cpu2/cpuidle/state2/disable"
printf '2,14\n' > "$h/sys/devices/system/cpu/cpu2/topology/thread_siblings_list"
printf '0-3\n' > "$h/proc/irq/10/smp_affinity_list"
printf '0\n' > "$h/proc/irq/11/smp_affinity_list"
printf '1\n' > "$h/proc/sys/kernel/numa_balancing"
printf 'Filename Type Size Used Priority\n/swap.img file 1 0 -2\n' > "$h/proc/swaps"
printf '60\n' > "$h/proc/sys/vm/swappiness"
out=$(HOST_ROOT=$h "$audit" --cpus 2 2>&1); rc=$?
[[ $rc == 0 ]] && ok "audit runs on fake host" || fail "audit runs on fake host" "$out"
for needle in "finding=warn:thp_always" "finding=warn:clocksource_not_tsc" "finding=warn:irqs_on_hot_cpus:1 IRQ" \
              "finding=info:not_isolated:CPUs 2" "finding=warn:smt_sibling_shared:hot CPU~sibling pairs where the sibling is not reserved: 2~14" \
              "finding=info:deep_idle_states" "finding=info:swap_enabled" "finding=info:numa_balancing" \
              "boot_nohz_full=2" "thp_defrag=madvise"; do
  expect_contains "audit reports ${needle%%:*}:${needle#*:}" "$needle" "$out"
done
[[ "$out" != *tick_not_stopped* ]] && ok "audit accepts nohz_full coverage" || fail "audit accepts nohz_full coverage" "$out"
expect_rc "audit rejects bad cpu list" 2 "$audit" --cpus '2-;rm'
expect_rc "audit sampling needs cpus" 2 "$audit" --sample-seconds 1

printf '== bpf-capture.sh (stub tools)\n'
bpf=$repo/skills/linux-ebpf-io-network/scripts/bpf-capture.sh
mkdir -p "$work/bin" && install -d -m 700 "$work/out"
for tool in offcputime runqlat tcpretrans syscount; do
  printf '#!/usr/bin/env bash\necho stub %s "$@"\n' "$tool" > "$work/bin/$tool-bpfcc"; chmod +x "$work/bin/$tool-bpfcc"
done
export PATH="$work/bin:$PATH"
expect_rc "bpf dry-run offcputime" 0 "$bpf" --dry-run --pid $$ offcputime 10 "$work/out/off.folded"
expect_contains "bpf builds folded offcputime command" "offcputime-bpfcc -f -p $$ 10" "$LAST_OUT"
expect_rc "bpf dry-run tcpretrans uses timeout" 0 "$bpf" --dry-run tcpretrans 5 "$work/out/tcp.txt"
expect_contains "bpf timeout wrapper" "timeout -s INT 5" "$LAST_OUT"
expect_rc "bpf rejects system-wide profile" 2 "$bpf" --dry-run offcputime 10 "$work/out/x.folded"
expect_rc "bpf rejects pid for system tool" 2 "$bpf" --dry-run --pid $$ tcpretrans 10 "$work/out/x.txt"
expect_rc "bpf rejects unknown tool" 2 "$bpf" --dry-run --pid $$ bash 10 "$work/out/x.txt"
expect_rc "bpf rejects long duration" 2 "$bpf" --dry-run --pid $$ runqlat 601 "$work/out/x.txt"
install -d -m 755 "$work/public"
expect_rc "bpf rejects shared output dir" 4 "$bpf" --dry-run --pid $$ runqlat 5 "$work/public/x.txt"
if [[ $(id -u) -ne 0 ]]; then
  expect_rc "bpf refuses unprivileged capture" 5 "$bpf" --pid $$ syscount 1 "$work/out/sys.txt"
fi

printf '== install.sh\n'
inst=$repo/install.sh
export CODEX_HOME=$work/codex CLAUDE_CONFIG_DIR=$work/claude
expect_rc "install subset" 0 "$inst" java-gc-tuning
[[ -L "$work/codex/skills/java-gc-tuning" && -L "$work/claude/skills/profiling-readiness" ]] && ok "install links both agents plus readiness" || fail "install links both agents plus readiness"
expect_rc "install idempotent" 0 "$inst" java-gc-tuning
mkdir -p "$work/claude/skills/java-linux-perf"
expect_rc "install refuses foreign dir" 1 "$inst" --claude java-linux-perf
expect_rc "install copy mode" 0 "$inst" --codex --copy java-jit-codegen
[[ -f "$work/codex/skills/java-jit-codegen/SKILL.md" && ! -L "$work/codex/skills/java-jit-codegen" ]] && ok "copy mode copies" || fail "copy mode copies"
expect_rc "install rejects unknown skill" 2 "$inst" nope
expect_rc "uninstall" 0 "$inst" --uninstall java-gc-tuning java-jit-codegen
[[ ! -e "$work/codex/skills/java-gc-tuning" && ! -e "$work/codex/skills/java-jit-codegen" && -d "$work/claude/skills/java-linux-perf" ]] \
  && ok "uninstall removes only owned entries" || fail "uninstall removes only owned entries"
unset CODEX_HOME CLAUDE_CONFIG_DIR

printf '== argument validation\n'
nms=$repo/skills/java-native-memory/scripts/native-memory-snapshot.sh
expect_rc "snapshot rejects bad pid" 2 "$nms" abc "$work/nm"
expect_rc "snapshot rejects existing dir" 2 "$nms" $$ "$work/out"
jfrcap=$repo/skills/java-flight-recorder/scripts/jfr-capture.sh
jfrrep=$repo/skills/java-flight-recorder/scripts/jfr-report.sh
expect_rc "jfr capture rejects bad duration" 2 "$jfrcap" $$ 0 "$work/out/x.jfr"
expect_rc "jfr capture rejects non-jfr output" 2 "$jfrcap" $$ 5 "$work/out/x.txt"
expect_rc "jfr capture rejects non-java target" 4 "$jfrcap" $$ 5 "$work/out/x.jfr"
expect_rc "jfr report rejects bad focus" 2 "$jfrrep" "$repo/README.md" "$work/rep" --focus everything

if [[ ${LIVE_JDK_TESTS:-1} == 1 ]] && command -v java >/dev/null && command -v javac >/dev/null; then
  printf '== live JDK tests (%s)\n' "$(java -version 2>&1 | head -1)"
  major=$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.specification.version/ {print $2}')
  cp "$repo/tests/fixtures/Churn.java" "$work/" && javac -d "$work/classes" "$work/Churn.java" 2>"$work/javac.log" \
    && ok "compile workload" || fail "compile workload" "$(cat "$work/javac.log")"
  declare -a gc_variants=("g1:-XX:+UseG1GC" "zgc:-XX:+UseZGC")
  [[ "$major" == 21 ]] && gc_variants+=("zgen:-XX:+UseZGC -XX:+ZGenerational")
  for variant in "${gc_variants[@]}"; do
    name=${variant%%:*}; flags=${variant#*:}
    # shellcheck disable=SC2086
    java -Xmx256m $flags "-Xlog:gc*,safepoint:file=$work/$name.log:time,uptime,level,tags" -cp "$work/classes" Churn 2 >/dev/null 2>&1
    summary=$(python3 "$repo/skills/java-gc-tuning/scripts/gc-log-summary.py" --json "$work/$name.log" 2>&1)
    if python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["pause_count"]>0 and d["safepoints"]["total_ms"]["count"]>0' "$summary" 2>/dev/null; then
      ok "gc summary on live JDK $major $name log"
    else
      fail "gc summary on live JDK $major $name log" "$summary"
    fi
  done
  java -XX:+UnlockDiagnosticVMOptions -XX:+PrintCompilation -XX:+PrintInlining -cp "$work/classes" Churn 2 > "$work/jit.txt" 2>&1
  expect_rc "jit summary on live JDK $major log" 0 python3 "$repo/skills/java-jit-codegen/scripts/jit-log-summary.py" "$work/jit.txt"
  expect_rc "jitter meter spin" 0 java "$repo/skills/java-latency-measurement/scripts/JitterMeter.java" --mode spin --duration 1 --warmup 0
  expect_contains "jitter meter prints percentiles" "p99.99_us=" "$LAST_OUT"
  java -XX:NativeMemoryTracking=summary -cp "$work/classes" Churn 120 >/dev/null 2>&1 &
  jvm=$!
  for _ in $(seq 1 50); do jcmd "$jvm" VM.version >/dev/null 2>&1 && break; sleep 0.2; done
  expect_rc "native snapshot t0" 0 "$nms" "$jvm" "$work/nm0"
  expect_rc "native snapshot t1" 0 "$nms" "$jvm" "$work/nm1"
  expect_rc "nmt compare live snapshots" 0 python3 "$repo/skills/java-native-memory/scripts/nmt-compare.py" "$work/nm0" "$work/nm1"
  expect_contains "nmt compare sees heap" "nmt_committed_delta" "$LAST_OUT"
  [[ $(stat -c %a "$work/nm0") == 700 ]] && ok "snapshot dir is private" || fail "snapshot dir is private"
  kill "$jvm" 2>/dev/null; wait "$jvm" 2>/dev/null

  java -cp "$work/classes" Churn 60 >/dev/null 2>&1 &
  jvm=$!
  for _ in $(seq 1 50); do jcmd "$jvm" VM.version >/dev/null 2>&1 && break; sleep 0.2; done
  expect_rc "jfr capture on live JVM" 0 "$jfrcap" "$jvm" 3 "$work/out/live.jfr"
  kill "$jvm" 2>/dev/null; wait "$jvm" 2>/dev/null
  [[ $(stat -c %a "$work/out/live.jfr" 2>/dev/null) == 600 ]] && ok "jfr recording is private" || fail "jfr recording is private"
  expect_rc "jfr report on live recording" 0 "$jfrrep" "$work/out/live.jfr" "$work/jfr-report" --focus latency
  [[ -s "$work/jfr-report/INDEX.txt" && -s "$work/jfr-report/01-gc-pauses.txt" ]] && ok "jfr report wrote views" || fail "jfr report wrote views" "$LAST_OUT"

  probe=$repo/skills/java-low-latency-patterns/scripts/AllocationProbe.java
  javac -d "$work/alloc" "$repo"/tests/fixtures/alloc/*.java 2>"$work/javac-alloc.log" \
    && ok "compile allocation fixtures" || fail "compile allocation fixtures" "$(cat "$work/javac-alloc.log")"
  expect_rc "allocation probe passes allocation-free class" 0 java -cp "$work/alloc" "$probe" NoAlloc --warmup-ops 500000 --ops 200000 --rounds 3
  expect_rc "allocation probe fails allocating class" 1 java -cp "$work/alloc" "$probe" Allocates --warmup-ops 500000 --ops 200000 --rounds 3
  expect_rc "allocation probe rejects non-Runnable" 2 java -cp "$work/alloc" "$probe" java.lang.String

  printf '== offline capture kit (live)\n'
  kitbuild=$repo/skills/java-offline-capture/scripts/build-kit.sh
  analyze=$repo/skills/java-offline-capture/scripts/analyze-bundle.py
  expect_rc "kit builds" 0 "$kitbuild" "$work/kits"
  kit_sha1=$(sha256sum "$work"/kits/*.tar.gz | awk '{print $1}')
  expect_rc "kit build is reproducible" 0 "$kitbuild" "$work/kits2"
  [[ $(sha256sum "$work"/kits2/*.tar.gz | awk '{print $1}') == "$kit_sha1" ]] && ok "kit sha256 identical across builds" || fail "kit sha256 identical across builds"
  mkdir -p "$work/target" && tar -xzf "$work"/kits/*.tar.gz -C "$work/target"
  kitdir=$(echo "$work"/target/jvm-collector-*)
  (cd "$kitdir" && sha256sum -c --quiet SHA256SUMS) && ok "kit checksums verify" || fail "kit checksums verify"
  collect=$kitdir/collect.sh

  expect_rc "collect rejects non-java pid" 4 bash "$collect" --pid $$ --duration 10 --yes --out "$work/caps"
  expect_rc "collect rejects bad duration" 2 bash "$collect" --pid $$ --duration 5

  (cd "$work" && exec java -XX:NativeMemoryTracking=summary -Xmx128m \
     "-Xlog:gc*,safepoint:file=$work/capgc.log:time,uptime,level,tags" \
     -XX:StartFlightRecording=name=continuous,settings=default,maxage=5m -cp "$work/classes" Churn 120 >/dev/null 2>&1) &
  jvm=$!
  for _ in $(seq 1 50); do jcmd "$jvm" VM.version >/dev/null 2>&1 && break; sleep 0.2; done
  expect_rc "collect requires --yes when not interactive" 2 bash -c "bash '$collect' --pid \$1 --duration 10 --out '$work/caps' < /dev/null" _ "$jvm"
  install -d -m 755 "$work/shared-out"
  expect_rc "collect refuses a group/world-readable --out" 4 bash "$collect" --pid "$jvm" --duration 10 --yes --out "$work/shared-out"
  [[ $(stat -c %a "$work/shared-out") == 755 ]] && ok "collect leaves existing --out permissions alone" || fail "collect leaves existing --out permissions alone"
  expect_rc "collect dry-run" 0 bash "$collect" --pid "$jvm" --duration 10 --dry-run --out "$work/caps"
  [[ ! -e "$work/caps" ]] && ok "dry-run wrote nothing" || fail "dry-run wrote nothing"
  expect_rc "collect lists java processes" 0 bash "$collect" --list
  expect_contains "collect list shows target" "$jvm" "$LAST_OUT"
  expect_rc "collect new recording" 0 bash "$collect" --pid "$jvm" --duration 10 --thread-dumps 1 --redact-hostname --out "$work/caps" --yes
  bundle_tgz=$(ls "$work"/caps/jvmcap-host-*.tar.gz 2>/dev/null | head -1)
  [[ -n "$bundle_tgz" && $(stat -c %a "$bundle_tgz") == 600 ]] && ok "bundle archive is private" || fail "bundle archive is private" "$(ls -la "$work/caps")"
  if [[ -n "$bundle_tgz" ]]; then
    bundle_sha=$(sha256sum "$bundle_tgz" | awk '{print $1}')
    expect_rc "analyze bundle" 0 python3 "$analyze" "$bundle_tgz" "$work/analysis" --expect-sha256 "$bundle_sha"
    analysis_md=$(cat "$work/analysis/ANALYSIS.md" 2>/dev/null)
    for needle in "## Findings" "Integrity: OK" "## Process" "During the capture window" "recording.jfr" "## Native memory" "thread-dump-01.txt"; do
      expect_contains "analysis contains: $needle" "$needle" "$analysis_md"
    done
    extracted=$(echo "$work"/analysis/jvmcap-*)
    grep -q '^jfr_scrub.recording.jfr=ok' "$extracted/MANIFEST.txt" && ok "jfr scrubbed on target" || fail "jfr scrubbed on target"
    leaked=$(jfr summary "$extracted/jvm/recording.jfr" 2>/dev/null | awk '/InitialEnvironmentVariable|InitialSystemProperty|SystemProcess|JVMInformation/ {s += $2} END {print s + 0}')
    [[ "$leaked" == 0 ]] && ok "no env/property/command-line events in recording" || fail "no env/property/command-line events in recording" "count=$leaked"
    grep -rqF "$(uname -n)" "$extracted" && fail "hostname redacted everywhere" || ok "hostname redacted everywhere"
    ls "$extracted"/logs/*gc* >/dev/null 2>&1 && ok "gc log auto-detected and copied" || fail "gc log auto-detected and copied"
  fi
  expect_rc "collect dump of continuous recording" 0 bash "$collect" --pid "$jvm" --jfr dump --duration 10 --out "$work/caps-dump" --yes
  dump_tgz=$(ls "$work"/caps-dump/*.tar.gz 2>/dev/null | head -1)
  [[ -n "$dump_tgz" ]] && tar -tzf "$dump_tgz" | grep 'jvm/continuous.jfr' >/dev/null && ok "dump bundle has continuous.jfr" || fail "dump bundle has continuous.jfr"
  bash "$collect" --pid "$jvm" --duration 60 --jfr none --out "$work/caps-int" --yes > "$work/int.log" 2>&1 &
  collector=$!
  sleep 6; kill -TERM "$collector"; wait "$collector"; int_rc=$?
  [[ $int_rc == 130 ]] && ok "interrupted collect exits 130" || fail "interrupted collect exits 130" "rc=$int_rc $(tail -5 "$work/int.log")"
  int_tgz=$(ls "$work"/caps-int/*.tar.gz 2>/dev/null | head -1)
  [[ -n "$int_tgz" ]] && tar -xzOf "$int_tgz" --wildcards '*/MANIFEST.txt' | grep '^interrupted=1' >/dev/null \
    && ok "interrupted collect still writes a partial bundle" || fail "interrupted collect still writes a partial bundle" "$(tail -5 "$work/int.log")"
  kill "$jvm" 2>/dev/null; wait "$jvm" 2>/dev/null

  if [[ ${WALKTHROUGH_TESTS:-0} == 1 ]]; then
    wt=$work/walk
    mkdir -p "$wt"
    javac -d "$wt" "$repo/docs/walkthrough/OrderGateway.java" && ok "walkthrough compiles" || fail "walkthrough compiles"
    for mode in allocating zero-alloc; do
      java -Xms64m -Xmx64m -XX:+UseG1GC "-Xlog:gc*,safepoint:file=$wt/$mode-gc.log:time,uptime,level,tags" \
        -cp "$wt" OrderGateway "$mode" 3 5000 "$wt/$mode.csv" >/dev/null 2>&1
    done
    expect_rc "walkthrough latency report" 0 python3 "$repo/skills/java-latency-measurement/scripts/latency-report.py" --baseline "$wt/allocating.csv" "$wt/zero-alloc.csv"
    expect_rc "walkthrough gc summary" 0 python3 "$repo/skills/java-gc-tuning/scripts/gc-log-summary.py" --from-uptime 1 "$wt/zero-alloc-gc.log"
    expect_rc "walkthrough probe zero-alloc handler" 0 java -cp "$wt" "$probe" 'OrderGateway$ZeroAllocHandler' --rounds 2
  fi
else
  printf '== live JDK tests skipped\n'
fi

printf '\npassed=%s failed=%s\n' "$passed" "$failed"
(( failed == 0 ))
