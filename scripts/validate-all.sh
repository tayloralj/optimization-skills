#!/usr/bin/env bash
set -euo pipefail

# Validate every public skill without requiring network access or host changes.
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -n ${SKILL_VALIDATOR:-} ]]; then
  validator=$SKILL_VALIDATOR
elif [[ -n ${CODEX_HOME:-} ]]; then
  validator=$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py
elif [[ -n ${HOME:-} ]]; then
  validator=$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py
else
  printf 'Set SKILL_VALIDATOR, CODEX_HOME, or HOME.\n' >&2
  exit 2
fi

if [[ ! -f "$validator" ]]; then
  printf 'Skill validator not found: %s\n' "$validator" >&2
  printf 'Set SKILL_VALIDATOR to the quick_validate.py supplied with Codex.\n' >&2
  exit 2
fi

status=0
for skill_dir in "$repo_root"/skills/*; do
  [[ -d "$skill_dir" ]] || continue
  printf 'Validating %s\n' "$(basename "$skill_dir")"
  python3 "$validator" "$skill_dir" || status=1
done

exit "$status"
