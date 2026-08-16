# Vendor and JVM interpretation

## Vendor routing

Use `lscpu` or `/proc/cpuinfo` to identify the vendor and model, then confirm the
installed profiler explicitly supports them. Analysis labels that sound similar
can use different PMU events and formulas. Never translate an Intel top-down
ratio or raw event code directly to AMD Zen.

Use only analysis names shown by the installed CLI. Vendor releases change
commands, drivers, kernel support, and Java integration. When installation or
driver changes are needed, link the current official vendor documentation and
hand the action to an administrator; the skill must not install or load drivers.

## JVM context

- Warm to the relevant tiered-compilation state before steady-state collection.
- Preserve JIT method and line attribution according to the installed profiler
  and JDK documentation.
- Correlate hotspots with JFR or JVM logs for GC, safepoints, compilation, and
  deoptimization where useful.
- Account for attach/sampling overhead, containers, frequency changes, SMT, CPU
  migration, and multiplexed counters.
- Treat a single run as exploratory. Repeat, include a control, and verify the
  final change without profiler overhead.

## Thresholds

Do not label a cache-miss, front-end, back-end, branch, IPC, or memory-bandwidth
percentage “good” or “bad” in isolation. Compare against a stable baseline,
known workload phase, achieved throughput/latency, frequency, and the CPU
vendor/model's documented metric meaning.
