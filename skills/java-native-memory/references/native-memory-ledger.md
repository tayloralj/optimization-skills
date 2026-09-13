# Native memory ledger

## Components and evidence

| Component | NMT category | Evidence | Controls |
| --- | --- | --- | --- |
| Java heap | Java Heap | `GC.heap_info`, GC logs | `-Xmx`, `-Xms`, `MaxRAMPercentage`, pre-touch |
| Class metadata | Class, Metaspace | `VM.metaspace`, `jdk.MetaspaceSummary` | `MaxMetaspaceSize`, fix classloader leaks |
| Compiled code | Code | `Compiler.codecache` | `ReservedCodeCacheSize` |
| Thread stacks | Thread | NMT thread count, `/proc/PID/status` Threads | `-Xss`, thread pool sizes, virtual threads |
| GC data structures | GC, GCCardSet | NMT; grows with heap and region count | collector choice, heap size |
| Compiler arenas | Compiler | NMT spikes during compilation | usually transient |
| Symbols, strings | Symbol, String Deduplication | NMT | class/String churn |
| Direct buffers | Other (malloc) | JFR `jdk.DirectBufferStatistics`; `BufferPoolMXBean` "direct" | `-XX:MaxDirectMemorySize`, pooling |
| Mapped files | not in NMT committed | `smaps_rollup` RssFile, `BufferPoolMXBean` "mapped" | windowing, `unmap` via closing arenas (FFM) |
| JNI/FFM native libs | not tracked | anon RSS minus NMT; `System.native_heap_info`; allocator profilers | library config, allocator |
| glibc fragmentation / arenas | not tracked | `System.native_heap_info` (malloc_info XML) | `MALLOC_ARENA_MAX`, trimming, jemalloc |

`Total committed` in NMT is not RSS: committed pages that were never touched do
not count toward RSS, and NMT does not see allocations made outside HotSpot.

## JDK notes

- NMT JFR events `jdk.NativeMemoryUsage` / `jdk.NativeMemoryUsageTotal` (JDK 20+)
  record categories over time when NMT is enabled.
- `jcmd PID VM.native_memory baseline` then `summary.diff` compares against a
  baseline but mutates NMT state; the snapshot script avoids it and compares
  independent summaries instead.
- `System.map` / `System.dump_map` (check `jcmd PID help`) annotate the process
  memory map with NMT information on recent JDKs.
- `System.trim_native_heap` and `-XX:TrimNativeHeapInterval=<ms>` are available
  on JDK 21+ with glibc.
- Compact object headers (JDK 25 product option) reduce heap usage, not native
  components.

## cgroup v2

- `memory.max` breach triggers the OOM killer (`memory.events` `oom_kill`);
  `memory.high` throttles reclaim first and adds latency.
- Page cache from mapped journals is charged to the cgroup and can be
  reclaimed, but reclaim under pressure stalls the writer.
- `memory.stat` separates `anon`, `file`, `kernel_stack`, `pagetables`, `sock`.
- JVM heap ergonomics use the container limit; leave headroom for everything in
  the ledger (commonly far more than 25% for thread- and buffer-heavy services —
  measure).

## Transparent huge pages

With THP `always`, sparse native allocations and thread stacks can be backed by
2 MiB pages, inflating RSS; khugepaged collapse and compaction add latency.
Check `AnonHugePages` in `smaps_rollup`. Prefer THP `madvise` plus
`-XX:+UseTransparentHugePages` for the heap only; see the
`linux-low-latency-tuning` skill.

## Leak workflow

1. Two or more snapshots under constant load show monotonic growth.
2. If an NMT category grows: enable `detail` on a replica and diff call sites.
3. If anon RSS grows beyond NMT: inspect `System.native_heap_info` arena
   growth, then profile native allocations on a replica (for example
   jemalloc profiling or an eBPF malloc tracer via the
   `linux-ebpf-io-network` skill) with approval.
4. If file-backed RSS grows: list mappings (`/proc/PID/maps`, privately) and
   verify mapped files are closed/unmapped as intended.
