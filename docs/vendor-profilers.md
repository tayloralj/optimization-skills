# Intel and AMD vendor-profiler investigation

Status as of 2026-09-15: runbooks, the synthetic fixture, and user-local vendor
tool setup are implemented. Intel collection is blocked by the supplied VM's
ptrace policy and absent vPMU; AMD uProf has been downloaded and checksum
verified and completed a bounded Java hotspots launch on the local Ryzen 9
7900. CPI and IBS fixture attribution and three hotspots comparison pairs also
completed during release hardening; see the release validation record. This is not
a release-level vendor-support claim.

See the historical [0.3.0 release validation](release-validation.md) for the
AMD and Intel checks at that time, and [behavioral evaluations](../evals/README.md)
for the current scoring gaps.

## What to use

| Need | Intel | AMD |
| --- | --- | --- |
| Java/native method hotspots | VTune | AMDuProfCLI |
| Model-specific instruction/cache/branch evidence | VTune hardware analyses | uProf core PMCs / IBS |
| Shared memory-channel and other system counters | Intel PCM tools where supported | AMDuProfPcm where supported |

Start with the [vendor skill](../skills/java-vtune-uprof/SKILL.md), its
[Intel runbook](../skills/java-vtune-uprof/references/intel.md) or
[AMD runbook](../skills/java-vtune-uprof/references/amd.md), and the
[system-counter reference](../skills/java-hardware-counters/references/system-counters.md).
The [validation protocol](../skills/java-vtune-uprof/references/validation.md)
defines attribution and overhead checks. The
[offline handoff](../skills/java-vtune-uprof/references/offline-results.md)
preserves native sessions alongside the JVM kit; it does not add a vendor parser
to the existing bundle analyser.

## Local evidence

Read-only readiness check: AMD Ryzen 9 7900, Ubuntu 26.04.1, kernel
7.0.0-31-generic, one NUMA node and two LLC domains. The agent sandbox reports
`perf_event_paranoid=4`, no effective capabilities, and a failed perf smoke test.
Launch-time JFR was created and parsed successfully. AMD uProf 5.3.521 is
downloaded to the private validation area (MD5
`45437d8bc0b4276a0b78e28d21de23cb`; SHA-256
`134659c6d9394be323632ad406169c1bd53623b27e58f5eb72f7235daaa6c0f9`) and was subsequently extracted for CLI and capture validation. VTune 2026.4.0 and PCM
202502-1build2 are installed under `$HOME/.local/opt` on the supplied Intel VM.

| Validation | Result |
| --- | --- |
| Synthetic fixture on Temurin 25.0.2 | Six workload modes pass fixed-work, checksum, argument, and source-launcher checks |
| Synthetic fixture on Oracle 21.0.10 | Historical fixture tests passed; see the release validation record for current coverage |
| Fixture method attribution with JFR, JDK 25 | `VendorWorkload.chaseBatch` and its caller resolve |
| AMD uProf CLI / Pcm | uProf 5.3.521 `info --system` resolves Ryzen 9 7900; bounded `hotspots` launch completed and report.csv resolved `VendorWorkload::chaseBatch`; CPI/IBS attribution and hotspots comparisons subsequently completed |
| Intel VTune / PCM | VTune software sampling exits 1 at `ptrace_scope=1`; PCM exits 1 because vPMU/MSR/PCI access is unavailable; no capture |
| Vendor overhead and source improvements | Three hotspots comparison pairs completed; noisy timing is not an optimization claim |
| Behavioral evals | Three cases authored; unscored |

Historical verification (before release hardening): 48 Python tests passed;
`WALKTHROUGH_TESTS=1 ./tests/run-tests.sh` passed 125 checks on Temurin 25.0.2
and 126 on Oracle 21.0.10. Structural and installed agent validators passed for
all 19 skills, with the existing Claude root-context warning. Live suite checks
attached only to their own temporary local JVMs. No shell helpers changed.

The JFR experiment used a compiled fixture, 256 MiB fixed heap, frame pointers,
64 MiB working set, 2,000 warmup batches and 30,000 measured batches. It recorded
with `settings=profile,maxsize=32m` under a 60-second outer timeout. It validates
the fixture's observability with JFR, not AMD PMU permission or uProf integration.

## Supplied Intel VM

Read-only SSH inspection found Ubuntu 26.04.1, kernel 7.0.0-31-generic, two KVM
vCPUs, and guest CPUID model `Intel Xeon Processor (SierraForest)` (family 6,
model 175). This describes the guest CPU presentation, not independently
verified physical host hardware. Java, javac, VTune, and Intel PCM were absent
from PATH and the inspected standard installation locations.

The guest exposes only `breakpoint`, `kprobe`, `msr`, `software`, `tracepoint`,
and `uprobe` event sources, with no core `cpu` or uncore PMU. Both the
`cycles:u,instructions:u` and `task-clock` self-process tests exited 1 with
`perf_event_paranoid=4`. That permission failure does not identify every possible
event limitation; the missing PMU is an independent obstacle. No packages,
privileges, VM configuration, or services were changed.

Next steps are an operator-reviewed ptrace policy decision for a repeatable
VTune software trial, repeated AMD profile comparisons,
and a separate hypervisor/physical-host discussion for core vPMU and uncore
access. Installing PCM or relaxing guest perf policy alone cannot establish
socket/channel counter support.

## AMD validation record and next live step

1. The approved EULA form returned AMD's `uprof-5-3` archive URL. The 331 MB
   archive is checksum-verified above. Extract it into a fresh private
   user-local directory; do not run a package installer, driver installer, or
   capability setup script.
2. Inspect the archive's executable dependencies and CLI help. Record exact
   version/configuration support and confirm the Java launch requirements.
3. A user-mode hotspots capture of the synthetic JVM completed with a new
   private output directory, a 60-second wall-clock deadline, and a 256 MiB JVM
   heap. The report contained `VendorWorkload::chaseBatch`.
4. Preserve logs/results and verify owned processes exit. Keep host sysctls,
   drivers, capabilities, and service configuration unchanged. Removing the
   temporary tool directory after preserving evidence is the cleanup step.
5. If successful, perform the repeated comparison and JDK matrix in the protocol.
   Other CPU/JDK/analysis combinations require separate validation and their own
   least-privilege operator plan if the exact event fails. Intel work needs a
   supported Intel host and installed tools.

The archive was downloaded under the operator's approval. uProf extraction,
`info --system`, and the bounded hotspots trial were successful. No vendor
driver, capability setup, sysctl, package-manager installation, or service
change was performed. The result is a fixture attribution check, not proof
that every PMU or IBS analysis is available.

## Real JFR fixture output

Trimmed, unedited stdout from the run described above:

```text
fixture=synthetic
mode=chase
jdk=25.0.2+10-LTS
working_set_mib=64
warmup_batches=2000
measured_operations=30720000
measurement_start_uptime_ms=668
measurement_end_uptime_ms=3536
elapsed_ns=2867830762
operations_per_second=10711929.172
checksum=250703326249
```

Trimmed, unedited `jfr print --events jdk.ExecutionSample` output:

```text
    VendorWorkload.chaseBatch() line: 64
    VendorWorkload.run(String, int) line: 75
```
