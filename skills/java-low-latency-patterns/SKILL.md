---
name: java-low-latency-patterns
description: Write and review low-latency Java - allocation-free hot paths, single-writer ring buffers, wait strategies, flyweight binary encoding, off-heap memory with the FFM API, and JCStress correctness checks. Use when building or reviewing Disruptor, Aeron, or Agrona-style code, or when removing garbage and jitter from a hot path.
---

# Java Low-Latency Patterns

Low-latency Java is mostly about what the hot path does *not* do: allocate,
block, share writes, take locks, call the OS, or wander through pointers. This
skill turns that into concrete code patterns and a way to prove each one.

## Workflow

1. **Define the hot path**: the exact thread(s) and call chain from event
   arrival to output, its latency budget, and its threading contract (single
   writer? how many readers?). Everything else is the cold path.
2. **Measure first** with the `java-latency-measurement` skill (valid
   percentiles) and find the cause with the `java-flight-recorder`,
   `java-async-profiler`, or `java-gc-tuning` skills. Do not apply patterns
   blindly.
3. **Pick the pattern** from `references/patterns.md` that matches the evidence:
   garbage → zero-allocation techniques; contention → single-writer and
   ring buffers; wake-up latency → wait strategies; encoding cost → flyweights;
   GC pressure from large data → off-heap segments; clock/log cost → cached
   clocks and binary logging.
4. **Prove it** with `references/verification.md`:
   - zero allocation: `java -cp CLASSES scripts/AllocationProbe.java com.example.HotPath`
     (exit code gates CI), plus JMH `-prof gc`;
   - concurrency correctness: a JCStress test for any hand-written concurrent
     structure;
   - latency: before/after histograms under the same open-loop load;
   - stability: a long soak with GC logging showing no steady-state collections.
5. **Keep it maintainable**: isolate low-level code behind small, tested
   components; document the threading contract in the type's Javadoc; prefer a
   maintained library (Disruptor, Agrona, JCTools, SBE) over a private copy.

## Defaults for a latency-critical service

- Steady-state allocation of zero bytes per event on hot threads; warm up with
  representative data before accepting traffic.
- One writer per piece of mutable state; hand-offs through bounded
  single-producer or multi-producer ring buffers; batch on the consumer side.
- Hot consumer threads pinned to isolated CPUs with a busy-spin or backoff
  wait strategy (placement via the `linux-low-latency-tuning` skill).
- Binary encoding with flyweights over reused buffers; no reflection-based
  serialization on the hot path.
- A cached clock for timestamps where microsecond staleness is acceptable;
  `System.nanoTime` only where exact intervals matter.

## Guardrails

- Every pattern here trades simplicity for latency. Apply it only where a
  measurement shows the need, and keep a simpler path for cold code.
- Hand-written lock-free code is guilty until JCStress proves it; prefer
  libraries.
- JDK 21: the FFM API (`java.lang.foreign`) is a preview feature and needs
  `--enable-preview`; it is final from JDK 22. The Vector API is incubating on
  both 21 and 25.
- Busy-spinning burns a whole core per thread; plan capacity and power.
- `sun.misc.Unsafe` memory access is deprecated for removal in recent JDKs;
  use `VarHandle` and `MemorySegment` in new code.
