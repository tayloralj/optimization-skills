# Script output examples and how to read them

Real output from the development machine (AMD Ryzen 9 7900, 24 logical CPUs,
one NUMA node with two cache domains, Ubuntu with Linux 7.0, Temurin JDK 25.0.2),
trimmed for length. Every script lives in `skills/<skill>/scripts/` and prints
`--help`.

- [Profiling readiness](#profiling-readiness)
- [Host jitter audit](#host-jitter-audit)
- [Lab-mode plan](#lab-mode-plan)
- [Jitter meter](#jitter-meter)
- [GC and safepoint log summary](#gc-and-safepoint-log-summary)
- [JIT log summary](#jit-log-summary)
- [JFR report](#jfr-report)
- [Native memory comparison](#native-memory-comparison)
- [Latency report](#latency-report)
- [Allocation probe](#allocation-probe)
- [eBPF capture (dry run)](#ebpf-capture-dry-run)
- [Offline capture on a host without an agent](#offline-capture-on-a-host-without-an-agent)

## Profiling readiness

`skills/profiling-readiness/scripts/check-profiling-readiness.sh`

```text
status=DEGRADED_VERIFIED_JFR_FALLBACK
cpu_model=AMD Ryzen 9 7900 12-Core Processor
numa_nodes=1
llc_domains=2
llc_cpu_lists=0-5,12-17;6-11,18-23
perf_event_paranoid=4
perf_smoke=failed
perf_reason=Error: No supported events found. Access to performance monitoring and observability operations is limited. ...
jfr_smoke=passed_launch_time
async_profiler=available_unverified
bpftrace=available
bcc_tools=available
```

**Reading it:** `perf` is blocked by the distribution default
(`perf_event_paranoid=4`), but JFR works, so the agent uses JFR-based skills
unless you choose to change the host (the remediation guide explains the
least-privilege options). There is one NUMA node but two cache domains: CPUs
`0-5,12-17` share one L3 cache and `6-11,18-23` the other, which matters when
pinning threads that hand off work to each other.

## Host jitter audit

`skills/linux-low-latency-tuning/scripts/latency-host-audit.sh --cpus 4-5,16-17 --sample-seconds 5`

```text
clocksource=tsc
governors_checked_cpus=powersave
thp_enabled=madvise
interrupt_rates_hot_cpus=121:1/s,126:5/s,127:3/s,CAL:1715/s,LOC:1468/s,RES:37/s,TLB:620/s
finding=info:not_isolated:CPUs 4,5,16,17 not in isolcpus/isolated set; ...
finding=info:tick_not_stopped:CPUs 4,5,16,17 not in nohz_full; expect periodic scheduler tick interrupts
finding=info:governor:governor(s) powersave on checked CPUs; frequency transitions add latency variance
finding=info:deep_idle_states:enabled idle states with exit latency >=50us on checked CPUs: cpu4:C3(350us),...
finding=info:swap_enabled:swap active with swappiness=60; paged-out JVM memory causes multi-ms stalls
finding=info:ksm_running:KSM scanning active: background CPU and copy-on-write faults
finding=warn:irqs_on_hot_cpus:15 IRQ(s) may fire on hot CPUs (first: 120,121,126,127,140,149,150,162); ...
finding=info:local_timer_rate:LOC 1468/s summed over hot CPUs: tick not stopped or timers active
findings=11
```

**Reading it:** this is a normal desktop, not a latency host. `CPUs 4-5,16-17`
are two whole cores (each CPU and its SMT sibling) in one cache domain. The
`warn` finding matters most: 15 device interrupts can land on those CPUs. The
clocksource is `tsc`, so `System.nanoTime` is fast. Each finding names the
knob to look at; none of them is changed by the audit.

## Lab-mode plan

`skills/linux-low-latency-tuning/scripts/make-lab-plan.py benchmark-host --cpus 4-5,16-17`

```text
# lab-tune plan: profile=benchmark-host host=graphics hot_cpus=4-5,16-17
# Generated read-only from this host's current values. Runtime-only; lost on reboot.
# cpu4: avoid frequency transitions (EPP follows); currently powersave
set /sys/devices/system/cpu/cpu4/cpufreq/scaling_governor performance
# cpu4: disable C3 (exit latency 350 us); currently 0
set /sys/devices/system/cpu/cpu4/cpuidle/state3/disable 1
...
# no KSM scanning or copy-on-write faults; currently 1
set /sys/kernel/mm/ksm/run 0
# keep timers where they were armed; currently 1
set /proc/sys/kernel/timer_migration 0
```

**Reading it:** a reviewable diff for this host only. `lab-tune.sh plan FILE`
shows each change again as `current -> requested` without touching anything;
the operator applies it as root with `LAB_HOST_ACK=$(hostname)`, and
`lab-tune.sh rollback DIR` restores every recorded value.

## Jitter meter

`java skills/java-latency-measurement/scripts/JitterMeter.java --mode spin --duration 3 --warmup 1`

```text
mode=spin duration_s=3 warmup_s=1
samples=98259646
p50_us=0.030
p99_us=0.050
p99.99_us=0.111
p99.999_us=4.735
max_us=659.407
count_above_20us=29
count_above_100us=3
worst_events (value_us at jvm_uptime_ms):
  659.407 at 1656
  180.361 at 2848
```

**Reading it:** a thread that never blocks still lost the CPU 29 times for more
than 20 µs in 3 seconds, once for 659 µs. That is the platform's noise floor on
an unpinned CPU. No application code will be faster than this at the tail
until the host is tuned. The uptime values line up with GC logs.

`--mode sleep` on the same host shows a median wake-up overshoot of about
55 µs. That is mostly the kernel's 50 µs default timer slack, which is why
latency-critical threads spin instead of sleeping.

## GC and safepoint log summary

`skills/java-gc-tuning/scripts/gc-log-summary.py --top 3 --from-uptime 1.5 gc.log`

```text
collectors: G1
window_uptime_s: from=1.5 to=None
pauses_ms: n=18 sum=21.333 p50=0.908 p90=2.717 p99=2.808 p99.9=2.808 max=2.808
pause_fraction: 0.139% of wall time
worst_pauses:
  2.808 ms GC(109) Pause Young (Prepare Mixed) (G1 Evacuation Pause) uptime=5.742
time_to_safepoint_ms: ...
alarms: none
```

Without `--from-uptime`, the same log shows 7 full GCs and 13 evacuation
failures, all during startup.

**Reading it:** `pause_fraction` says how much wall time was lost to pauses,
and `worst_pauses` gives uptimes to align with latency spikes. `alarms` lists
the events that deserve attention first: full GCs, evacuation failures,
humongous allocations, allocation stalls. A large `time_to_safepoint` relative
to the pause means threads were slow to stop, which GC flags will not fix.

## JIT log summary

`skills/java-jit-codegen/scripts/jit-log-summary.py --top 3 --warmup-ms 1000 jit.txt`

```text
compiles_by_tier: {'tier1': 2, 'tier2': 1, 'tier3': 35, 'tier4': 17}  osr=6 native_wrappers=7
made_not_entrant_by_reason:
  not used: 14  (normal tier-3 -> tier-4 replacement)
  OSR invalidation of lower level: 3
  uncommon trap: 1
inline_failures:
  callee is too large: 18
      4x java.util.ArrayList::grow (60 bytes)
  virtual call: 4
      3x Churn$Shape::area (0 bytes)
compiles_after_1000ms: 4 {'tier3': 2, 'tier4': 2}
```

**Reading it:** `not used` is normal. `uncommon trap` means compiled code hit
a case its profile had not seen, so the method was deoptimized. `virtual
call` on `Shape::area` means that interface call was not inlined, because
three receiver types were seen at that site. Compilations after the warmup
cut-off mean the hot path was still changing.

## JFR report

`skills/java-flight-recorder/scripts/jfr-report.sh run1.jfr report --focus latency`

```text
view=gc-pauses file=01-gc-pauses.txt lines=12
view=safepoints file=02-safepoints.txt lines=14
view=vm-operations file=03-vm-operations.txt lines=7
view=contention-by-site file=04-contention-by-site.txt lines=1
view=deoptimizations-by-reason file=07-deoptimizations-by-reason.txt lines=9
```

```text
GC Pauses
Total Pause Time: 38.1 ms
Number of Pauses: 6
Median Pause Time: 6.22 ms
```

**Reading it:** one text file per view plus `INDEX.txt`. A file with one line
(`contention-by-site` here) means the view had no rows: nothing crossed the
recording thresholds. Lower the thresholds before concluding there is no
contention.

## Native memory comparison

Two snapshots 15 seconds apart of a steady JVM started with
`-XX:NativeMemoryTracking=summary`:

```bash
skills/java-native-memory/scripts/native-memory-snapshot.sh PID nm0
skills/java-native-memory/scripts/native-memory-snapshot.sh PID nm1
skills/java-native-memory/scripts/nmt-compare.py nm0 nm1
```

```text
VmRSS_delta: +436 kB
RssAnon_delta: +428 kB
Threads_delta: -1
nmt_committed_delta: -73 kB
anon_rss_growth_not_explained_by_nmt: +501 kB
nmt_committed_by_category (largest change first):
  Thread: 1120 -> 1047 kB (-73)
```

**Reading it:** this is what healthy looks like. RSS is flat within a few
hundred kB, and no category grows. A leak shows up as a steadily growing
category (for example `Class` or `Thread`), or as large
`anon_rss_growth_not_explained_by_nmt` repeated across snapshots, which points
at native libraries or malloc arenas.

## Latency report

`skills/java-latency-measurement/scripts/latency-report.py --baseline before.csv after.csv`

See the [real repeated reports](walkthrough/repeated-results.md), produced with
identical flags and no sampling profiler on either implementation. The previous
example compared a JFR baseline with an unprofiled candidate and has been removed.

**Reading it:** the input CSV has intended start, actual start, and end per
operation. Compare response and service distributions to expose queueing.
Within-run blocks show episodic behavior but do not replace independent runs.
The report labels percentiles with fewer than 100 tail samples as indicative.

## Allocation probe

`java -cp build/walkthrough skills/java-low-latency-patterns/scripts/AllocationProbe.java 'OrderGateway$ZeroAllocHandler'`

The [walkthrough](walkthrough/README.md#5-check-allocation-directly) gives both
invocations. Exit code 0 means every measured round met the budget; 1 means at
least one exceeded it. Warmup is separate. Allocation during an earlier measured
round must not be dismissed because the final round is zero. Empty JFR allocation
samples cannot independently prove zero allocation.

## eBPF capture (dry run)

`skills/linux-ebpf-io-network/scripts/bpf-capture.sh --dry-run --pid 1609752 runqlat 30 ./bpf/rq.txt`

```text
command: /usr/sbin/runqlat-bpfcc -p 1609752 30 1 > ./bpf/rq.txt
dry_run=1 (nothing executed). The operator runs the command above as root.
```

**Reading it:** eBPF needs root, so the agent prints the exact, time-limited
command for you to run (in Claude Code: `! sudo ...`) instead of trying to
escalate. For stack-based tools it also warns when Java frames will be
unreadable and how to fix that.

## Offline capture on a host without an agent

On the analysis machine, `skills/java-offline-capture/scripts/build-kit.sh ./kits`:

```text
kit=.../kits/jvm-collector-0.3.0.tar.gz
sha256=2a49c14d1a434a9c98eb08a1eeaa7704446452d81d5ac3e48cbf01f18a6db194
files=10
```

On the target host, as the JVM's user, the collector waits for a CPU burst and
then records 30 seconds:
`bash collect.sh --pid 1243173 --trigger cpu:150 --duration 30 --thread-dumps 2 --digest --redact-hostname --out ./bundles --yes`
(the target is the synthetic `tests/fixtures/CaptureTarget.java` with a
128 MB heap):

```text
Armed: cpu:150 (up to 86400 s).
Starting: process CPU 207% >= 150% (after 5 s).
Collecting into .../bundles/jvmcap-host-57eb5aed-1243173-20260916T230708Z
[23:07:08] proc-start             ok
[23:07:09] readiness              ok
[23:07:09] jcmd-VM.version        ok
...
[23:07:11] nmt-start              ok
[23:07:21] thread-dump-1          ok
[23:07:31] thread-dump-2          ok
[23:07:41] samples                rows=6
[23:07:41] jfr-new                ok
[23:07:41] host-audit             ok
[23:07:41] proc-end               ok
[23:07:42] jcmd-heap-end          ok
[23:07:42] nmt-end                ok
[23:07:43] gc-logs                copied=1 bytes=18172100
[23:07:45] digest                 bytes=12562

bundle=.../bundles/jvmcap-host-57eb5aed-1243173-20260916T230708Z.tar.gz
size_bytes=11989258
sha256=55728bf4dbbaa2aa4bd80f079d6f83095d3144d1c182b438f05fb7f9d2d7cdf5
digest=.../bundles/jvmcap-host-57eb5aed-1243173-20260916T230708Z.digest.txt (text; paste or attach it if the bundle cannot be sent quickly)
```

Back on the analysis machine, `analyze-bundle.py jvmcap-....tar.gz ./analysis --expect-sha256 55728bf4...` writes `ANALYSIS.md` and `analysis.json`:

```text
## Findings

- **warn**: GC pauses took 16.0% of wall time (high allocation or small heap)
- **info**: thread-dump-01.txt: 1 BLOCKED threads
- **info**: thread-dump-02.txt: 1 BLOCKED threads
- **info**: 2 thread(s) show the same busy or blocked stack in every dump

## Capture
...
- Started by `process CPU 207% >= 150%` after waiting 5 s

## Process

- RSS 121 MiB → 178 MiB (+56 MiB over the window)
- Process CPU 229% of one core (all threads, including ones that exited)
...
| java (1243175) | 81.2 | 34.7 | 958 | 11 |
| contender-1 (1243197) | 41.1 | 28.2 | 481 | 15 |
| contender-0 (1243196) | 40.8 | 32.3 | 512 | 17 |
| GC Thread#2 (1243208) | 8.3 | 17.4 | 262 | 1 |

## Hot threads and their stacks

- **main** (tid 1243175, 81% CPU)
  - `thread-dump-01.txt` RUNNABLE: `CaptureTarget.burn` ← `CaptureTarget.main`
  - `thread-dump-02.txt` RUNNABLE: `CaptureTarget.burn` ← `CaptureTarget.main`
  - Same top frames in every dump: this thread is likely stuck in, or looping through, that code.
- **contender-1** (tid 1243197, 41% CPU)
  - `thread-dump-01.txt` BLOCKED: `CaptureTarget.lambda$main$0` ← ...

## Time series

5 intervals of about 5.0 s (times are host uptime in seconds). Process CPU: min 226%, median 227%, max 243% of one core. RSS 145–191 MiB.

| Interval (s) | Process CPU | Busiest thread | Host busy | Steal | iowait | CPU pressure | Throttled ms | GC pause ms (max) |
| 15863.5–15868.6 | 243% | java (1243175) 81% | 15.2% | 0.0% | 0.2% | 0.3% | - | 805.7 (6.1) |
| 15873.6–15878.6 | 228% | java (1243175) 82% | 13.2% | 0.0% | 0.2% | 0.3% | - | 780.7 (1.9) |
...
```

**Reading it:** the synthetic workload (an allocating main loop plus two threads
fighting over one monitor, on a 128 MB heap) spent a sixth of its time in GC
pauses, about 800 ms in every 5-second interval, while each pause stayed short.
The hot-thread section ties the busiest OS threads to their Java frames, and the
thread dumps show `contender-1` blocked on the monitor `contender-0` holds.
The report continues with the GC window summary, JFR views, NMT deltas, and
lock owners; `DIGEST.txt` carries a text version of the key tables. In the
bundle the JFR recording has zero environment-variable, system-property,
command-line, child-process, and process events, and the real hostname appears
nowhere. With a healthy capture from the same host, `compare-bundles.py
./analysis-baseline ./analysis` lists what changed.
