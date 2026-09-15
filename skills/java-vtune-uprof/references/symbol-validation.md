# Java/JIT symbol validation

A profiler result is not actionable merely because it contains samples. Export
the report to text using the installed profiler's documented command, then
confirm that representative Java methods resolve and that unresolved frames are
not hiding the hot path. Proprietary result databases remain with their vendor
tool; this check deliberately consumes only an exported text report.

Use `scripts/validate-symbols.py` with one or more methods from the measured
workload:

```bash
python3 skills/java-vtune-uprof/scripts/validate-symbols.py report.txt \
  --require com.example.OrderHandler.handle \
  --require VendorWorkload.chaseBatch \
  --max-unknown 0
```

The command emits JSON and exits non-zero when a required method is absent or
the report contains more unresolved markers than allowed. The default markers
cover `[unknown]`, unknown frames, and long hexadecimal addresses; inspect the
report manually because vendor formats vary. A clean result does not prove
sampling representativeness, inline attribution, or source-line accuracy.

Before exporting, preserve the profiler's JIT map or equivalent metadata and
record the JDK, profiler version, JVM flags, workload interval, and report
command. For `perf`, follow `java-linux-perf`'s JIT-map/jitdump guidance. For
VTune or uProf, use their Java-aware report view and retain the native session.
If the method is absent, label the capture inconclusive before changing code.
