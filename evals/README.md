# Evals

Script tests prove the tools work. These evals check the part tests cannot:
whether an agent **picks the right skill** for a realistic request and **gives a
better answer because of it**.

## Cases

Vendor cases `vendor-perf-blocked`, `vendor-uncore-scope`, and `vendor-vm-no-pmu`
cover missing tools, JFR-versus-PMU evidence, shared counter scope, cross-vendor
event misuse, and guest permissions versus PMU exposure.
They are authored but have not yet been scored.

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
| `invalid-latency` | Negative response times with exit zero | Rejects SLO conclusion and requires valid timestamps |
| `incomplete-capture` | All JFR views failed with exit zero | Does not infer absence of GC or contention |
| `periodic-allocation` | Allocating first measured round but final-round PASS | Requires every measured round to meet the allocation budget |
| `interrupted-rollback` | Failed restoration followed by rolled-back status | Treats state as incomplete and preserves recovery evidence |
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
claude plugin eval . --runs 3 -j 4 --max-cost-usd 10 --no-publish  # whole suite, with and without the plugin
claude plugin eval . --case gc-log-triage --runs 3 --max-cost-usd 5 --no-publish  # one case
```

By default each case runs twice: with the plugin and without it (a baseline).
The report shows the score difference. Results go to `evals/results/`, which is
gitignored. The runs use your Claude account, so each full suite costs real
money: set `--max-cost-usd`.

For Codex, use the same prompts and rubric files in a fresh unrelated directory
with this collection linked under `.agents/skills`. Run the installed CLI's
`codex exec --ephemeral --sandbox read-only --skip-git-repo-check -C DIR --json`
with a prompt on stdin; retain its JSONL trace and final response privately.
Grade against each case's rubric and verify actual skill reads in the trace.
This is a manual behavioral evaluation, not merely a request to list skill names.
Use a bounded timeout and record the CLI/model. Do not claim equivalence to the
Claude scored ablation or a no-plugin baseline from a single Codex answer.

Agent evals send prompts and loaded skills to the configured external service.
Obtain any required authorization, cap paid runs, and keep publishing disabled.
Installation and format checks are not behavioral evals.

## Status

- Vendor behavioral evaluation attempt on 2026-09-15 was unscored: the
  trusted-plugin run started, but the child reported missing prompt input and
  the grader API request failed with `EAI_AGAIN`. These are separate failures;
  neither produced valid behavioral evidence. The later retry outside the
  sandbox was rejected by automatic approval review because transmitting the
  private plugin content to the Claude API required explicit data-transfer
  approval. No new score is claimed.

- Format verified: `not-java-python-code` ran and passed (no skill loaded; valid answer).
- Codex discovery verified: `codex exec` in a checkout found all 19 skills, including `java-offline-capture` (via `.agents/skills`).
- Claude plugin install verified in an isolated config: 19 skills loaded, about 1,400 always-on tokens.
- **Full suite not yet scored.** The first full run (2026-09-13) hit the account's
  monthly spend limit, and 58 of 60 runs errored before producing answers, so
  its scores are meaningless and were discarded. Re-run when budget allows and
  record the results here with the date, model, and Claude Code version.

## Review-fix validation, 2026-09-13

- Local worktree: script suites passed on Temurin 25.0.2 (94 checks) and Azul
  21.0.8 (95 checks), including 29 Python tests, live JFR/NMT, and walkthrough checks.
- Structural validation and ShellCheck passed. Claude 2.1.270 validates the
  plugin, with the expected warning that repository-root CLAUDE.md is not
  shipped as plugin context. Codex CLI present: 0.153.4.
- New behavioral cases are authored. A bounded Codex pass (CLI 0.153.4) covered
  all four synthetic cases and correctly rejected invalid latency evidence,
  incomplete JFR analysis, periodic allocation hidden by a final-round check,
  and incomplete rollback. Claude 2.1.270 launched the case, but both the
  plugin and no-plugin arms were rejected by the account monthly spend limit
  before model execution; that is unverified, not a score.
- Release remains gated on completed behavioral results for both agents; the
  historical full-suite budget failure above is not resolved by local tests.

## PR refresh, 2026-09-14

Main's offline-capture additions were merged into the hardening branch, preserving
all regression cases and the bounded JFR completion checks. The attempted Claude
eval retry was blocked by automatic approval review before execution because it
would send plugin content to Claude and could incur up to $5. No new behavioral
score is claimed; the release gate above remains open.
