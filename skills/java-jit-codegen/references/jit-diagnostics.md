# JIT diagnostics reference

Defaults below were checked on JDK 25 x86-64 (C2); confirm with
`java -XX:+PrintFlagsFinal -version` on the target, as they are platform- and
release-dependent.

## Tiers

| Tier | Compiler | Purpose |
| --- | --- | --- |
| 0 | Interpreter | Profiling starts |
| 1 | C1 | Full optimisation, no profiling (trivial methods) |
| 2 | C1 | Limited profiling (C2 queue backed up) |
| 3 | C1 | Full profiling — normal stepping stone |
| 4 | C2 | Optimised using the profile |

`made not entrant: not used` after a tier-4 compile is the normal replacement of
tier-3 code. Other reasons (for example `uncommon trap`, `class check`,
`null check`, `unstable if`, `OSR invalidation of lower level`) mean the
profile or an assumption changed.

## Inlining failures

| Message | Meaning | Source-level options |
| --- | --- | --- |
| `callee is too large` | Callee bytecode > `MaxInlineSize` (35) at a cold/normal site | Usually fine; if hot, check the site frequency |
| `hot method too big` / `too big` | Hot callee bytecode > `FreqInlineSize` (325) | Split into a small hot path plus an out-of-line slow path |
| `already compiled into a big method` | Callee's compiled size > `InlineSmallCode` (2500) | Same: shrink the common path |
| `inlining too deep` | Depth > `MaxInlineLevel` (15) | Flatten abstraction layers on the hot path |
| `no static binding`, `virtual call` | Not devirtualised (megamorphic or no profile) | Reduce receiver types at the site; final classes; sealed hierarchies help only if profiling sees few types |
| `low call site frequency`, `never executed` | Cold site | Usually correct; check warmup data matches production |
| `callee uses too much stack` | Stack budget exceeded | Fewer large locals; split method |
| `native method`, `not inlineable` | Cannot inline | Batch native calls; consider FFM downcall shape |
| `intrinsic` / `(intrinsic)` | Replaced by a hand-written stub | Good; keep the exact API call shape |

Bytecode size is from `javap -c`; small source changes (assertions, logging,
string concatenation) can push a method over a threshold.

## Deoptimization investigation

1. JFR `jdk.Deoptimization` gives method, line, reason, and action; group by
   reason and method across time.
2. Correlate with latency spikes and with deploys, feature flags, or traffic
   mix changes that introduce new receiver types or branches.
3. `PerMethodTrapLimit` (100) and `PerBytecodeRecompilationCutoff` (200) cap
   recompilation; a method that hits them may stay in slower code
   permanently — look for many recompiles of the same method in the summary.

## Escape analysis and scalar replacement

C2 can remove allocations that do not escape the compiled (inlined) scope.
Failure causes: the object escapes into a field/array/unknown call, a callee
was not inlined, merge points with different allocations (improved in recent
JDKs), or large arrays. Verify with JMH `-prof gc` (allocation per op) and not
by assumption; re-verify after JDK upgrades.

## Loops

- Counted loops (`int` induction with a simple bound) enable range-check
  elimination, vectorisation (superword), and loop unswitching. Long-indexed
  loops are optimised on modern JDKs but verify.
- Loop strip mining (`LoopStripMiningIter`, 1000) bounds time-to-safepoint for
  counted loops; do not disable `UseCountedLoopSafepoints` to chase a
  benchmark number.
- Auto-vectorisation is fragile; check with perfasm or the Vector API.

## Generated assembly

- `-XX:+UnlockDiagnosticVMOptions -XX:+PrintAssembly` needs the `hsdis` plugin
  (`hsdis-amd64.so`) on the JVM library path; OpenJDK builds do not ship it.
  Build it from the OpenJDK source (`--with-hsdis=binutils|capstone|llvm`) or
  use a trusted vendor package, pinned and verified.
- JMH `-prof perfasm` combines perf samples with assembly; requires perf
  hardware-event access (the `profiling-readiness` skill) and hsdis.
- `-XX:+DebugNonSafepoints` improves attribution of samples to inlined
  source lines for profilers.

## Code cache

`jcmd PID Compiler.codecache` shows segment usage (non-method, profiled,
non-profiled). Full code cache stops compilation ("CodeCache is full. Compiler
has been disabled"). Size `ReservedCodeCacheSize` with headroom for
recompilation churn and dynamically generated code (lambdas, method handles,
proxies).

## Compiler threads on isolated hosts

`CICompilerCount` scales with visible CPUs. When hot threads are pinned to
isolated cores, JIT and GC threads must run on housekeeping cores; too few
housekeeping cores delays compilation and extends warmup. Record the final
value and test warmup time explicitly.
