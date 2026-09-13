---
name: java-jit-codegen
description: Diagnose HotSpot JIT behaviour on JDK 21 and 25 - tiered compilation, inlining decisions, deoptimization and recompilation churn, megamorphic call sites, OSR, code cache exhaustion, intrinsics, escape analysis, loop optimisations, generated assembly (hsdis, JMH perfasm), Vector API, warmup, and startup via CDS and the JDK 25 AOT cache. Use when hot Java code is slower than expected, performance changes after warmup or deploys, latency spikes coincide with deoptimization, or a proposed micro-optimisation depends on what C2 actually generates.
---

# Java JIT and Code Generation

Treat the JIT as an adaptive system: decisions depend on runtime profiles, so
diagnose with the real workload shape (types, branch frequencies, data sizes),
not a toy loop.

## Workflow

1. **Classify**: steady-state throughput/latency, warmup time, startup, or a
   regression after time or deploy. Record JDK build, flags, CPU model, and
   `CICompilerCount`.
2. **Cheap evidence first (no restart)**: JFR `jdk.Compilation`,
   `jdk.Deoptimization`, `jdk.CodeCacheFull`, `jdk.CompilerInlining` (off by
   default in `profile`), and `jcmd PID Compiler.codecache` /
   `Compiler.queue`. Check whether latency spikes align with deoptimization
   or compilation bursts.
3. **Controlled launch evidence** on a replica or benchmark:

   ```bash
   java -XX:+UnlockDiagnosticVMOptions -XX:+PrintCompilation -XX:+PrintInlining ... > jit.txt
   scripts/jit-log-summary.py --warmup-ms 60000 jit.txt
   ```

   The summary reports compiles per tier, OSR, `made not entrant` reasons,
   repeatedly recompiled/deoptimized methods, inlining failures grouped by
   reason and callee, and compilations after the warmup cut-off. For full
   per-compilation trees use `-XX:+LogCompilation` with JITWatch.
4. **Interpret** using `references/jit-diagnostics.md`. Typical actionable
   findings: hot callee "too large" or "hot method too big", megamorphic
   virtual/interface calls on the hot path, repeated uncommon traps from a
   profile that changes after warmup, late tier-4 compilation, code cache full.
5. **Confirm in JMH** with the `java-jmh-benchmarking` skill; where machine
   code matters use `-prof perfasm` (needs hsdis and perf access) and compare
   assembly of baseline and candidate.
6. **Change one thing** in source first (split a method, monomorphise a call
   site, remove an allocation that blocks scalar replacement, restructure a
   loop). Flag changes (`FreqInlineSize`, `MaxInlineLevel`, `CompileCommand`)
   are last-resort, global, and version-fragile.
7. **Verify** under representative load including warmup, then re-check that
   deoptimization counts and code-cache usage stay flat over a long soak.

## Low-latency specifics

- Warm hot paths with representative data before accepting traffic; avoid
  warming with unrepresentative types or branches, which trains a profile that
  later deoptimizes.
- Keep call sites on the hot path mono- or bimorphic (`TypeProfileWidth` is 2);
  a third receiver type seen later forces a megamorphic dispatch or deopt.
- Exceptions used for control flow, rarely taken branches that become hot, and
  class loading on the hot path all trigger uncommon traps — check
  `jdk.Deoptimization` reasons.
- Code-cache exhaustion silently stops compilation; alert on
  `jdk.CodeCacheFull` and size `ReservedCodeCacheSize` with headroom.

## Startup and warmup (JDK 21 vs 25)

- JDK 21: AppCDS via `-XX:ArchiveClassesAtExit=app.jsa` then
  `-XX:SharedArchiveFile=app.jsa`.
- JDK 25: AOT cache (Project Leyden) — `-XX:AOTCacheOutput=app.aot` on a
  training run, then `-XX:AOTCache=app.aot`; it stores loaded/linked classes and
  method profiles so the JIT warms faster. The training run must exercise
  representative paths and the same JDK, classpath, and flags.
- CRaC checkpoint/restore exists only in specific vendor builds; GraalVM Native
  Image trades peak JIT performance and dynamic features for startup.

## Guardrails

- PrintCompilation/PrintInlining/LogCompilation are diagnostic and verbose; use
  them on replicas or benchmarks, not production services.
- Do not disable tiered compilation, raise inlining limits, or add
  `CompileCommand` directives globally without a benchmark and a soak test.
- The Vector API is still an incubator module on JDK 21 and 25
  (`--add-modules jdk.incubator.vector`); verify the intrinsics compile on the
  deployment CPU and keep a scalar fallback.
- Assembly and inlining trees reveal proprietary code; handle as source code.
