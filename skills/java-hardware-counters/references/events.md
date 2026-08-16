# Counter experiment reference

## Portable starting point

When listed and permitted, begin with a small group such as:

```bash
perf stat -e cycles:u,instructions:u,branches:u,branch-misses:u \
  -p PID -- sleep 20
```

Add cache or stall events only after `perf list` confirms their exact meaning on
the host. Use grouping carefully: too many simultaneous events cause
multiplexing or scheduling failure. Record `time enabled` and `time running`;
low running fractions increase uncertainty.

## Experimental confounders

- JVM warmup, compilation, deoptimization, GC, safepoints, and class loading
- SMT sibling activity, CPU migration, interrupts, frequency and thermal state
- containers/cgroups, co-tenants, NUMA/LLC placement, and page faults
- sampling skid, PEBS/IBS differences, event errata, and kernel/tool versions
- profiler overhead and event multiplexing

## Ratios

Compute ratios only when numerator and denominator represent the same interval
and were scheduled compatibly. Report raw counts and workload output alongside
derived IPC, miss rate, or MPKI. A ratio change can be caused by the denominator;
inspect both terms.

For raw/model-specific events, cite the authoritative event source for the
detected CPU family/model and record the encoding. If the event meaning cannot
be established, do not use it.
