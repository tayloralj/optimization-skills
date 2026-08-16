---
name: java-hardware-counters
description: Design and interpret portable Java PMU and hardware-counter experiments across Intel and AMD Linux hosts. Use for cycles, instructions, cache, branch, stalled-cycle, memory, PEBS, IBS, perf, PCM, PAPI, or LIKWID questions where event availability, permissions, multiplexing, SMT, frequency, JIT attribution, and same-host baselines must be checked before drawing conclusions.
---

# Java Hardware Counters

Counters are model-specific observations. Start with `$profiling-readiness`,
then build a minimal event set for one hypothesis.

## Workflow

1. Record CPU vendor, family/model, microcode, kernel, perf/tool version, SMT,
   frequency/governor, NUMA/LLC topology, JDK, JVM flags, and workload phase.
2. Classify the workload and metric. Do not use a fixed request rate to infer
   throughput scaling.
3. List events on this host (`perf list` or the installed vendor tool). Begin
   with portable events and `:u` when user-space data is sufficient.
4. Smoke-test each event for a few seconds. Reject unsupported, zero, permission
   denied, or heavily multiplexed measurements.
5. Keep event groups small. Save raw counts, time enabled/running, repetitions,
   application throughput/latency, CPU frequency, and placement.
6. Attribute samples with Java/JIT-aware symbols. Counts without attribution
   can compare runs but rarely identify source by themselves.
7. Compare a control, baseline, and candidate on the same host. Interpret
   ratios using the CPU vendor/model documentation and `references/events.md`.

For production attachment, obtain operator approval, verify PID identity/UID
and process start time before and after the bounded interval, protect the output,
and handle target exit or PID reuse explicitly. Record that `:u` intentionally
excludes kernel execution, which may omit relevant syscall, network, or journal
work.

## Guardrails

- Never paste a raw event code from a different CPU model.
- Intel PEBS and AMD IBS are different facilities; use the supported path for
  the detected platform.
- “L1”, “L2”, “LLC”, and “node load” event names are not portable contracts.
- Intel PCM may require privileged MSR access depending on deployment; do not
  promise unprivileged operation or load modules automatically.
- Counter thresholds and IPC are not universal performance grades. A useful
  change improves the required workload metric without violating correctness.
