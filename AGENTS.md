# Repository guide for coding agents

This repository publishes agent skills for Java/JVM performance work on Linux.
The same `skills/` tree must work unchanged in OpenAI Codex and Claude Code.

## Layout

```text
skills/<name>/SKILL.md          frontmatter + workflow (shared by both agents)
skills/<name>/references/*.md   detail loaded on demand; linked from SKILL.md
skills/<name>/scripts/*         executable helpers; paths are relative to the skill dir
skills/<name>/agents/openai.yaml Codex UI metadata (ignored by Claude)
.claude-plugin/                  Claude Code plugin + marketplace manifests
.claude/skills/, .agents/skills/ symlinks to skills/ for in-repo discovery
scripts/validate_skills.py       bundled validator (both agents' rules)
tests/                           script tests and real JDK fixtures
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
- New skill: add the directory, both symlinks
  (`ln -s ../../skills/<name> .claude/skills/<name>` and the same under
  `.agents/skills/`), a README table row, and tests for any script.

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
  and state JDK version differences (21 vs 25) explicitly.

## Before committing

```bash
./scripts/validate-all.sh
./tests/run-tests.sh
shellcheck skills/*/scripts/*.sh scripts/*.sh install.sh tests/*.sh
```

Bump `VERSION`, `.claude-plugin/plugin.json`, and the marketplace entry
together when releasing.
