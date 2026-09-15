# Vendor-profiler validation protocol

## Synthetic workload

`scripts/VendorWorkload.java` is an attribution fixture, not a performance claim.
It has named methods for four input patterns:

| Mode | Mechanism | Interpretation limit |
| --- | --- | --- |
| allocation | Escaping 256-byte arrays | Includes volatile publication; not pure allocation cost |
| branch | Seeded values with two arithmetic paths | JIT may if-convert; do not presume branch misses |
| stream | Sequential int-array reads | One thread need not saturate memory channels |
| chase | Dependent reads through a seeded single-cycle permutation | Cache residency depends on working set and placement |
| lock | Uncontended Java monitor acquisition | Does not model multi-thread contention; use a service-shaped lock test for that |
| park | Short `LockSupport.parkNanos` waits | Timer/scheduler behavior is host-dependent; it is not a queue benchmark |

Do not compare modes as equivalent implementations. Use identical arguments and
checksums when comparing a mode with/without profiling. Each batch performs
1,024 operations. Warmup is separate; allocation size includes no object-header
assumption. Initialization and shuffle are outside the measured window.

From the skill directory, a source-launcher smoke test is:

```bash
timeout --kill-after=5s 30s java -Xms128m -Xmx128m \
  scripts/VendorWorkload.java chase 1000 1000 16
```

For profiler experiments, compile once to avoid sampling the source compiler:

```bash
umask 077
vendor_run=$(mktemp -d "${TMPDIR:-/tmp}/vendor-validation.XXXXXX")
mkdir "$vendor_run/classes"
javac -g -d "$vendor_run/classes" scripts/VendorWorkload.java
timeout --kill-after=5s 60s java -Xms256m -Xmx256m \
  -XX:+PreserveFramePointer -cp "$vendor_run/classes" \
  VendorWorkload chase 10000 2000 64 > "$vendor_run/baseline.txt"
```

Inspect every exit code; timeouts, OOM, or missing final fields invalidate the
run. Increase batches within the same deadline only after a pilot establishes
runtime. Working sets are bounded to 256 MiB; allow heap headroom. The workload
has finite work but no internal wall-clock deadline, so keep the outer timeout.

`measurement_start_uptime_ms` and `measurement_end_uptime_ms` bracket the measured
loop approximately at millisecond precision. They permit alignment with JVM
uptime in GC/JFR data; translate vendor timelines using their documented clock
origin. They are not exact cross-tool synchronization. If the profiler includes
warmup, filter to the matching interval and report any boundary uncertainty.

## Acceptance matrix

For each vendor, JDK, collection mode, and launch/attach combination, record:

1. **Environment:** CPU model/microcode, topology, OS/kernel, JDK build, tool
   version, permissions, workload revision/hash, arguments, heap and collector.
2. **Collection:** exact command, interval, return code, logs, finalization status,
   raw artifact size and checksum, sample count, lost samples and multiplexing
   where available. A report file alone is insufficient.
3. **Attribution:** the relevant fixture method (or inline frame/source line)
   resolves in the measured window. Preserve the representative report excerpt.
   Do not require every method to have a sample; inspect the mode actually run.
4. **Mechanism:** explain which measured metric supports the hypothesis and its
   scope/units. Zero or unsupported counters are not proof of absent stalls.
5. **Overhead:** run at least three interleaved profiled/unprofiled pairs with
   identical fixed work, warmup, JVM flags, placement, and inputs. Report all
   measured elapsed times and checksums. Calculate elapsed-time overhead as
   `(profiled / unprofiled - 1) * 100`; distinguish it from total launch and
   finalization time. Run no other load tests alongside these comparisons.
6. **Cleanup:** owned test JVM and collector have exited; incomplete output is
   marked partial. Retain evidence of any unconfirmed cleanup. Do not kill
   unrelated processes or delete incomplete artifacts to make a run look clean.

The installed JVMs checked on 2026-09-14 (Oracle 21.0.10 and Temurin 25.0.2)
both expose `PreserveFramePointer` and `EnableDynamicAgentLoading`. Recheck with
`java -XX:+PrintFlagsFinal -version` on other builds. Option existence does not
validate uProf/VTune attachment; flag defaults and agent policy are separate.

Do not promise speedups from this fixture. To verify a source optimization,
use a semantically equivalent representative workload and unprofiled repeated
measurements, following the `java-jmh-benchmarking` or `java-latency-measurement`
skill as appropriate.
