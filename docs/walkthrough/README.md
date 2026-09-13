# Walkthrough: tracing a p99.99 latency spike to garbage collection

This walkthrough follows one realistic problem from "the tail latency is bad"
to a verified fix, using the skills and their scripts. Every number below comes
from real runs on the development machine (AMD Ryzen 9 7900, Linux 7.0,
Temurin JDK 25.0.2). Your numbers will differ; the shape of the story will not.

The demo program, [`OrderGateway.java`](OrderGateway.java), handles orders
at a fixed rate of 10,000 per second on one thread. It has two handlers doing
the same logical work:

- `allocating`: builds a `String` per order and keeps the last 200,000 orders
  in a `LinkedHashMap<Long, String>`, which is typical first-draft code.
- `zero-alloc`: encodes each order into a reused byte buffer and keeps recent
  orders in primitive arrays.

It records when each order *should* have started, when it actually started,
and when it finished, so queueing behind a pause is counted.

## 0. Build and run the "before" version

All commands run from the repository root.

```bash
javac -d build/walkthrough docs/walkthrough/OrderGateway.java
java -Xms64m -Xmx64m -XX:+UseG1GC \
     -Xlog:gc*,safepoint:file=build/walkthrough/before-gc.log:time,uptime,level,tags \
     -XX:StartFlightRecording=settings=profile,filename=build/walkthrough/before.jfr \
     -cp build/walkthrough OrderGateway allocating 20 10000 build/walkthrough/before.csv
```

## 1. Describe the symptom

> **You:** Our order gateway's p99.99 latency is in milliseconds but the handler
> itself is fast. Where do I start?

The agent loads **`java-performance-investigation`**. It asks for the target
(for example "p99.99 below 100 µs at 10k orders/s"), classifies this as a
*fixed-rate latency* problem, and, following its low-latency order, checks
measurement validity first, then JVM pauses.

## 2. Check that the latency numbers are real

> **You:** Here is before.csv with intended start, actual start and end times.

The agent loads **`java-latency-measurement`** and runs:

```bash
skills/java-latency-measurement/scripts/latency-report.py build/walkthrough/before.csv
```

```text
response_time: n=200000 p50=108ns p90=193ns p99=502ns p99.9=67.736us p99.99=2.184ms max=2.943ms
service_time : n=200000 p50=90ns  p90=171ns p99=451ns p99.9=8.606us  p99.99=21.781us max=2.943ms
queue_delay  : n=200000 p50=16ns  p90=29ns  p99=39ns  p99.9=47.260us p99.99=2.084ms max=2.843ms
response/service ratio: p99=1.11 p99.9=7.87 p99.99=100.27  <- queueing at p99.99: service-time-only reporting would hide this
```

**How to read it.** *Service time* is how long the handler ran. *Response
time* includes waiting in line. At p99.99 the handler took 22 µs, but orders
waited 2 ms. A benchmark that timed only the handler (a closed-loop test)
would have reported 22 µs and missed the problem entirely. That hidden wait is
called *coordinated omission*. Something is periodically stopping the thread.

## 3. Is the JVM pausing?

> **You:** What is stopping the thread?

The agent loads **`java-gc-tuning`** and summarises the GC log, first for the
whole run and then after warmup (`--from-uptime`) so startup does not
dominate:

```bash
skills/java-gc-tuning/scripts/gc-log-summary.py --top 3 build/walkthrough/before-gc.log
skills/java-gc-tuning/scripts/gc-log-summary.py --top 3 --from-uptime 1.5 build/walkthrough/before-gc.log
```

```text
# whole run
pauses_ms: n=129 sum=431.679 p50=2.198 p90=5.906 p99=20.167 max=21.707
  Pause Full (G1 Compaction Pause): n=7 ... max=21.707
alarms:
  evacuation_failure: 13
  full_gc: 7

# steady state only (after 1.5 s of uptime)
pauses_ms: n=18 sum=21.333 p50=0.908 p90=2.717 p99=2.808 max=2.808
worst_pauses:
  2.808 ms GC(109) Pause Young (Prepare Mixed) (G1 Evacuation Pause) uptime=5.742
  2.717 ms GC(115) Pause Young (Concurrent Start) (G1 Evacuation Pause) uptime=17.349
```

**How to read it.** During warmup the small heap overflowed (full GCs,
evacuation failures). In steady state there are still 18 pauses of up to
2.8 ms, which matches the 2–3 ms queue delay in step 2. The agent's
conclusion: GC pauses explain the tail. It also suggests the cheapest fix is
to allocate less, not to tune GC flags.

