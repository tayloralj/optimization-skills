# 0.3.0 release scope and validation

This release includes the requested capture safety, installation, and
recommendation improvements. It is a Linux/HotSpot 21/25 toolkit with documented
limitations, not a certified automatic diagnosis service.

## Changed behavior

- Perf and vendor launch wrappers share a process-group supervisor. Deadlines,
  interrupts, nonzero exits and storage-limit violations return nonzero and
  preserve partial evidence. The manifest records completeness and the reason.
- A per-file OS limit and a 50 ms aggregate-size monitor replace unbounded
  output. Rapid multi-file writes can overshoot; this is not a filesystem quota.
  Vendor output must be configured inside the capture directory. Commands must
  not daemonize or escape the supervised process group.
- Perf record no longer uses the unsupported `--timeout` argument. Recording
  uses 99 Hz cycles sampling; wall time is enforced externally.
- Subset installations include transitive script dependencies for guided debug
  and vendor capture. Invalid dependency names fail installation.
- Recommendations include JSON evidence locations, observations, uncertainty,
  and a verification experiment. Warning counts/severity no longer generate
  diagnostic confidence. Baselines are explicitly not compared without checked
  units, scope, workload and time windows.

## Validation evidence

New regression tests exercise interrupted output retention, deadline expiry,
storage exhaustion, nonzero commands, symlink refusal, fresh Codex/Claude copy
installs outside the checkout, and recommendation provenance.

Local release checks on 2026-09-18: `WALKTHROUGH_TESTS=1 ./tests/run-tests.sh`
passed 190 checks on JDK 25; the five new release-safety tests and six guided
toolset tests passed. All 20 skills passed bundled/Codex/Claude structural
validation, and ShellCheck 0.11.0 passed at warning severity. Structural
validation does not establish agent behavior. CI also runs JDK 21 and 25.

A real local perf record test with an 8 MiB budget first hit the storage limit
at the former sampling defaults. The 99 Hz capture completed with 257084 bytes
of content and exit 0. Both manifests were retained. This was a short Python
workload to verify capture mechanics, not Java symbol or vendor validation.

## Known limitations carried into this tag

- The offline analyser's service-evidence import remains defective; the
  standalone service parser is available. Automatic integration is unverified.
- Vendor text parsing remains heuristic and must not establish method
  attribution or reliable IPC. Preserve and inspect native vendor results.
- Recovery comparison does not yet validate every completion line or ordering
  error in a multi-case workload.
- Guided `--run` currently selects perf directly; automatic fallback and a
  complete capture-to-diagnosis path remain unfinished.
- No new live VTune/uProf/PCM validation is claimed by this release.
- Claude behavioral evaluation was blocked by automatic approval review before
  execution: private-plugin transfer and paid API use require explicit approval.
  Full Claude/Codex behavioral coverage remains incomplete.

The tag is explicitly requested for this scope. It does not close the older
full behavioral-validation gate or certify the known incomplete paths above.
