# Build and capture settings for native profiling

Checked against GCC 15.2, GNU binutils 2.46, perf 7.0, and gdb 17.1 on x86-64
Ubuntu. Confirm each option with the build host's own `--help` output before
recommending it; defaults differ between distributions and architectures.

## Compiler and linker flags (GCC)

| Goal | Flag | Notes |
| --- | --- | --- |
| Frame pointers | `-fno-omit-frame-pointer` | Enables cheap `perf --call-graph fp` unwinding. Usually costs a few percent or less; measure it on the real workload rather than assuming. |
| Leaf frames (x86) | `-mno-omit-leaf-frame-pointer` | Target option; without it leaf functions may still omit the frame pointer. |
| Symbols for backtraces | `-g1` | Functions and line tables without local variables; smaller than `-g`. |
| Full debuginfo | `-g` | Needed for `perf report --inline`, source annotation, and gdb locals. |
| Record the switches | `-grecord-gcc-switches` | On by default in GCC; the readiness script reads frame-pointer and `-O` settings from it. |
| Build-id | `-Wl,--build-id` | Many distribution GCCs pass it already; check with `readelf -n`. |
| Keep the optimisation | `-O2` or `-O3` as shipped | Profile the flags production uses. LTO (`-flto`) and inlining merge frames; use `perf report --inline` with debuginfo to see them. |

## Ship symbols without shipping full debuginfo

Keep `.symtab` in the deployed binary so function names resolve on any host,
and ship DWARF separately:

```bash
objcopy --only-keep-debug app app.debug
strip --strip-debug app            # keeps .symtab, removes DWARF
objcopy --add-gnu-debuglink=app.debug app
```

Place the debug file where tools look for it: next to the binary, in a
`.debug/` subdirectory, or at `/usr/lib/debug/.build-id/xx/rest-of-id.debug`.
Alternatively publish it to a debuginfod server; gdb and perf read
`DEBUGINFOD_URLS`, and perf also accepts `--debuginfod`.

## Choosing the perf unwinding mode

| Report says | Use | Cost |
| --- | --- | --- |
| `recommended_call_graph: fp` | `perf record --call-graph fp` | Small per-sample cost and output. |
| `dwarf` | `perf record --call-graph dwarf` | Copies the user stack on every sample (8192 bytes by default, `dwarf,SIZE` to change); much larger `perf.data` and slower reports. Lower the frequency or duration to compensate. |
| frame pointers `mixed` | `dwarf`, or rebuild the libraries that omit them | `fp` stacks stop at the first frame without one. |

LBR (`--call-graph lbr`) exists only on supported Intel CPUs and has limited
depth; check `perf list` and the `java-hardware-counters` skill before relying
on it.
