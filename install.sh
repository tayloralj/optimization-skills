#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
umask 077

# Install skills into personal Codex and/or Claude Code skill directories.
# Only creates or removes entries inside those directories; never touches an
# entry it did not create (a symlink into this repository or a marked copy).
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
marker=.installed-from-optimization-skills

usage() {
  cat <<EOF
Usage: ${0##*/} [--codex] [--claude] [--copy] [--uninstall] [--dry-run] [SKILL...]

Targets (default: both):
  --codex      \${CODEX_SKILLS_DIR:-\$HOME/.agents/skills}
  --claude     \${CLAUDE_CONFIG_DIR:-\$HOME/.claude}/skills
Mode:
  (default)    symlink each skill to this checkout (updates with git pull)
  --copy       copy files instead of linking
  --uninstall  remove entries previously installed from this repository
  --dry-run    print actions without changing anything

With no SKILL arguments every skill is installed. profiling-readiness is always
included because the specialised skills route through it. Subsets omit other
workflow destinations: install the whole collection for complete investigations.
Use CODEX_SKILLS_DIR to override the Codex directory (including legacy cleanup).

Claude Code users may prefer the plugin instead:
  claude plugin marketplace add tayloralj/optimization-skills
  claude plugin install optimization-skills@optimization-skills
EOF
}

want_codex=0; want_claude=0; copy=0; uninstall=0; dry_run=0
declare -a requested=()
while (( $# )); do
  case "$1" in
    --codex) want_codex=1 ;;
    --claude) want_claude=1 ;;
    --copy) copy=1 ;;
    --uninstall) uninstall=1 ;;
    --dry-run) dry_run=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    *) requested+=("$1") ;;
  esac
  shift
done
(( want_codex || want_claude )) || { want_codex=1; want_claude=1; }

declare -a skills=()
if (( ${#requested[@]} )); then
  for name in "${requested[@]}"; do
    [[ "$name" =~ ^[a-z0-9-]+$ && -f "$repo_root/skills/$name/SKILL.md" ]] || {
      printf 'Unknown skill: %s\n' "$name" >&2; exit 2;
    }
  done
  if (( ! uninstall )); then
    printf 'Subset install: other referenced skills are omitted; install without SKILL arguments for complete workflows.\n' >&2
  fi
  skills=("${requested[@]}")
  [[ " ${skills[*]} " == *" profiling-readiness "* ]] || skills=(profiling-readiness "${skills[@]}")
else
  for dir in "$repo_root"/skills/*/; do
    dir=${dir%/}
    skills+=("${dir##*/}")
  done
fi

declare -a targets=()
(( want_codex )) && targets+=("${CODEX_SKILLS_DIR:-$HOME/.agents/skills}")
(( want_claude )) && targets+=("${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills")

run() {
  printf '+ %s\n' "$*"
  (( dry_run )) || "$@"
}

owned_by_us() {
  local entry=$1 name=$2
  if [[ -L "$entry" ]]; then
    [[ $(readlink "$entry") == "$repo_root/skills/$name" ]]
  else
    [[ -d "$entry" && -f "$entry/$marker" ]]
  fi
}

status=0
for target in "${targets[@]}"; do
  if (( ! uninstall )); then
    [[ -d "$target" ]] || run install -d -m 700 "$target"
  fi
  for name in "${skills[@]}"; do
    entry=$target/$name
    if (( uninstall )); then
      if [[ -e "$entry" || -L "$entry" ]]; then
        if owned_by_us "$entry" "$name"; then
          if [[ -L "$entry" ]]; then run rm -- "$entry"; else run rm -r -- "$entry"; fi
        else
          printf 'skip %s: not installed from this repository\n' "$entry" >&2; status=1
        fi
      fi
      continue
    fi
    if [[ -e "$entry" || -L "$entry" ]]; then
      if owned_by_us "$entry" "$name"; then
        if (( copy )) && [[ ! -L "$entry" ]]; then
          run rm -r -- "$entry"
        elif (( ! copy )) && [[ -L "$entry" ]]; then
          printf 'ok   %s (already linked)\n' "$entry"; continue
        else
          if [[ -L "$entry" ]]; then run rm -- "$entry"; else run rm -r -- "$entry"; fi
        fi
      else
        printf 'skip %s: exists and was not installed from this repository\n' "$entry" >&2
        status=1; continue
      fi
    fi
    if (( copy )); then
      run cp -R -- "$repo_root/skills/$name" "$entry"
      (( dry_run )) || : > "$entry/$marker"
    else
      run ln -s -- "$repo_root/skills/$name" "$entry"
    fi
  done
done

(( dry_run )) || (( uninstall )) || printf 'Restart Codex / Claude Code sessions to pick up new skills.\n'
exit "$status"
