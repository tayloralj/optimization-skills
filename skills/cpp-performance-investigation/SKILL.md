---
name: cpp-performance-investigation
description: Start here for slow, stuck, crashing, or memory-hungry native C or C++ services on GNU/Linux, or JNI code a Java investigation has implicated. Use when the cause or next tool is unclear to define the problem, check build and host readiness, and route to evidence.
---

# C/C++ Performance Investigation

Route the problem; do not start optimising. The output is a short plan naming
the next skill or capture, the evidence it must produce, and the decision that
evidence supports. This is the entry point for native services built with the
GNU toolchain (GCC, binutils, glibc). Skills whose scripts this workflow runs
are listed in `requires.txt` and installed with it.

**JVM boundary.** If the process is a JVM, start with the
`java-performance-investigation` skill. Come here when its evidence points at
native code: JNI or other native libraries on hot or leaking stacks, or native
crashes outside `libjvm.so`. JVM internals (GC, JIT, NMT) stay with the Java
skills.

Several shared skills are named `java-*` but their host and method sections
apply to any process: `java-latency-measurement` (open-loop load, coordinated
omission, percentiles), `java-hardware-counters`, `java-numa-affinity`, and the
`perf c2c` part of `java-cache-efficiency`. Use those sections and skip the
JVM-specific steps. Say so in the plan, so the user knows why a Java skill
was chosen.

## Workflow

1. **Scope and objective.** Identify the service, binary and version,
   incident window, environment, access, and existing evidence. Discover the
   real PID; example PIDs are not targets. For crashes, restarts, or hangs,
   establish the failure timeline first and do not delay evidence for an SLO.
   For performance, state a measurable target: metric, percentile, offered
   load, environment. If none exists, propose one and the baseline it needs.
2. **Build readiness.** Run the `cpp-build-readiness` skill on the running PID
   or the exact deployed artifact. Stripped binaries, omitted frame pointers,
   or a binary replaced since start decide which evidence is usable and which
   unwinding mode to use. Keep the report and build-ids with the evidence.
3. **Host readiness.** Run the `profiling-readiness` skill on the affected
   host. Also read `/proc/sys/kernel/yama/ptrace_scope`: at 1 or above, gdb and
   `gcore` cannot attach to a process the user did not start, even as the same
   user. Local readiness is not evidence of production capability.
4. **Broad observation first.** Separate the big buckets before narrowing,
   using `references/triage.md` for bounded captures:
   - on-CPU application work vs kernel time vs waiting off-CPU;
   - off-CPU: locks (futex), I/O, network, scheduler run-queue delay;
   - host interference: interrupts, frequency, migrations, cgroup throttling;
   - memory: RSS and page faults vs allocator behaviour vs leaks;
   - work amplification: syscalls, requests, or retries per logical operation;
   - completeness: operations finished versus offered.
5. **Route** with the symptom map in `references/triage.md`. Pick one skill or
   capture and one question, and record the result that would confirm or reject
   the hypothesis.
6. **Experiment discipline.** Change one factor, repeat on the same host and
   load, compare against a control, and verify the service metric without
   profiler overhead. Rebuilds count as a change: compare builds with the
   same flags apart from the one under test.
7. **Close.** Report the confirmed cause or an inconclusive result, the change,
   before/after distributions, residual risk, and rollback. Routing hints are
   not diagnoses. If the bottleneck did not move, return to step 4.

## Low-latency first

For latency-critical native systems (market data, matching, messaging),
investigate in this order unless evidence says otherwise:

1. Measurement validity: coordinated omission, clock source, histogram
   resolution (method from `java-latency-measurement`).
2. OS jitter on hot threads: interrupts, timer ticks, run-queue delay, C-state
   exits, THP compaction, page faults — `linux-low-latency-tuning`,
   `linux-ebpf-io-network`.
3. Allocator and memory: `malloc` on the hot path, arena contention, page
   faults on first touch.
4. Hot-path cost: instructions, cache and branch misses, false sharing —
   perf with the unwinding mode from step 2, then `java-hardware-counters`
   and `java-cache-efficiency` (`perf c2c`).
5. Placement: cores, SMT siblings, cache domains, NUMA — `java-numa-affinity`.

## Guardrails

- gdb attach and `gcore` stop every thread of the target while they run. Treat
  them as an outage on a latency-critical service and obtain approval first;
  prefer `/proc` state, perf, or eBPF evidence for live systems.
- Never treat missing symbols, failed captures, or a blocked attach as evidence
  that a problem is absent.
- Do not recommend `-O0` or debug builds to investigate performance.
- Do not change production build flags, allocator, environment variables,
  kernel settings, or affinity as part of triage. Propose them as experiments.
- Keep throughput and tail-latency conclusions separate.
- Core dumps and `perf.data` can contain memory contents, paths, and command
  lines. Store privately and redact before sharing.
