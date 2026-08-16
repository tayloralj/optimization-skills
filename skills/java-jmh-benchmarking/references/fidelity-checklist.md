# Benchmark fidelity checklist

Complete this before interpreting results.

## Production mapping

- Record the production repository, commit, class, method, and relevant lines.
- Record the benchmark repository, commit, class, and method.
- Diff the algorithm and data structures. Check pools, primitive collections,
  locks, queue type/capacity, batching, copying, clocks, I/O, and error paths.
- Verify the concurrency contract: single writer, multi-writer, readers, thread
  ownership, and contention. `@State` scope and `@Threads` must model it.
- Verify input sizes, key distributions, hit/miss ratios, ordering, payloads,
  allocation lifetime, and cache warmness against observed production data.
- Verify outputs and side effects remain observable.
- Identify omitted costs such as serialization, JNI/Panama calls, journal I/O,
  transport, backpressure, repair traffic, GC, and coordination.

If a material mapping fails, update or replace the benchmark before using it.

## Experimental controls

- Include a control benchmark that measures harness/setup cost when relevant.
- Confirm warmup stabilization rather than relying on a fixed iteration slogan.
- Use enough forks to expose process/JIT variance.
- Randomize or alternate baseline/candidate order when thermal drift matters.
- Keep fixed-rate latency and saturation throughput as separate experiments.
- Save raw JSON and environment metadata; do not report only a rounded mean.

## Interpretation

JMH score excludes setup hooks, but profilers and GC counters can still observe
their activity. Allocation rate is not retained heap. A microbenchmark effect
does not establish service throughput or tail-latency impact; verify the winning
candidate in an integration or representative load test.
