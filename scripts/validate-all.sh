#!/usr/bin/env bash
set -euo pipefail

# Validate the collection for both Codex and Claude Code without network access
# or host changes. The bundled validator always runs; agent-supplied validators
# run when installed (set STRICT_AGENT_VALIDATORS=1 to require them).
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
strict=${STRICT_AGENT_VALIDATORS:-0}
status=0

printf '== bundled validator\n'
python3 "$repo_root/scripts/validate_skills.py" "$repo_root" || status=1

if [[ -n ${SKILL_VALIDATOR:-} ]]; then
  codex_validator=$SKILL_VALIDATOR
else
  codex_validator=${CODEX_HOME:-${HOME:-/nonexistent}/.codex}/skills/.system/skill-creator/scripts/quick_validate.py
fi
printf '== codex quick_validate\n'
if [[ -f "$codex_validator" ]] && python3 -c 'import yaml' 2>/dev/null; then
  for skill_dir in "$repo_root"/skills/*/; do
    python3 "$codex_validator" "${skill_dir%/}" >/dev/null || {
      printf 'codex validator rejected %s\n' "$(basename "$skill_dir")" >&2
      python3 "$codex_validator" "${skill_dir%/}" >&2 || true
      status=1
    }
  done
  (( status )) || printf 'codex validator: ok\n'
elif (( strict )); then
  printf 'Codex validator (or PyYAML) not found: %s\n' "$codex_validator" >&2; status=1
else
  printf 'skipped (Codex validator or PyYAML not installed)\n'
fi

printf '== claude plugin validate\n'
if command -v claude >/dev/null 2>&1; then
  for target in "$repo_root" "$repo_root/.claude-plugin/plugin.json" "$repo_root/skills"; do
    claude plugin validate "$target" || status=1
  done
elif (( strict )); then
  printf 'claude CLI not found.\n' >&2; status=1
else
  printf 'skipped (claude CLI not installed)\n'
fi

exit "$status"
