# JDK compatibility matrix

Use `scripts/compatibility-matrix.py` to compile and run the fixed
`VendorWorkload.java` fixture with each explicitly supplied JDK. The runner
uses bounded, fixed work and writes raw stdout/stderr plus `summary.json`.

```bash
python3 skills/java-vtune-uprof/scripts/compatibility-matrix.py \
  --jdk "$HOME/.sdkman/candidates/java/21.0.7-tem" \
  --jdk "$HOME/.sdkman/candidates/java/25.0.2-tem" \
  --source skills/java-vtune-uprof/scripts/VendorWorkload.java \
  --output-dir /tmp/vendor-compat
```

`verified` means only that this fixture compiled and completed with the
expected operation count and valid timing. `failed` and `unavailable` remain
visible and produce a non-zero exit; neither status may be converted into a
claim of profiler support. The matrix does not test VTune, uProf, PMU access,
JIT symbol quality, or a VM's vPMU exposure.

For each run, record CPU vendor/model, kernel and hypervisor, JDK vendor and
version, JVM flags, profiler version and analysis mode, permissions, workload
revision, checksums, and the paths to raw logs. Run bare metal and virtual
machines as separate rows. Pair this fixture check with the
`profiling-readiness`, `java-hardware-counters`, and symbol-validation guidance
before comparing vendor metrics.
