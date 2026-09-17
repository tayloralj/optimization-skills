---
name: java-linux-perf
description: Profile JVM workloads with Linux perf using working JIT symbols, portable events, and bounded captures. Use when perf stat, record, report, or c2c is requested for a Java service or benchmark.
---

# Java Linux perf

Use `perf` only after the `profiling-readiness` skill proves the intended collection is
possible. Do not treat a JAR like an ELF binary.

## Workflow

1. Classify the workload: fixed-rate latency, maximum sustainable throughput,
   batch completion, or mixed service load. Never compute a throughput scaling
   factor from a deliberately fixed-rate run.
2. Record JDK, kernel, perf, CPU vendor/model, SMT, NUMA and LLC-domain topology,
   JVM flags, application commit, warmup, and workload parameters.
3. Run `perf list` and smoke-test the exact event on a short self-owned process.
   Use portable events first. Select raw or model-specific events only from the
   installed tool or an authoritative event list for that CPU.
4. Choose symbolization using `references/java-symbols.md`. Do not use `ldd`,
   `nm`, `objdump --dwarf`, or missing native DWARF to judge Java bytecode debug
   quality. `javap -c -l` checks Java line tables but not live JIT symbols.
   After exporting a text report, use the vendor skill's
   `validate-symbols.py` check to require representative Java methods and
   reject unresolved frames before interpreting hotspots.
5. Capture a bounded steady-state interval. Prefer per-process and user-space
   collection; avoid `-a` unless system-wide evidence is required and approved.
6. Interpret samples together with JIT/GC/safepoint state, multiplexing, CPU
   placement, and run variance. Confirm hot source and benchmark fidelity.
7. Apply one change and repeat the same unprofiled performance test.

## Commands

Use only events shown by this host:

```bash
perf list
pid=1234  # replace only after confirming the warm target process
perf stat -p "$pid" -e task-clock,context-switches,cpu-migrations -- sleep 30
perf record -o ./profiles/perf.data -F 199 -e cycles:u \
  --call-graph dwarf,8192 -p "$pid" -- sleep 30
perf report -i ./profiles/perf.data
```

The call-graph mode is workload/JDK/tool dependent. Frame pointers may reduce
overhead when the complete stack is built for them; DWARF alone does not create
JIT method names. Ensure the output directory has a size budget, compare the
application metric with and without recording, and inspect lost samples and
stack truncation. Read `references/java-symbols.md` before recording.

For startup or finite batch work, wrapping `java -jar ...` can be valid because
startup is part of that metric. Do not use that form as a steady-state service
example.

For a guided bounded launch, use `scripts/java-perf-capture.sh --out DIR
--duration SEC [--cpus LIST] [--record] -- java-command...`. It records host,
JDK-independent workload output, perf policy, portable user counters, and an
optional call-graph recording in a private directory; a nonzero workload or
perf exit is a failed capture.

## c2c and Java objects

`perf c2c` can identify cache-line contention, but a reported address/offset is
not definitive proof of a Java field or ownership pattern. Combine it with JOL
or validated object layout, allocation/site evidence, thread ownership, and a
controlled padding/placement experiment. Account for GC movement.
