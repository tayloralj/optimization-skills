# Compatibility and validation

Validation levels are separate: discovery means an agent can see a skill;
execution means a helper ran; behavioral evaluation means the agent used the
evidence correctly. None is interchangeable with another.

## Supported scope and evidence

| Component | Intended support | Verification |
| --- | --- | --- |
| Host | Linux, Bash 4+, GNU coreutils including `timeout`, Python 3.9+ | Fake proc/sys fixtures plus host-local checks |
| JVM | HotSpot JDK 21 and 25 | CI matrix exercises both; local run details below |
| Codex | Personal `~/.agents/skills`, repository `.agents/skills` | Installer lifecycle tested from an unrelated directory; agent discovery/behavior recorded separately |
| Claude | Standalone skills and `optimization-skills` plugin | Manifest validation and installer tests; behavior recorded in evals |
| async-profiler | Installed `asprof`, pinned by the operator | Version/event compatibility must be checked on target; not certified by JDK tests |
| BCC / perf / vendor profilers | Installed version and supported host events | Stub/argument checks do not establish live profiling success |

`CODEX_SKILLS_DIR` overrides the personal installer destination. Use it explicitly
for legacy `~/.codex/skills` cleanup; installation does not delete legacy entries
or modify agent configuration automatically. Do not install both standalone
Claude skills and the plugin unless you intentionally want duplicate entries.

Official discovery conventions: [Codex skills](https://learn.chatgpt.com/docs/build-skills)
and [Claude plugins](https://code.claude.com/docs/en/plugins).

## Capture guarantees

| Helper | Scope and identity | Time and storage controls |
| --- | --- | --- |
| `jfr-capture.sh` | Same-user Java PID, start time, mount namespace (another namespace only with `JFR_TARGET_TMP`, reading back through `/proc/PID/root`); private directory | Recording duration up to 1 hour; each jcmd bounded to 10 seconds by default plus 2-second kill grace; retained JFR data capped, not an exact file-size limit; optional events disabled at the source; failed cleanup reported |
| async-profiler `capture.sh` | Same-user Java PID and start time; private output | Profiler duration up to 1 hour; stack-storage memory limit is not a file-size limit; no independent attach deadline |
| `rotating-jfr.sh` | Uses async-profiler capture checks | Retained-file count/bytes, free-space reserve, monitored per-capture budget; not a filesystem quota |
| `bpf-capture.sh` | Operator-run PID-scoped or explicitly system-wide; does not enforce same-user Java identity | Duration argument or timeout up to 600 seconds; no byte ceiling or universal forced-kill deadline |
| `native-memory-snapshot.sh` | Same-user Java PID and start time; private output | Multiple diagnostics, each jcmd bounded to 10 seconds by default; no global wall-time or byte ceiling |
| Offline `collect.sh` | Same-user Java PID and start time, rechecked through the window; other mount namespaces through `/proc/PID/root`; private output | Wait up to `--max-wait` (7 days maximum) writing nothing; window 10 seconds to 1 hour; each JVM command bounded by `JCMD_TIMEOUT_SECONDS` (30 by default, 60 maximum), and an unresponsive JVM skips further JVM commands; JFR, GC log, and vendor-artifact budgets inside `--max-mb` plus a free-space check; asprof and thread-dump output are counted only after collection (over-budget bundles are flagged, not truncated) |
| Manual perf/vendor commands | Agent/operator must verify scope and identity | Budgets are instructions, not enforced by these skills |

Read-only describes host-configuration policy: profiling still attaches to a
process, adds runtime work, and writes artifacts. Treat instruction-level
approval rules separately from mechanisms enforced by scripts or agent sandboxes.

## Release evidence

Before release, record the date, commit or worktree, OS, JDK vendor/build,
agent CLI versions, command, result, and limitations. Require:

1. Structural validation, ShellCheck, and script tests on JDK 21 and 25.
2. Installation and resource execution from an unrelated directory.
3. Claude and Codex behavioral cases covering routing, successful evidence use,
   missing tools, failed capture, invalid measurements, and recovery.
4. Actual artifacts or transcripts for claimed successes. A failed API call,
   unavailable tool, or account limit is **unverified**, never a passing eval.

See [behavioral evaluations](../evals/README.md) for cases and current results.
The current tag is `v0.3.2`. Repository checks, live attachment checks, and
agent behavior remain distinct claims; the routing cases have limited scored
results and the full behavioral suite has not yet been scored.

## Local review-fix run, 2026-09-13

Worktree validation on Linux 7.0.0-31-generic:

| Check | Version / command | Result |
| --- | --- | --- |
| Script suite | Temurin 25.0.2, `WALKTHROUGH_TESTS=1 ./tests/run-tests.sh` | 94 passed, 0 failed |
| Script suite | Azul 21.0.8, same command | 95 passed, 0 failed |
| Structural + agent validators | `./scripts/validate-all.sh`; Claude 2.1.270 | Passed; root CLAUDE.md context warning |
| ShellCheck | `--severity=warning` over repository shell scripts | Passed |
| Installer lifecycle | Fresh temporary directories, link/copy/uninstall, resource execution outside checkout | Passed |
| Agent behavior | Codex 0.153.4 / Claude 2.1.270 | Codex synthetic pass succeeded; Claude launch was blocked by monthly spend limit before model execution |

No live perf, async-profiler, BCC, VTune, or uProf captures were performed during
this validation. Live JVM tests attached only to their own temporary processes.

## Merged-branch verification, 2026-09-14

After integrating main's offline capture kit, the full suite including walkthrough
checks passed on Temurin 25.0.2 (125 checks) and Oracle 21.0.10 (126 checks).
The Python suite passed all 34 tests. All 19 skills passed structural and agent
validation; ShellCheck 0.11.0 passed, including the offline collector. The expected
root CLAUDE.md context warning remains. Live attachment checks ran outside the
agent sandbox against temporary test-owned JVMs after sandbox attachment failed.
These are correctness checks, not new performance measurements. Claude behavioral
evaluation remains unverified; see the evaluation status linked above.

## Release history and hardening evidence

See the [v0.3.0 release record](release-0.3.0.md) and the historical
[release hardening record](release-validation.md) for JDK suites, ShellCheck,
AMD CPI/IBS evidence, Intel VM blockers, and the evaluation limits at that
time. The [changelog](../CHANGELOG.md) records the later v0.3.1 routing and
v0.3.2 JFR finalization fixes. See [behavioral evaluations](../evals/README.md)
for the most recent agent results; the historical records are not a statement
that a released tag is still pending.
