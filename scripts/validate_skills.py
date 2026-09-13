#!/usr/bin/env python3
"""Offline structural validator for a skill collection shared by Codex and Claude Code.

It enforces the intersection of both agents' SKILL.md rules plus repository
conventions. Python 3.9+ standard library only; no network, no host changes.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

ALLOWED_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_SKILL_LINES = 500
SHORT_DESCRIPTION_RANGE = (25, 64)
RESOURCE_RE = re.compile(r"(?<![\w/.-])((?:references|scripts|assets)/[A-Za-z0-9_./-]+[A-Za-z0-9_])")
AGENT_LINK_DIRS = (".claude/skills", ".agents/skills")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Parse the flat subset of YAML frontmatter used by skills.

    Top-level `key: value` scalars are returned; nested mappings (for example
    `metadata:`) are recorded with an empty value. Block scalars are rejected
    because both agents' tooling handles single-line descriptions most reliably.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    block, body = text[4:end], text[end + 5:]
    fields: dict[str, str] = {}
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw[0] in " \t":
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise ValueError(f"unparseable frontmatter line: {raw!r}")
        value = value.strip()
        if value in {"|", ">", "|-", ">-"}:
            raise ValueError(f"block scalar for {key!r}; use a single-line value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif value and (": " in value or " #" in value or value[0] in "&*!|>%@`[]{}'\""):
            raise ValueError(f"unquoted value for {key.strip()!r} is not valid YAML (contains ': ' or ' #' or starts "
                             "with a YAML indicator); reword or quote it")
        fields[key.strip()] = value
    return fields, body


def parse_openai_interface(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    in_interface = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        if not raw.startswith(" "):
            in_interface = raw.rstrip() == "interface:"
            continue
        if in_interface:
            key, _, value = raw.strip().partition(":")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key] = value
    return values


def strip_code_fences(body: str) -> str:
    return re.sub(r"```.*?```", "", body, flags=re.S)


def validate_skill(skill_dir: Path, all_names: set[str], report: Report) -> None:
    where = f"skills/{skill_dir.name}"
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        report.error(where, "missing SKILL.md")
        return
    text = skill_md.read_text(encoding="utf-8")
    try:
        parsed = parse_frontmatter(text)
    except ValueError as exc:
        report.error(where, str(exc))
        return
    if parsed is None:
        report.error(where, "SKILL.md must start with '---' frontmatter closed by '---'")
        return
    fields, body = parsed

    unexpected = set(fields) - ALLOWED_KEYS
    if unexpected:
        report.error(where, f"unexpected frontmatter keys {sorted(unexpected)}; allowed {sorted(ALLOWED_KEYS)}")
    name = fields.get("name", "")
    if not NAME_RE.match(name) or len(name) > MAX_NAME:
        report.error(where, f"name {name!r} must be hyphen-case and at most {MAX_NAME} characters")
    if name != skill_dir.name:
        report.error(where, f"name {name!r} must equal directory name")
    description = fields.get("description", "")
    if not description:
        report.error(where, "missing description")
    elif len(description) > MAX_DESCRIPTION:
        report.error(where, f"description is {len(description)} characters; maximum {MAX_DESCRIPTION}")
    if "<" in description or ">" in description:
        report.error(where, "description must not contain angle brackets")
    if description and not re.search(r"\bUse (when|to|for|after|before)\b", description):
        report.error(where, "description must state when to use the skill ('Use when/to/for/after/before ...')")

    line_count = text.count("\n") + 1
    if line_count > MAX_SKILL_LINES:
        report.error(where, f"SKILL.md has {line_count} lines; keep it under {MAX_SKILL_LINES} and move detail to references/")

    # Agent-neutral wording: `$skill-name` is Codex invocation syntax.
    for match in re.finditer(r"\$([a-z0-9-]+)", strip_code_fences(body)):
        if match.group(1) in all_names:
            report.error(where, f"use agent-neutral wording ('the `{match.group(1)}` skill') instead of ${match.group(1)}")

    referenced: set[str] = set()
    for source in [skill_md, *sorted((skill_dir / "references").glob("*.md"))]:
        for match in RESOURCE_RE.finditer(source.read_text(encoding="utf-8")):
            referenced.add(match.group(1).rstrip("."))
    for rel in sorted(referenced):
        if not (skill_dir / rel).exists():
            report.error(where, f"references missing resource {rel}")
    for folder in ("references", "scripts"):
        base = skill_dir / folder
        if not base.is_dir():
            continue
        for item in sorted(base.rglob("*")):
            if item.is_file() and "__pycache__" not in item.parts:
                rel = item.relative_to(skill_dir).as_posix()
                if rel not in referenced and not any(rel.startswith(r.rstrip("/") + "/") for r in referenced):
                    report.error(where, f"{rel} is not referenced from SKILL.md or a reference file")
    for script in sorted((skill_dir / "scripts").glob("*")):
        if script.suffix in {".sh", ".py"}:
            if not script.stat().st_mode & stat.S_IXUSR:
                report.error(where, f"{script.name} must be executable")
            if not script.read_text(encoding="utf-8").startswith("#!/usr/bin/env "):
                report.error(where, f"{script.name} must start with a '#!/usr/bin/env' shebang")

    openai_yaml = skill_dir / "agents" / "openai.yaml"
    if not openai_yaml.is_file():
        report.error(where, "missing agents/openai.yaml (Codex UI metadata)")
    else:
        interface = parse_openai_interface(openai_yaml)
        for key in ("display_name", "short_description", "default_prompt"):
            if not interface.get(key):
                report.error(where, f"agents/openai.yaml missing interface.{key}")
        short = interface.get("short_description", "")
        low, high = SHORT_DESCRIPTION_RANGE
        if short and not low <= len(short) <= high:
            report.error(where, f"short_description must be {low}-{high} characters (is {len(short)})")
        if f"${name}" not in interface.get("default_prompt", ""):
            report.error(where, f"default_prompt should invoke ${name} for Codex")


def validate_plugin(repo: Path, names: list[str], report: Report) -> None:
    plugin_path = repo / ".claude-plugin" / "plugin.json"
    market_path = repo / ".claude-plugin" / "marketplace.json"
    try:
        plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
        market = json.loads(market_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.error(".claude-plugin", f"cannot read manifests: {exc}")
        return
    entries = [p for p in market.get("plugins", []) if p.get("name") == plugin.get("name")]
    if len(entries) != 1:
        report.error(".claude-plugin", "marketplace.json must list plugin.json's plugin exactly once")
    elif entries[0].get("version") not in (None, plugin.get("version")):
        report.error(".claude-plugin", "marketplace entry version differs from plugin.json version")
    version_file = repo / "VERSION"
    if version_file.is_file() and version_file.read_text(encoding="utf-8").strip() != plugin.get("version"):
        report.error("VERSION", "must match .claude-plugin/plugin.json version")

    for link_dir in AGENT_LINK_DIRS:
        base = repo / link_dir
        present = {p.name for p in base.iterdir()} if base.is_dir() else set()
        for name in names:
            link = base / name
            if not link.is_symlink() or os.readlink(link) != f"../../skills/{name}":
                report.error(link_dir, f"{name} must be a symlink to ../../skills/{name}")
        for extra in sorted(present - set(names)):
            report.error(link_dir, f"stale entry {extra}")

    readme = (repo / "README.md").read_text(encoding="utf-8")
    for name in names:
        if f"`{name}`" not in readme:
            report.error("README.md", f"skill table does not mention `{name}`")


def github_slug(heading: str) -> str:
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def validate_links(repo: Path, report: Report) -> None:
    """Relative Markdown links (and their #anchors) in project docs must resolve."""
    docs = [repo / "README.md", repo / "AGENTS.md", repo / "CHANGELOG.md", *sorted((repo / "docs").rglob("*.md")),
            *sorted((repo / "evals").glob("*.md"))]
    link_re = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
    for doc in docs:
        if not doc.is_file():
            continue
        text = strip_code_fences(doc.read_text(encoding="utf-8"))
        for target in link_re.findall(text):
            if re.match(r"^[a-z]+:", target):
                continue
            path_part, _, anchor = target.partition("#")
            dest = (doc.parent / path_part).resolve() if path_part else doc
            where = str(doc.relative_to(repo))
            if not dest.exists():
                report.error(where, f"broken link {target}")
                continue
            if anchor and dest.suffix == ".md":
                headings = re.findall(r"^#+\s+(.*)$", strip_code_fences(dest.read_text(encoding="utf-8")), re.M)
                if anchor not in {github_slug(h) for h in headings}:
                    report.error(where, f"broken anchor {target}")


def main(argv: list[str]) -> int:
    repo = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parents[1]
    skills_root = repo / "skills"
    skill_dirs = sorted(p for p in skills_root.iterdir() if p.is_dir())
    names = [p.name for p in skill_dirs]
    report = Report()
    for skill_dir in skill_dirs:
        validate_skill(skill_dir, set(names), report)
    validate_plugin(repo, names, report)
    validate_links(repo, report)
    for line in report.errors:
        print(f"ERROR {line}")
    print(f"validated {len(names)} skills: {'FAILED' if report.errors else 'ok'}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
