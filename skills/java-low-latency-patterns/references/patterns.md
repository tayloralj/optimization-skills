# Low-latency Java patterns

Code targets JDK 21/25. Each pattern lists the evidence that justifies it and
how to verify it (see `verification.md`).

## 1. Allocation-free hot paths

Evidence: allocation samples on hot threads (JFR `allocation-by-site`,
async-profiler `alloc`), young GCs during steady state.

| Common source of garbage | Replacement |
| --- | --- |
| Boxing (`Map<Long, X>`, `List<Integer>`, generic callbacks) | Primitive collections (Agrona `Long2ObjectHashMap`, fastutil, Eclipse Collections) |
| Capturing lambdas and method references | Pre-built instances held in fields; non-capturing lambdas |
| Iterators / enhanced `for` over collections | Indexed loops over arrays or `ArrayList` |
| `String` concatenation, `String.format`, logging arguments | Append into a reused `StringBuilder`/byte buffer; garbage-free or binary logging |
| Varargs | Fixed-arity overloads |
| Per-event message objects | Pre-allocated, reused event instances (ring-buffer entries) |
| `Optional`, streams on the hot path | Plain branches and loops |
| Exceptions for control flow | Return codes; if unavoidable, a preallocated exception with `writableStackTrace=false` |
| `ByteBuffer.allocate` / `wrap` per message | One buffer per thread or connection, reset with `clear()` |
| A new "no result" record or object per call (`return new Result(false, ...)`) | A shared immutable constant for the common outcome |
| NIO `Selector.selectedKeys()` iteration (an iterator per poll and a set node per ready key) | `selector.select(Consumer, timeout)` / `selectNow(Consumer)` (JDK 11+), collecting keys into a reused array if dispatch must stay separate from the poll |

Escape analysis can remove some allocations after C2 compiles and inlines the
code, but it is fragile; verify with the probe instead of relying on it.

## 2. Single writer and ring buffers

Evidence: lock contention, CAS retry loops, or cache-line ping-pong between
threads that update the same state.

Principle: exactly one thread mutates each piece of state; other threads
communicate with it through a queue. Use a maintained implementation
(LMAX Disruptor, JCTools `SpscArrayQueue`/`MpscArrayQueue`, Agrona
`ManyToOneRingBuffer`). The sketch below shows the idea for review purposes:

```java
/** Single-producer single-consumer ring of longs. Producer calls offer(), consumer calls poll(). */
final class SpscLongRing {
    private final long[] buffer;
    private final int mask;
    private final AtomicLong tail = new AtomicLong(); // written only by the producer
    private final AtomicLong head = new AtomicLong(); // written only by the consumer

    SpscLongRing(int capacityPowerOfTwo) {
        if (Integer.bitCount(capacityPowerOfTwo) != 1) throw new IllegalArgumentException("power of two");
        buffer = new long[capacityPowerOfTwo];
        mask = capacityPowerOfTwo - 1;
    }

    boolean offer(long value) {
        long t = tail.get();
        if (t - head.get() == buffer.length) return false;   // full (a stale head only looks fuller)
        buffer[(int) (t & mask)] = value;
        tail.lazySet(t + 1);                                  // publish after the element is written
        return true;
    }

    boolean poll(LongConsumer consumer) {
        long h = head.get();
        if (h == tail.get()) return false;                    // empty (a stale tail only looks emptier)
        consumer.accept(buffer[(int) (h & mask)]);
        head.lazySet(h + 1);
        return true;
    }
}
```

Production versions add cache-line padding around the indices (see the
`java-cache-efficiency` skill), cache the other side's index to avoid reading
a volatile on every call, and batch-drain. The `lazySet` publication pattern
is the one JCTools uses; any variant must pass a JCStress test.

Smart batching: the consumer drains everything available, processes it as a
batch (one flush, one syscall), then waits. Batch size grows under load and
shrinks to one when idle, so latency stays low at both ends.

## 3. Wait strategies

Evidence: wake-up latency (sleep/park overshoot in `JitterMeter --mode sleep`,
run-queue delay in eBPF) dominates the tail.

| Strategy | Latency | CPU | Use when |
| --- | --- | --- | --- |
| Busy spin with `Thread.onSpinWait()` | Lowest | 100% of a core | Dedicated, isolated core; strict tail budget |
| Spin → yield → park backoff (Agrona `BackoffIdleStrategy`) | Low when busy, higher after idle | Adaptive | Bursty traffic, shared cores |
| `LockSupport.parkNanos` / blocking queue | Highest (scheduler + timer slack) | Minimal | Throughput or background work |

