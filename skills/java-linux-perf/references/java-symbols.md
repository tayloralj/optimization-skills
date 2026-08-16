# Java/JIT symbolization

## Choose a path

- Prefer async-profiler or JFR when the question is JVM-centric and PMU access
  is unavailable. They understand JIT code and JVM state directly.
- For Linux perf, use the JDK's supported perf-map or jitdump integration when
  available, or a maintained profiler integration such as async-profiler's
  JFR/perf workflows. Verify instructions against the installed JDK and perf
  versions rather than copying a version-specific flag.
- `-XX:+PreserveFramePointer` can improve frame-pointer unwinding on supported
  JDKs, at a possible performance cost. Apply it only in a controlled launch.
- `-XX:+UnlockDiagnosticVMOptions -XX:+DebugNonSafepoints` can improve source
  attribution on JDKs where it remains applicable. Check the installed JDK.

Warm the JVM before capture and retain JIT compilation, deoptimization, GC, and
safepoint context. A profile dominated by startup compilation is not a
steady-state service profile.

## Discover and validate a perf map

For JDKs that expose the diagnostic command, use the target PID, UID, and PID
namespace:

```bash
pid=1234
jcmd "$pid" help Compiler.perfmap
jcmd "$pid" Compiler.perfmap
test -r "/tmp/perf-$pid.map"
```

The help command is the feature test; do not assume every JDK has it. In a
container, the map may live in the target mount namespace, and the profiler must
see the same path. If the command is absent, use the maintained perf-map-agent
or jitdump integration supported by the installed JDK/profiler and follow that
version's documentation. A jitdump workflow normally requires a subsequent
`perf inject --jit` conversion; a plain perf map does not. Do not mix the two
procedures.

## Validation

Before interpretation, inspect the report for unknown, hexadecimal, or generic
JIT frames. Confirm that representative hot Java methods resolve and that
native libraries have symbols where their attribution matters. If symbol loss
is material, label the capture inconclusive and fix symbolization before making
source changes.

Never claim that `objdump --dwarf` returning zero tags for a JAR means Java was
built without debug information. Use `javap -c -l` for class line tables and a
live JIT-symbol strategy for generated machine code.
