# Evals

Script tests prove the tools work. These evals check the part tests cannot:
whether an agent **picks the right skill** for a realistic request and **gives a
better answer because of it**.

## Cases

| Case | Request | Expect |
| --- | --- | --- |
| `gc-log-triage` | GC log excerpt with a 912 ms full GC | `java-gc-tuning`; names the full GC and evacuation failure; evidence before flags |
| `closed-loop-latency` | "JMH SampleTime p99.99 is 90 µs, so put it in the SLA" | Rejects the claim; explains coordinated omission and open-loop testing |
| `no-root-allocation` | `perf` blocked, no root, no restart, find allocations | JFR via `jcmd` first; does not start by lowering `perf_event_paranoid` |
| `rss-growth` | Container OOM kills, heap flat, RSS grows | Native Memory Tracking and a memory ledger, not just a bigger limit |
| `hot-path-review` | Handler with boxing, `String.format`, per-call lists | Finds the allocations; proposes fixes and a way to prove zero allocation |
| `jit-deopt-after-deploy` | `class_check` deoptimizations after adding a third implementation | Explains megamorphic call sites; source-level fixes over global flags |
| `production-host-tuning` | "Give me commands to isolate CPUs on production" | Read-only audit, trade-offs, rollback, verification; no casual paste-ready changes |
| `benchmark-host-lab-mode` | Declared lab host with CPU lists | Uses `make-lab-plan.py` and `lab-tune.sh` with review, apply, measure, rollback |
| `prod-host-without-agent` | Locked-down prod VM, ops runs what we send | `java-offline-capture`; kit, dry-run, run as app user, retrieve, verify, analyse |
| `not-java-python-code` | Reverse a linked list in Python | **No** skill from this plugin loads |
| `not-java-frontend-bundle` | Slow React bundle | **No** skill from this plugin loads; front-end advice |

Each case has an outcome grader (regex or an LLM rubric with checkable
claims). The `skill-fired` graders report whether the expected skill loaded but
do not count toward the score. The two negative cases guard against the
skills loading for unrelated work.

## Run

Claude Code:

```bash
claude plugin eval . --runs 3 -j 4 --max-cost-usd 10          # whole suite, with and without the plugin
claude plugin eval . --case gc-log-triage --runs 3            # one case
```

By default each case runs twice: with the plugin and without it (a baseline).
The report shows the score difference. Results go to `evals/results/`, which is
gitignored. The runs use your Claude account, so each full suite costs real
money: set `--max-cost-usd`.

Codex has no equivalent runner. Check discovery manually from a checkout:

```bash
codex exec --sandbox read-only "Without running commands, list every skill whose name starts with java-, linux-, or profiling-."
```

## Status

- Format verified: `not-java-python-code` ran and passed (no skill loaded; valid answer).
- Codex discovery verified: `codex exec` in a checkout found all 19 skills, including `java-offline-capture` (via `.agents/skills`).
- Claude plugin install verified in an isolated config: 19 skills loaded, about 1,400 always-on tokens.
- **Full suite not yet scored.** The first full run (2026-09-13) hit the account's
  monthly spend limit, and 58 of 60 runs errored before producing answers, so
  its scores are meaningless and were discarded. Re-run when budget allows and
  record the results here with the date, model, and Claude Code version.
