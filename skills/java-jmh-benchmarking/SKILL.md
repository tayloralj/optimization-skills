---
name: java-jmh-benchmarking
description: Design, audit, run, and interpret trustworthy JMH benchmarks for Java optimizations. Use when creating a microbenchmark, checking that an existing benchmark still models production code, avoiding dead-code and state-scope errors, separating setup activity from measured score, collecting reproducible JSON results, or comparing a baseline and candidate with uncertainty.
---

# Java JMH Benchmarking

Treat benchmark fidelity as the first test. A statistically tidy benchmark of
obsolete code is worse than no benchmark because it produces confident noise.

## Workflow

1. Identify the exact production method, data structure, concurrency contract,
   input distribution, and output side effect being modelled.
2. Complete `references/fidelity-checklist.md`. Link the benchmark to the
   production revision and reject stale stand-ins before running JMH.
3. Choose state scope, threads, parameters, mode, time unit, forks, warmup, and
   measurement from the production question. There is no universal minimum of
   five iterations; demonstrate stabilization and adequate sample time.
4. Prevent elimination with a returned value or `Blackhole` only where needed.
   A `void` benchmark with observable state mutation can be valid; inspect the
   generated/compiled behaviour instead of applying a slogan.
5. Run multiple forks and emit JSON. Use `scripts/capture-environment.sh` beside
   the result. Control CPU placement/governor only with explicit operator
   approval and record the setting.
6. Use low-overhead JMH secondary profilers such as `-prof gc` symmetrically
   after checking their overhead. Run sampling profilers such as async-profiler,
   JFR, or perf as separate diagnostics; quote arguments containing semicolons
   and do not use their scores as the final comparison.
7. Compare effect size, fork-to-fork variance, confidence intervals, GC metrics,
   and service-level relevance. Interval overlap is a conservative heuristic,
   not a hypothesis test or proof of equivalence.

## Setup semantics

JMH invokes setup/teardown hooks outside the timed benchmark method. However,
`Level.Invocation` can add substantial harness overhead and its allocations or
GC activity can pollute profiler and secondary-counter observations. Use it only
when per-invocation reset is essential, and validate with generated harness code
or a control benchmark.

Timer exclusion is a score semantic, not proof that reset/fixture work is
irrelevant. If production must perform that work per operation, measure and
report its wall cost separately or include it in an end-to-end benchmark.

## Output requirements

Report the JDK/JMH versions, JVM flags, commit, host/topology, full JMH command,
forks, warmup and measurement durations, parameters, units, raw JSON, variance,
and known environmental limitations. Keep maximum-throughput tests separate
from fixed-rate tail-latency tests.

Read `references/build-setup.md` when creating a new executable benchmark.
