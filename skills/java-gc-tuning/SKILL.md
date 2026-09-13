---
name: java-gc-tuning
description: Analyse GC and safepoint logs and tune HotSpot collectors (G1, ZGC, Shenandoah, Parallel) on JDK 21 and 25. Use when GC pauses, time-to-safepoint, allocation rate, heap growth, or collector choice may explain latency, throughput, or memory use.
---

# Java GC Tuning

Tune the collector only after logs show that GC or safepoints matter for the
stated objective. Allocation reduction usually beats flag tuning; flags buy
headroom, not a different allocation profile.

## Workflow

1. **Capture.** Launch (or restart a replica) with unified logging, keeping
   rotation bounded:

   ```bash
   -Xlog:gc*,safepoint:file=gc-%p.log:time,uptime,level,tags:filecount=5,filesize=50m
   ```

   Also record `java -XX:+PrintFlagsFinal -version` for the exact launch flags,
   the JDK build/vendor, container limits, and the workload phase.
2. **Summarise.** Run `scripts/gc-log-summary.py --from-uptime 60 gc-*.log`
   (`--from-uptime` excludes warmup; add `--json` for records). It reports pause distributions per type, pause fraction, an
   approximate allocation rate, concurrent-cycle counts, time-to-safepoint
   (TTSP) distributions, and alarms (Full GC, evacuation failure, humongous
   allocation, allocation stalls, degenerated cycles, `System.gc()`).
3. **Correlate.** Align the worst application latencies with GC/safepoint
   uptime. If tail spikes do not coincide with pauses or TTSP, GC is not the
   cause — route to the `linux-low-latency-tuning` or `linux-ebpf-io-network`
   skill instead of tuning flags.
4. **Diagnose** with `references/collectors.md`: which pause type dominates,
   whether TTSP (not GC work) is the problem, and whether the alarms show a
   sizing or allocation-pattern failure.
5. **Change one factor**: allocation site (via the `java-async-profiler` skill
   with `alloc`), heap/region sizing, collector, or pre-touch/large pages.
   Obtain approval for any production launch change and keep the previous
   flags as the rollback.
6. **Verify** with the same load: pause and TTSP distributions, the service
   latency distribution, throughput, CPU (GC threads consume cores), RSS, and
   startup time (pre-touch lengthens it).

## Collector choice (JDK 21 / 25)

- **G1** (default): balanced; pauses scale with live young-gen copy work and
  remembered-set scanning. First choice for general services.
- **Generational ZGC**: sub-millisecond pauses largely independent of heap size;
  costs extra CPU and memory headroom. JDK 21 requires `-XX:+UseZGC
  -XX:+ZGenerational`; from JDK 23 generational is the default and JDK 24+
  removed the non-generational mode. Watch for allocation stalls.
- **Shenandoah**: low pauses via concurrent compaction; present only in builds
  that include it (many OpenJDK distributions, not Oracle JDK). Generational
  mode is a product option on JDK 25 and experimental on 24.
- **Parallel**: best raw throughput for batch work that tolerates long pauses.
- **Epsilon** (`-XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC`): no
  collection. Use to prove a hot path is allocation-free or to isolate GC
  barrier cost in benchmarks, never for services.

For low-latency single-writer designs the usual end state is a near-zero
steady-state allocation rate with G1 or generational ZGC as a safety net;
confirm with `-prof gc` in JMH and a long soak with GC logging.

## Guardrails

- Never tune `MaxGCPauseMillis`, region size, or thread counts from folklore;
  change one, compare distributions, and keep the default when the gain is noise.
- `-Xms` equal to `-Xmx` plus `-XX:+AlwaysPreTouch` removes runtime heap page
  faults but raises startup time and committed RSS; account for container limits.
- A heap dump or `GC.class_histogram` without `-all` triggers a full GC and can
  pause for seconds; both expose sensitive data. Require explicit approval.
- Unified log paths, command lines, and heap dumps can contain secrets; store
  and redact accordingly.
- Container JVMs size heap from `MaxRAMPercentage` (default 25%) and threads
  from the CPU quota; record both before comparing hosts.
