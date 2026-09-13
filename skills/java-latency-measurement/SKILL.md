---
name: java-latency-measurement
description: Measure Java latency correctly - open-loop load, coordinated omission, HdrHistogram, percentiles and sample counts, and host jitter. Use before trusting a latency number, when designing a latency test, or when comparing tail latency between builds or hosts.
---

# Java Latency Measurement

A latency number is only as good as its load model and timestamps. Establish
measurement validity before any tuning skill uses the result.

## Workflow

1. **State the question and load model.** Fixed-rate latency uses an
   open-loop generator with a schedule of intended send times. Maximum
   sustainable throughput is found by stepping fixed rates until the SLO
   fails. Closed-loop "send next when previous returns" runs understate tail
   latency (coordinated omission) and are only valid for batch throughput.
2. **Timestamp correctly.** Record, per operation, `intended_start`,
   `actual_start`, and `end` from one monotonic clock (`System.nanoTime` within
   a process). Response time = end − intended start. Across hosts use
   synchronized clocks (PTP/chrony) and state their error bound.
3. **Record without distorting.** Use HdrHistogram (or equivalent) with a
   pre-sized range and precision; record in the hot path without allocation;
   write interval logs so time series and merged totals are both available.
   Never average percentiles across intervals or hosts — merge histograms.
4. **Check the generator.** Pin and isolate it from the system under test,
   confirm achieved send rate equals intended rate, and watch its own
   latency (a saturated generator produces a fake plateau).
5. **Baseline the platform.** Run `scripts/JitterMeter.java` on the intended
   hot CPU (`--mode spin`) and for blocking threads (`--mode sleep`) to learn
   the host's noise floor before attributing latency to the application.
6. **Analyse.** For CSV timestamps run `scripts/latency-report.py run.csv
   [--baseline base.csv]`: response vs service time, queue delay, the p99
   response/service ratio (coordinated omission indicator), rate checks, and
   per-block p99 spread for stability. Input timestamps must be integer nanoseconds
   with intended start <= actual start <= end. Invalid rows fail the report;
   percentiles with fewer than 100 tail observations are labelled indicative. Read `references/methodology.md` for
   sample-size and comparison rules.
7. **Correlate spikes** with JVM and OS timelines: GC/safepoint logs (the
   `java-gc-tuning` skill), JFR events, interrupts and run-queue delay (the
   `linux-low-latency-tuning` and `linux-ebpf-io-network` skills).
8. **Report** full distributions (p50 … p99.99, max) with counts, rate,
   duration, warmup excluded, repetitions, host and JVM details, and the
   spread across runs. Keep throughput and latency claims separate.

## Guardrails

- JMH `SampleTime` mode is closed-loop per thread; do not present it as a
  service latency distribution.
- A percentile needs enough samples: p99.99 needs far more than 10,000
  operations, and a single run's max is an anecdote, not a statistic.
- Warmup (JIT, caches, page faults) must be excluded explicitly and reported;
  do not silently drop "outliers".
- `System.currentTimeMillis` and `Instant.now` are wall clocks subject to
  adjustment; use them only for correlation, not durations.
- Latency datasets can include customer identifiers; strip before sharing.
