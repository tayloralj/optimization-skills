# Walkthrough: investigate queueing and allocation

This is a **synthetic, in-process order-handling workload**, not a production
service benchmark. It demonstrates intended-start timestamps, GC diagnostics,
allocation checks, and repeated comparison. [Real output from repeated runs](repeated-results.md)
is retained separately. No particular speedup is promised.

[`OrderGateway.java`](OrderGateway.java) offers two implementations:

- `allocating` retains strings in a boxed map.
- `zero-alloc` uses a binary buffer and primitive arrays.

Both retain recent generated order fields, but their representations and lookup
capabilities differ. A real application must test encoding, lookup, retention,
and error semantics before substituting one for the other. This demo does not
establish drop-in equivalence.

The driver replays a fixed arrival schedule on the handler thread. It records
intended start, actual start, and completion so stalls contribute to response
time. This models queued serial work; it does not exercise a network client,
independent generator, transport, overload rejection, or service deployment.

## 1. Define the question

Ask the `java-performance-investigation` skill to separate handler cost from
queueing and find evidence for the cause. Use `profiling-readiness` to determine
which captures are possible. Do not infer that a local JFR launch proves attach
permission to an existing production JVM.

## 2. Run a comparison without sampling profilers

All commands below run from the repository root. Choose a new output directory.
Both implementations use exactly the same JVM and logging flags. The program
warms up for two million operations before collecting timestamps.

```bash
install -d -m 700 build/walkthrough
javac -d build/walkthrough docs/walkthrough/OrderGateway.java
for pair in 1 2 3; do
  modes='allocating zero-alloc'
  if [ "$pair" = 2 ]; then modes='zero-alloc allocating'; fi
  for mode in $modes; do
    java -Xms64m -Xmx64m -XX:+UseG1GC \
      "-Xlog:gc*,safepoint:file=build/walkthrough/$pair-$mode.log:time,uptime,level,tags" \
      -cp build/walkthrough OrderGateway "$mode" 20 10000 "build/walkthrough/$pair-$mode.csv"
  done
  skills/java-latency-measurement/scripts/latency-report.py \
    --baseline "build/walkthrough/$pair-allocating.csv" "build/walkthrough/$pair-zero-alloc.csv"
done
```

The historical headline “2.18 ms → 55 µs” has been withdrawn: the old baseline
recorded JFR while the candidate did not. Those numbers do not isolate the code
change from profiling overhead.

Each new run contains 200,000 operations. Only about 20 observations lie beyond
p99.99; treat that percentile as indicative. For at least 100 tail observations,
use at least one million operations (100 seconds at this rate), and repeat.
Equal-count blocks within one run show episodic behavior; they are not
independent repetitions or proof against run-to-run noise.

## 3. Separate response time from service time

Response time is completion minus intended start. Service time is completion
minus actual start. Their difference is queue delay. A high response/service
ratio demonstrates waiting that service-time-only timing would omit; it does
not identify GC or any other cause by itself.

Use the `java-latency-measurement` skill to inspect the count, offered rate,
percentiles, and block spread in each report. Invalid ordering fails parsing.
Compare each pair and its variability, not only the best before/after numbers.

## 4. Collect diagnostics separately

For allocation attribution, record a separate diagnostic run:

```bash
java -Xms64m -Xmx64m -XX:+UseG1GC \
  -Xlog:gc*,safepoint:file=build/walkthrough/diagnostic-gc.log:time,uptime,level,tags \
  -XX:StartFlightRecording=settings=profile,filename=build/walkthrough/diagnostic.jfr,maxsize=256m \
  -cp build/walkthrough OrderGateway allocating 20 10000 build/walkthrough/diagnostic.csv
skills/java-flight-recorder/scripts/jfr-report.sh \
  build/walkthrough/diagnostic.jfr build/walkthrough/jfr-report --focus memory
skills/java-gc-tuning/scripts/gc-log-summary.py build/walkthrough/diagnostic-gc.log
```

Do not include this run in the unprofiled comparison. Inspect the report index:
failed views make reporting fail; unavailable views are identified separately.
An empty sampled allocation view does not prove zero allocation.

The GC log includes warmup and output writing. To claim that a particular
latency spike is GC-caused, align timestamps with the actual measurement window
and pause events. Matching maxima alone is insufficient. This demo does not
currently export the JVM-uptime boundary of that window, so do not apply a
hard-coded `--from-uptime 1.5` and call it steady state.

## 5. Check allocation directly

```bash
java -cp build/walkthrough skills/java-low-latency-patterns/scripts/AllocationProbe.java \
  'OrderGateway$AllocatingHandler' --rounds 3
java -cp build/walkthrough skills/java-low-latency-patterns/scripts/AllocationProbe.java \
  'OrderGateway$ZeroAllocHandler' --rounds 3
```

The allocating handler should return exit code 1. Under `set -e`, handle that
expected failure before continuing. Every measured round must satisfy the
allocation budget, including periodic allocations; warming up is a separate
phase. The probe covers only its calling thread, JVM, and input shape.

## 6. Decide what the evidence supports

Require semantic correctness, consistent repeated measurements, and diagnostics
that support the suspected mechanism. A zero-allocation result is not proof of
zero GC throughout an application. Remaining tail events need further evidence
from the host audit, scheduler, I/O, or JVM; do not assign them to a cause based
on an isolated maximum.