```java
while (running) {
    int work = pollAndProcessBatch();
    if (work == 0) {
        Thread.onSpinWait();   // CPU pause hint; cost differs between CPU models
    }
}
```

Never busy-spin on a CPU shared with the threads that feed it.

## 4. Flyweight binary encoding

Evidence: serialization frames (JSON/reflection/protobuf object building) or
copying dominate CPU or allocation profiles.

Encode directly into a reused buffer at fixed offsets (the SBE model). The
flyweight is a view: it holds a buffer and an offset, and has no per-message
allocation.

```java
final class OrderFlyweight {
    static final int SIZE = 24;
    private static final VarHandle LONG =
        MethodHandles.byteArrayViewVarHandle(long[].class, ByteOrder.LITTLE_ENDIAN);
    private static final VarHandle INT =
        MethodHandles.byteArrayViewVarHandle(int[].class, ByteOrder.LITTLE_ENDIAN);
    private byte[] buffer;
    private int offset;

    OrderFlyweight wrap(byte[] buffer, int offset) { this.buffer = buffer; this.offset = offset; return this; }
    OrderFlyweight orderId(long v)  { LONG.set(buffer, offset, v); return this; }
    long orderId()                  { return (long) LONG.get(buffer, offset); }
    OrderFlyweight priceTicks(long v) { LONG.set(buffer, offset + 8, v); return this; }
    long priceTicks()               { return (long) LONG.get(buffer, offset + 8); }
    OrderFlyweight quantity(int v)  { INT.set(buffer, offset + 16, v); return this; }
    int quantity()                  { return (int) INT.get(buffer, offset + 16); }
}
```

Use fixed-point integers (price in ticks) instead of `BigDecimal` or `double`
where the domain allows. Generate flyweights from a schema (SBE) for anything
beyond a handful of messages, and fuzz decoders against malformed input.

## 5. Off-heap memory with the FFM API

Evidence: large, long-lived data sets inflate GC work, or data must be shared
with native code or memory-mapped files.

```java
// JDK 22+ final API; on JDK 21 compile and run with --enable-preview.
try (Arena arena = Arena.ofConfined()) {
    MemorySegment prices = arena.allocate(ValueLayout.JAVA_LONG, 1_000_000);
    prices.setAtIndex(ValueLayout.JAVA_LONG, 42, 101_250L);
    long p = prices.getAtIndex(ValueLayout.JAVA_LONG, 42);
}   // memory freed deterministically here
```

- `Arena.ofConfined()` for single-thread lifetimes, `ofShared()` when several
  threads access the segment, `ofAuto()` for GC-managed lifetime.
- Mapped files: `FileChannel.map(MapMode.READ_WRITE, 0, size, arena)` returns a
  `MemorySegment`; pre-touch pages before the hot path uses them.
- Bounds checks are usually hoisted by C2 in loops; verify with JMH.
- Account for off-heap memory in container limits (the `java-native-memory` skill).

## 6. Time and logging

- `System.nanoTime` is cheap only with the TSC clocksource (check with the
  `linux-low-latency-tuning` audit). For per-event wall-clock stamps, a cached
  clock updated by the event loop or a timer thread (Agrona `CachedEpochClock`)
  avoids a clock read per event.
- Logging on the hot path must be garbage-free and non-blocking: write
  fixed-layout binary records or pre-formatted bytes to a ring buffer drained
  by a background thread; never synchronous file or console I/O.

## 7. Data layout and code shape

- Arrays of primitives (struct-of-arrays) beat arrays of objects for scans:
  fewer pointers, better prefetching.
- Keep hot methods small so they inline; move rare branches (errors, resizing,
  logging) into separate methods.
- Keep hot call sites monomorphic; see the `java-jit-codegen` skill.
- Avoid `synchronized` and `ReentrantLock` on the hot path; if a lock is
  unavoidable, measure hold time and contention with JFR.

## 8. Threads

- Platform threads for latency-critical loops; virtual threads suit blocking
  I/O fan-out, not spinning or pinned work.
- Name every thread; pin hot ones deliberately; keep GC and JIT threads on
  housekeeping cores.
