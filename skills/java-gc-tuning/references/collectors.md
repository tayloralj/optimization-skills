# Collector diagnosis reference

Confirm every flag against `java -XX:+PrintFlagsFinal -version` on the target
JDK; defaults and availability change between releases and vendors.

## Reading the summary

| Observation | Likely meaning | Next evidence |
| --- | --- | --- |
| TTSP p99 large relative to pause time | Threads slow to reach safepoint: long uncounted/stripped loops, large array copies, JNI critical regions, page faults, or CPU starvation | JFR `jdk.SafepointBegin`/`jdk.ExecuteVMOperation`; `-XX:+SafepointTimeout -XX:SafepointTimeoutDelay=MS` names laggard threads; check CPU quota and run-queue delay |
| Many non-GC safepoint operations | Deoptimization, biased-lock-era habits, thread dumps, JFR/JVMTI, class redefinition, `jcmd` polling | Group by operation; find the caller (monitoring agents are frequent culprits) |
| G1 young pauses grow with load | Survivor copying or remembered-set scanning | `-Xlog:gc+phases=debug`; object age via `-Xlog:gc+age=trace`; allocation profile |
| G1 humongous allocations | Objects ≥ half a region (large arrays/buffers) | Allocation profile for the site; reuse buffers or raise `G1HeapRegionSize` deliberately |
| G1 evacuation failure / to-space exhausted | Heap too small for promotion burst | Heap-after-GC trend; raise heap or cut the burst; check `G1ReservePercent` |
| G1 Full GC | Marking could not keep up or evacuation failed | Earlier concurrent start (`InitiatingHeapOccupancyPercent` with adaptive IHOP), more heap, fewer humongous objects |
| ZGC allocation stall | Allocation outpaced concurrent collection; threads blocked | More heap headroom (`-Xmx`, `SoftMaxHeapSize`), more concurrent threads, less allocation |
| Shenandoah degenerated / full GC | Concurrent cycle lost the race | More headroom; review pacing and allocation spikes |
| `System.gc()` | Explicit calls, RMI DGC, or direct-buffer reservation pressure | Stack via JFR `jdk.GarbageCollection` cause; `-XX:+DisableExplicitGC` only after checking direct-buffer reclamation needs |
| Heap-after-GC rises steadily | Retention (leak, cache, queue backlog) | Histogram/dump under approval; see retention below |

The summariser's allocation rate is an estimate from heap-before minus the
previous heap-after for pause events that print heap sizes (G1, Parallel,
Serial). Use JFR `jdk.ObjectAllocationSample` or async-profiler `alloc` for
sites, and `jdk.GCHeapSummary` for exact heap usage.

## Useful logging additions

```text
-Xlog:gc+phases=debug          per-phase pause breakdown (G1)
-Xlog:gc+heap=debug            per-region-type occupancy
-Xlog:gc+age=trace             tenuring distribution
-Xlog:safepoint*=debug         extra safepoint detail (tag sets vary; list with -Xlog:help)
-Xlog:gc+ergo*=debug           ergonomic sizing decisions
```

Debug and trace levels add volume; bound file count and size.

## Heap sizing and memory backing

- Fixed heap (`-Xms` = `-Xmx`) avoids resize pauses and uncommit/commit churn.
- `-XX:+AlwaysPreTouch` faults heap pages at startup; combine with the host's
  transparent huge page mode deliberately (see the `linux-low-latency-tuning`
  skill). JVM options: `-XX:+UseTransparentHugePages` (needs THP `madvise` or
  `always`) or `-XX:+UseLargePages` with preallocated hugetlbfs pages. Verify
  with `-Xlog:pagesize` and `/proc/PID/smaps_rollup` (`AnonHugePages`).
- Compact object headers (`-XX:+UseCompactObjectHeaders`) reduce heap footprint
  and GC work: product option on JDK 25, experimental (unlock required) on 24,
  absent on 21. Re-check JOL layouts and benchmarks after enabling.
- Containers: `-XX:MaxRAMPercentage`, `-XX:InitialRAMPercentage`, and
  `-XX:ActiveProcessorCount` override detection. GC and compiler thread counts
  follow the detected CPU count.

## Threads

`ParallelGCThreads` and `ConcGCThreads` default from the visible CPU count.
On an isolated or pinned deployment the defaults can oversubscribe the
housekeeping cores or starve the collector. Record them per placement and
change them only as a measured experiment.

## Retention analysis (approval required)

1. Trend heap-after-GC from logs or JFR `jdk.GCHeapSummary`.
2. Cheapest first: `jcmd PID GC.class_histogram -all` (no forced GC; counts
   include garbage) compared at two times.
3. JFR `jdk.OldObjectSample` with `path-to-gc-roots=true` at recording end for
   leak candidates, at a modest overhead.
4. Heap dump (`jcmd PID GC.heap_dump -all FILE` avoids the forced full GC but
   includes unreachable objects) only with disk, pause, and data-handling
   approval. Analyse offline (for example Eclipse MAT) on a secured host.

## Latency-critical patterns

- Pre-allocate and reuse ring-buffer entries and codecs; verify zero allocation
  with JMH `-prof gc` and a long GC-logged soak, not a single short run.
- Avoid boxing, varargs, lambdas capturing state, iterators on hot paths, and
  `String` building in logging; confirm with an allocation profile.
- Scalar replacement (escape analysis) removes some allocations only after C2
  compiles and inlines the path; it can disappear when inlining changes.
