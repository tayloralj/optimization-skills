# Repeatable comparison runner

Use `scripts/profile-compare.py` when both commands are bounded fixed-work
programs that print `measured_operations=`, `checksum=`, and `elapsed_ns=`. It
does not attach a profiler or generate load; put the complete vendor command in
the profiled command string.

The runner tokenises commands with Python `shlex` and executes them without a
shell. It runs baseline and profiled commands in interleaved pairs, refuses an
existing output directory, preserves stdout/stderr, checks return codes and
comparison fields, and writes `summary.json`. Failures leave partial evidence
and return non-zero.

Example using the vendor fixture:

```bash
python3 skills/java-vtune-uprof/scripts/profile-compare.py \
  --baseline-cmd 'java -Xms256m -Xmx256m -XX:+PreserveFramePointer -cp classes VendorWorkload chase 30000 2000 64' \
  --profiled-cmd 'vtune -collect hotspots -result-dir result -- java -Xms256m -Xmx256m -XX:+PreserveFramePointer -cp classes VendorWorkload chase 30000 2000 64' \
  --pairs 3 --timeout 120 --output-dir /tmp/vendor-compare
```

Run it only after the profiler's help, launch mode, output format, and
permission checks have succeeded. Interpret `overhead_percent` as workload
elapsed-time overhead; it excludes setup and profiler finalization. Do not
compare rows if flags, inputs, placement, or completion semantics differ.
