# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- Skills in this checkout are discovered through `.claude/skills/` symlinks;
  invoke one with `/<skill-name>` or let Claude select it by description.
- Validate the plugin with `claude plugin validate .` (also run by
  `scripts/validate-all.sh`). Test an install from the checkout with
  `claude plugin marketplace add ./` then
  `claude plugin install optimization-skills@optimization-skills`.
- When a skill script needs root (lab mode, eBPF), print the command for the
  user to run with `! sudo ...` rather than attempting privilege escalation.
