# Repository guide for coding agents

This repository publishes agent skills for Java/JVM performance work on Linux.
The same `skills/` tree must work unchanged in OpenAI Codex and Claude Code.

## Layout

```text
skills/<name>/SKILL.md          frontmatter + workflow (shared by both agents)
skills/<name>/references/*.md   detail loaded on demand; linked from SKILL.md
skills/<name>/scripts/*         executable helpers; paths are relative to the skill dir
skills/<name>/agents/openai.yaml Codex UI metadata (ignored by Claude)
skills/<name>/assets/            files shipped elsewhere (e.g. the offline collector kit)
skills/<name>/requires.txt       other skills whose scripts this skill uses (install.sh follows it)
.claude-plugin/                  Claude Code plugin + marketplace manifests (Codex reads the marketplace too)
.codex-plugin/plugin.json        Codex plugin manifest (UI metadata; version kept in sync)
.claude/skills/, .agents/skills/ symlinks to skills/ for in-repo discovery
scripts/validate_skills.py       bundled validator (both agents' rules, doc links)
tests/                           script tests and real JDK fixtures
evals/                           Claude Code eval cases (claude plugin eval)
docs/                            getting started, annotated examples, walkthrough
CHANGELOG.md                     user-facing changes per version
install.sh                       personal install for Codex and/or Claude
```

## Authoring contract

- Frontmatter keys: only `name`, `description` (plus optional `license`,
  `allowed-tools`, `metadata`). Single-line values; no block scalars.
- `name` is hyphen-case, at most 64 characters, and equals the directory name.
- `description` is at most 1024 characters, has no angle brackets, says what
  the skill does, and includes a "Use when/to/for/after/before ..." trigger.
- Refer to other skills in agent-neutral words: "the `profiling-readiness`
  skill". Do not write `$skill-name` (Codex syntax) or `/skill-name` (Claude
  syntax) in `SKILL.md` or references; only `agents/openai.yaml`'s
  `default_prompt` uses `$name`.
- Keep `SKILL.md` under 500 lines; put tables and detail in `references/`.
  Every file in `references/` and `scripts/` must be referenced.
- `agents/openai.yaml` needs `display_name`, a 25–64 character
  `short_description`, and a `default_prompt` containing `$<name>`.
- Write descriptions in plain words, ideally under 300 characters: every
  description is loaded into every session of both agents.
- New skill: add the directory, both symlinks
  (`ln -s ../../skills/<name> .claude/skills/<name>` and the same under
  `.agents/skills/`), a README table row, tests for any script, at least one
  eval case in `evals/`, and a CHANGELOG entry.
- Documentation examples must be real output from a real run, trimmed but not
  edited. Label synthetic fixtures as synthetic.
- Java helpers are single-file programs runnable with the JDK source launcher
  (`java Tool.java`), with no dependencies.
- Native (C/C++) skills target the GNU/Linux toolchain (GCC, binutils, gdb,
  glibc) and use a `cpp-` prefix. Test fixtures are small sources compiled at
  test time; tests skip when the compiler or binutils are missing.

## Script conventions

- Read-only by default. No `sudo`, package installs, sysctl or sysfs writes,
  service restarts, or persistent configuration. The only mutating helper is
  `linux-low-latency-tuning/scripts/lab-tune.sh`, which is allowlisted,
  runtime-only, operator-run, and records verified rollback.
- Bash: `#!/usr/bin/env bash`, `set -euo pipefail` (or `-uo` for best-effort
  collectors), `LC_ALL=C`, `umask 077`, validate every argument, refuse
  overwrites and symlinks, private output directories, verify target PID
  owner, executable, and start time before and after attaching.
- Python: 3.9+ standard library only, `argparse`, `--json` output where useful,
  non-zero exit when nothing was recognised.
- Support a root prefix (`HOST_ROOT`, `PROC_ROOT`, `LAB_TUNE_TEST_ROOT`) when
  reading `/proc` or `/sys` so tests can use fake trees.
- Never invent tool flags or JVM options: check them against the installed tool
  (`--help`, `java -XX:+PrintFlagsFinal -version`, `jfr metadata`, `jcmd PID help`)
  and state JDK version differences (21 vs 25) explicitly. For native tools,
  check `gcc --help=common`, `gcc --help=target`, `readelf --help`, and
  `perf <cmd> --help`, and name the versions checked.

## Before committing

```bash
./scripts/validate-all.sh
WALKTHROUGH_TESTS=1 ./tests/run-tests.sh
shellcheck --severity=warning skills/*/scripts/*.sh skills/*/assets/*/*.sh scripts/*.sh install.sh tests/*.sh
claude plugin eval . --case <changed-skill-case> --runs 3 --max-cost-usd 5   # when a skill's behaviour changes
```

Bump `VERSION`, `.claude-plugin/plugin.json`, the marketplace entry, and
`.codex-plugin/plugin.json` together when releasing, move the CHANGELOG
section from "unreleased" to a dated version, and tag `vX.Y.Z` on `main`.