## 4. Who is allocating?

> **You:** Which code is producing the garbage? I don't have root on this box.

No root is needed. The agent loads **`java-flight-recorder`** and renders the
recording made in step 0:

```bash
skills/java-flight-recorder/scripts/jfr-report.sh build/walkthrough/before.jfr build/walkthrough/jfr-before --focus memory
```

```text
Allocation by Site
Method                                                         Allocation Pressure
jdk.internal.misc.Unsafe.allocateUninitializedArray(Class, int)     62.36%   <- String bytes
java.util.LinkedHashMap.newNode(int, Object, Object, HashMap$Node)  26.82%   <- map entries
java.lang.String$$StringConcat...concat(long, long, int, Object)     2.80%
java.lang.Long.valueOf(long)                                         2.32%   <- boxing
```

**How to read it.** Over 90% of allocation comes from building strings, map
entries, and boxed `Long` keys, all in the handler.

## 5. Fix the hot path and prove it allocates nothing

> **You:** Rewrite the handler so it does not allocate.

The agent loads **`java-low-latency-patterns`**, replaces the string and map
with a fixed-layout buffer and primitive arrays (the `zero-alloc` handler), and
proves the result with the allocation probe, which exits non-zero if the hot
path allocates:

```bash
java -cp build/walkthrough skills/java-low-latency-patterns/scripts/AllocationProbe.java 'OrderGateway$AllocatingHandler' --rounds 3
java -cp build/walkthrough skills/java-low-latency-patterns/scripts/AllocationProbe.java 'OrderGateway$ZeroAllocHandler' --rounds 3
```

```text
class=OrderGateway$AllocatingHandler
bytes_per_op_by_round=151.6000,151.6000,151.6000
result=FAIL (threshold 0.0000 bytes/op on the last round)

class=OrderGateway$ZeroAllocHandler
bytes_per_op_by_round=0.0000,0.0000,0.0000
result=PASS (threshold 0.0000 bytes/op on the last round)
```

## 6. Verify with the same test

```bash
java -Xms64m -Xmx64m -XX:+UseG1GC \
     -Xlog:gc*,safepoint:file=build/walkthrough/after-gc.log:time,uptime,level,tags \
     -cp build/walkthrough OrderGateway zero-alloc 20 10000 build/walkthrough/after.csv
skills/java-latency-measurement/scripts/latency-report.py --baseline build/walkthrough/before.csv build/walkthrough/after.csv
skills/java-gc-tuning/scripts/gc-log-summary.py --from-uptime 1.5 build/walkthrough/after-gc.log
```

```text
vs_baseline (response time, candidate/baseline):
  p50: 108ns -> 57ns (0.528x)
  p99: 502ns -> 97ns (0.193x)
  p99.9: 67.736us -> 3.276us (0.0484x)
  p99.99: 2.184ms -> 55.261us (0.0253x)
  max: 2.943ms -> 171.343us (0.0582x)
  p99 blocks above baseline block range: 0/10; below: 10/10

pauses_ms: n=0  (no pauses in this window)
```

**Result.** p99.99 fell from 2.18 ms to 55 µs, and there were no GC pauses in
steady state. Every one of the ten time blocks improved, so this is a real
shift rather than one lucky interval.

**Runs vary, so repeat them.** A second pair of runs on the same machine gave
a worse "before" (p99.99 23.9 ms, including a 23 ms full GC after warmup) and
a better "after" (p99.99 4.4 µs, still no pauses). The conclusion held; the
exact numbers did not. Compare several runs of each version before quoting a
figure.

Note: step 5's first probe command exits with status 1 on purpose, which is
how it fails a CI build. If you paste the steps into a script with `set -e`,
that is where it stops.

## 7. What is left

The remaining 55 µs p99.99 and 171 µs max are not GC. The next step would be
the platform: run the `linux-low-latency-tuning` audit and the jitter meter on
the CPU the thread runs on (see [examples](../examples.md#host-jitter-audit)).
On this untuned desktop the audit reports 15 device IRQs, a 1,468/s timer tick,
and 350 µs C3 idle exits on candidate CPUs: plausible causes to measure next,
not yet proven ones.

## What this walkthrough shows

- Measure from the intended start time, or the tail is invisible.
- Correlate latency with JVM evidence before tuning anything.
- JFR answers "who allocates" without root or extra tools.
- Prove a fix twice: a targeted check (allocation probe) and the original
  end-to-end test with the same load.
