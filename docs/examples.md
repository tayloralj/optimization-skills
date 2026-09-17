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

## JFR allocation by stack

`skills/java-flight-recorder/scripts/jfr-alloc-stacks.py client.jfr --top 4 --depth 4`

```text
jdk.ObjectAllocationSample: 144 samples, estimated 166.8 MB
 36.8%     61.3 MB  n=50   [main] java.util.HashMap$KeyIterator
        HashMap$KeySet.iterator <- HashSet.iterator <- Util$2.iterator <- TransportReactor.dispatchReadyEvents
 14.4%     24.0 MB  n=8    [main] [I
        EntryMap.<init> <- SplitConstantPool.map <- SplitConstantPool.tryFindClassOrInterface <- SplitConstantPool.classEntryForClassOrInterface
 14.2%     23.6 MB  n=21   [main] com.sequencer.client.SequenceTracker$GapResult
        SequenceTracker$GapResult.none <- SequenceTracker.onSequence <- SequencerClient.handleSequenced <- SequencerClient$DefaultEgressFrameProcessor.onEgressFragment
 10.1%     16.8 MB  n=1    [main] [B
        TcpRepairClient.<init> <- SequencerClient.addRepairEndpointInternal <- SequencerClient.addInitialRepairEndpoints <- SequencerClient.<init>
```

**Reading it:** a 40-second JDK 25 recording of a messaging client under load.
The first and third rows allocate on every poll and every message on the hot
thread (a selector's selected-key iterator, and a new "no gap" result object);
they drove the only young GC in the run. The second and fourth rows are start-up
work (lambda bootstrap, one 16 MB receive buffer) and are not worth fixing.
`allocation-by-site` alone shows the same methods without telling these apart.

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

### Recovery episodes

`skills/java-latency-measurement/scripts/latency-report.py --episodes --expected 957 gap-episodes.csv`

```text
episode mode: response = end - fault observable (intended), service = end - detection (actual), queue = detection delay
response_time: n=957 p50=216.692us p90=418.963us p99=2.643ms p99.9=4.549ms p99.99=4.549ms max=4.549ms
note: fewer than 100 tail samples; indicative only: p90, p99, p99.9, p99.99
service_time : n=957 p50=194.979us p90=373.255us p99=2.582ms p99.9=4.455ms p99.99=4.455ms max=4.455ms
queue_delay  : n=957 p50=19.847us p90=46.299us p99=91.865us p99.9=935.625us p99.99=935.625us max=935.625us
  group 1: n=348 p50=202.947us p90=312.443us p99=487.723us p99.9=1.132ms p99.99=1.132ms max=1.132ms
  group 10000: n=21 p50=2.643ms p90=3.334ms p99=4.549ms p99.9=4.549ms p99.99=4.549ms max=4.549ms
```

**Reading it:** 957 UDP gap repairs over TCP, three runs merged, grouped by gap
size (middle groups trimmed). Detection delay (`queue_delay`) is tens of
microseconds; the p99 comes from the 10,000-message gaps, not from a slow path
for small ones. With `--expected 1000` the same file prints
`INVALID: only 957 of 1000 operations completed` and exits 5. Before this client
was fixed, all 18 runs of the same probe stopped delivering part-way through while
the live-message histogram still looked normal; the completeness count is what
exposed it.

To add round-trip time on loopback without root, put
`java skills/java-latency-measurement/scripts/TcpDelayProxy.java --target 127.0.0.1:PORT --delay-ms 0.5`
between client and server. Its first line is `listening 127.0.0.1:NNNNN ...`.

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
kit=./kits/jvm-collector-0.3.0.tar.gz
sha256=fef2f1591d29e56645c95fc354a71c2c47c8e83fb6f9d7be1fb5e8e002532fdc
files=9
```

On the target host, as the JVM's user, `bash collect.sh --pid 2770898 --duration 20 --thread-dumps 2 --cpus 4-5 --redact-hostname --yes`:

```text
[19:14:17] proc-start             ok
[19:14:18] readiness              ok
[19:14:18] jcmd-VM.version        ok
...
[19:14:20] nmt-start              ok
[19:14:26] thread-dump-1          ok
[19:14:32] thread-dump-2          ok
[19:14:41] jfr-new                ok
[19:14:41] host-audit             ok
[19:14:42] nmt-end                ok
[19:14:42] gc-logs                copied=3 bytes=12266708

bundle=.../jvmcap-host-57eb5aed-2770898-20260913T191417Z.tar.gz
size_bytes=15210565
sha256=2313618bf1d2439f42e88a2d89e14b7e04c8784814e283a4bc9c235598fb332a
```

Back on the analysis machine, `analyze-bundle.py jvmcap-....tar.gz ./analysis --expect-sha256 2313618b...` writes `ANALYSIS.md`:

```text
## Findings

- **warn**: GC pauses took 19.3% of wall time (high allocation or small heap)
- **warn**: GC alarms: evacuation_failure: 28, humongous_allocation: 53
- **info**: time-to-safepoint reached 13.7 ms (threads slow to stop)

## Suggested next skills

- `java-gc-tuning`

## Process

- RSS 173 MiB → 204 MiB (+30 MiB over the window)
- 25 threads; total CPU 178% of one core

| Thread (tid) | CPU % | Run-queue delay ms | Involuntary switches | Last CPU |
| java (2770900) | 78.7 | 12.9 | 733 | 3 |
| GC Thread#0 (2770903) | 14.7 | 11.9 | 304 | 12 |
```

**Reading it:** the demo workload (a deliberately allocation-heavy program with
a 128 MB heap) spent a fifth of its time in GC, and the GC threads rank
right behind the application thread in CPU. The report also holds the JFR
views (hot methods, allocation by site), NMT deltas, interrupt and vmstat
deltas, and thread-dump state counts. In the bundle the JFR recording has zero
environment-variable, system-property, command-line, and process events, and
the real hostname appears nowhere.
