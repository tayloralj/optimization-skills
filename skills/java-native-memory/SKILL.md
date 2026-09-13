---
name: java-native-memory
description: Explain and control JVM resident memory beyond the Java heap on Linux for JDK 21 and 25 - Native Memory Tracking, metaspace, code cache, thread stacks, GC structures, direct and mapped buffers, glibc malloc arenas and trimming, JNI and FFM native libraries, transparent huge pages, and cgroup v2 limits and OOM kills. Use when RSS or container memory grows while the heap looks stable, when a JVM is OOM-killed, when sizing memory limits, or when off-heap buffers, memory-mapped journals, or native libraries are suspected.
---

# Java Native Memory

RSS is not heap. Build a ledger that accounts for every large component before
changing limits or flags.

## Workflow

1. **Frame the symptom**: steady growth (leak), step growth (warmup, buffer
   pools, arenas), spikes (bursts), or a limit breach (cgroup OOM kill). Record
   `-Xmx`, container `memory.max`, JDK, collector, and uptime.
2. **Enable NMT on a controlled launch** where possible:
   `-XX:NativeMemoryTracking=summary` (small overhead; `detail` adds call
   sites and more overhead). It cannot be enabled on a running JVM.
3. **Snapshot twice** at steady state, separated by the growth interval:

   ```bash
   scripts/native-memory-snapshot.sh PID ./nm-t0
   scripts/native-memory-snapshot.sh PID ./nm-t1
   scripts/nmt-compare.py ./nm-t0 ./nm-t1
   ```

   The snapshot is read-only: `/proc` status and `smaps_rollup`, cgroup memory
   files, NMT summary, `GC.heap_info`, `VM.metaspace`, `Compiler.codecache`, and
   glibc `System.native_heap_info` when available. It refuses other users'
   processes and existing output directories.
4. **Build the ledger** with `references/native-memory-ledger.md`: heap
   committed, metaspace/class space, code cache, thread stacks × threads, GC
   structures, symbols/arenas, direct buffers, mapped files, and the remainder
   not tracked by NMT (malloc from native libraries, allocator fragmentation).
5. **Localise growth**: an NMT category that grows → the owning JVM subsystem;
   anon RSS growth beyond NMT → native allocator or libraries; file-backed RSS →
   mapped files (usually reclaimable page cache, but counted by cgroups).
6. **Change one factor** (thread count, direct-buffer cap, arena count,
   metaspace leak fix, mapped-file windowing) with approval for launch changes,
   and re-snapshot under the same load.

## Low-latency specifics

- Memory-mapped journals and `MappedByteBuffer`/`MemorySegment` files show up
  as file-backed RSS and page-cache pressure; major faults on first touch add
  latency. Pre-fault (touch or `madvise`-style warming) during startup and
  watch `majflt` for the hot threads.
- Pre-size and reuse direct buffers; each `ByteBuffer.allocateDirect` reserves
  against `MaxDirectMemorySize` and, when exhausted, can trigger `System.gc()`.
- Thread stacks are committed lazily; many pinned or busy-spinning threads
  still cost stack plus per-thread malloc arenas.

## Guardrails

- `System.trim_native_heap` and `-XX:TrimNativeHeapInterval` return glibc
  memory to the OS at a CPU and possible latency cost; treat as an experiment.
- `MALLOC_ARENA_MAX` or an alternative allocator (jemalloc via `LD_PRELOAD`)
  changes allocation behaviour process-wide; test throughput and tail latency,
  and pin the allocator version.
- `VM.native_memory detail`, `System.map`/`System.dump_map`, and heap dumps can
  reveal library paths and data; store privately. Check `jcmd PID help` first:
  some commands are absent on JDK 21.
- Never raise a container limit to hide unexplained growth; identify the owner.
