---
name: cpp-build-readiness
description: Check whether a native C or C++ binary or process, including JNI code in a JVM, will give usable profiler stacks on GNU/Linux - symbols, debuginfo, build-id, frame pointers, unwind tables, compile flags. Use before perf or gdb on native code, or when stacks show unknown frames.
---

# C/C++ Build Readiness

Native profiles are only as good as the build. Stripped binaries, missing
debuginfo, omitted frame pointers, or a binary replaced since the process
started turn stacks into `[unknown]` frames and hex addresses. Check this
before collecting evidence, not after. Host permissions are a separate question
for the `profiling-readiness` skill.

## Workflow

1. Run `scripts/native-build-check.py --pid PID` as the target's user, or
   `--binary PATH` on the exact artifact that is deployed. Add `--json` to keep
   the report with the evidence. The script only reads `/proc` and ELF files
   with GNU `readelf`; it does not attach, write, or query debuginfod.
2. Read `status` and `recommended_call_graph` (below), then each object's line.
   The executable is listed first; libraries follow in mapping order.
3. If the main object is unsymbolised or frame pointers are not kept, read
   `references/build-flags.md` and propose a build change. Do not rebuild or
   restart a service yourself; the build owner decides.
4. When the report is acceptable, collect evidence with the matching unwinding
   mode, and keep the report and `build_id` values with the profile so the
   right binaries and debuginfo can be matched later.

## Interpret the report

- `READY_SYMBOLISED`: every inspected object has a `.symtab` or debuginfo.
  Stacks can still be truncated if the unwinding mode is wrong.
- `PARTIAL_LIBRARIES_UNSYMBOLISED`: the executable is fine but some libraries
  only export dynamic symbols. Usually acceptable; internal library frames
  will be missing or named after the nearest exported function. Distribution
  debug packages or debuginfod can fill the gap.
- `DEGRADED_MAIN_UNSYMBOLISED`: the executable has neither `.symtab` nor
  debuginfo. Application frames will be addresses. Obtain the matching debug
  file (same `build_id`) or an unstripped build before profiling.
- `recommended_call_graph`: `fp` only when every object records
  `-fno-omit-frame-pointer`; otherwise `dwarf`. Frame pointer state comes from
  `DW_AT_producer`, so it is `unknown` without debuginfo, and
  `compiler_default` when no flag was recorded (GCC omits frame pointers at
  `-O1` and above on x86-64: confirm with
  `gcc -Q --help=common -O2 | grep omit-frame-pointer` on the build toolchain).
- `deleted_since_start`: the file on disk was replaced after the process
  mapped it. Symbols read from disk may not match the running code; profile a
  fresh process or use the original artifact.
- `allocator`: `glibc` means no jemalloc, tcmalloc, or mimalloc library is
  linked; a statically linked allocator is not detected.
- `unreadable` or exit status 3: run as the target's user. In containers the
  script tries `/proc/PID/root` first, which needs the same access.

## JVM processes with native code

When `jvm_in_process` is true, this report covers only native code: the
launcher, `libjvm.so`, and JNI libraries. JIT-compiled Java frames live in
anonymous memory and need a perf map and, for frame-pointer unwinding through
Java frames, `-XX:+PreserveFramePointer`. Use the `java-linux-perf` skill for
those; the JVM's own libraries are usually stripped with a debuglink, so
`PARTIAL_LIBRARIES_UNSYMBOLISED` is expected there.

## Guardrails

- Read-only: no `sudo`, package installs, rebuilds, restarts, or debuginfod
  downloads from this skill. Propose them to the operator instead.
- Match debuginfo by `build_id`, never by file name or version string alone.
- Treat build-id and file paths as potentially sensitive when sharing reports.
- Do not recommend `-O0` builds for profiling; they measure different code.
