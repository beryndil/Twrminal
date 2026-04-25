"""Disk walker for Claude Code slash commands and skills.

Scans the user's `~/.claude/commands` tree, per-project `.claude/commands`,
user `~/.claude/skills` tree, and plugin directories under
`~/.claude/plugins/marketplaces/*/plugins/*/{commands,skills}`. Parses
optional YAML frontmatter for a `description` field (best-effort — no
YAML dependency, just a small line scanner).

The output is a flat list of `CommandOut` entries with a stable `slug`
like `fad:ship` or `pr-review-toolkit:review-pr` — the same token a user
types after `/` in the CLI. Precedence when slugs collide:
    project > user > plugin
Later sources are silently dropped so the UI never shows duplicates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from bearings.api.models import CommandOut
from bearings.config import CommandsScope

Kind = Literal["command", "skill"]
Scope = Literal["user", "project", "plugin"]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_DESC_RE = re.compile(r"^description\s*:\s*(.+?)\s*$", re.MULTILINE)


def _parse_description(text: str) -> str:
    """Extract the `description` field from a markdown file's YAML
    frontmatter. Returns an empty string if there's no frontmatter or no
    `description` key — both are valid states per the Claude Code spec."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return ""
    desc = _DESC_RE.search(match.group(1))
    if not desc:
        return ""
    value = desc.group(1).strip()
    # Strip matching quotes if present — common in YAML hand-written by
    # humans. Leave unbalanced quotes alone; the string is informational.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _read_description(path: Path) -> str:
    try:
        # Frontmatter blocks are short — 4 KB is plenty and caps the
        # cost of scanning thousands of files.
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return ""
    return _parse_description(head)


def _iter_no_symlinks(root: Path) -> list[Path]:
    """Manual recursive walk of `root` for `*.md` files that does NOT
    descend into symlinked directories and does NOT follow symlinked
    files. `Path.rglob` would follow both — a symlink in a user's
    `.claude/commands` could point at `/etc` or anywhere else on disk
    and the scanner would happily read it (security audit 2026-04-21
    §5)."""
    out: list[Path] = []
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in sorted(entries):
            # `is_symlink` does not call stat() on the target, so it
            # also costs nothing for the dangling-symlink case.
            if entry.is_symlink():
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file() and entry.suffix == ".md":
                out.append(entry)
    return out


def _walk_commands(root: Path) -> list[tuple[str, Path]]:
    """Return (slug, path) for every `*.md` under `root`. Nested
    directories become `:` separators — `fad/ship.md` → `fad:ship`.
    Symlinked files and directories are skipped — see
    `_iter_no_symlinks`."""
    if not root.is_dir() or root.is_symlink():
        return []
    out: list[tuple[str, Path]] = []
    try:
        for path in _iter_no_symlinks(root):
            rel = path.relative_to(root).with_suffix("")
            slug = ":".join(rel.parts)
            if not slug:
                continue
            out.append((slug, path))
    except (PermissionError, OSError):
        return out
    return out


def _walk_skills(root: Path) -> list[tuple[str, Path]]:
    """Return (slug, path) for every `<skill-dir>/SKILL.md` directly
    under `root`. Skills are single-level — the skill name is the
    directory name. Symlinked skill dirs and SKILL.md files are
    skipped — see `_iter_no_symlinks` for the rationale."""
    if not root.is_dir() or root.is_symlink():
        return []
    out: list[tuple[str, Path]] = []
    try:
        for entry in sorted(root.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if skill_file.is_symlink() or not skill_file.is_file():
                continue
            out.append((entry.name, skill_file))
    except (PermissionError, OSError):
        return out
    return out


def _entries_from(
    pairs: list[tuple[str, Path]],
    *,
    kind: Kind,
    scope: Scope,
    prefix: str = "",
) -> list[CommandOut]:
    entries: list[CommandOut] = []
    for slug, path in pairs:
        full_slug = f"{prefix}{slug}" if prefix else slug
        entries.append(
            CommandOut(
                slug=full_slug,
                description=_read_description(path),
                kind=kind,
                scope=scope,
                source_path=str(path),
            )
        )
    return entries


def _plugin_roots(home: Path) -> list[Path]:
    """Every `plugins/<plugin>` dir under every installed marketplace.
    Shape: `~/.claude/plugins/marketplaces/<marketplace>/plugins/<plugin>`.
    Returns [] when the plugins dir doesn't exist. Symlinked
    marketplaces and symlinked plugin dirs are skipped — see
    `_iter_no_symlinks` for the rationale."""
    base = home / ".claude" / "plugins" / "marketplaces"
    if not base.is_dir() or base.is_symlink():
        return []
    out: list[Path] = []
    try:
        for marketplace in sorted(base.iterdir()):
            if marketplace.is_symlink() or not marketplace.is_dir():
                continue
            plugins_dir = marketplace / "plugins"
            if plugins_dir.is_symlink() or not plugins_dir.is_dir():
                continue
            for plugin in sorted(plugins_dir.iterdir()):
                if plugin.is_symlink() or not plugin.is_dir():
                    continue
                out.append(plugin)
    except (PermissionError, OSError):
        return out
    return out


def collect(
    *,
    home: Path,
    project_cwd: Path | None,
    scope: CommandsScope = "all",
) -> list[CommandOut]:
    """Scan every source and return a flat, dedup'd list.

    `home` is the directory containing `.claude/` — pass `Path.home()` in
    production and a tmp dir in tests. `project_cwd` (when provided) adds
    its own `.claude/commands` and `.claude/skills` at project scope.

    `scope` narrows which sources are walked (`commands.scope` in
    config, 2026-04-21 security audit §5):
      - "all"     — project + user + plugins (default, today's behavior)
      - "user"    — project + user; skip plugins
      - "project" — project only; skip user + plugins

    Precedence: project > user > plugin. First wins on slug collision.
    """
    include_user = scope in ("all", "user")
    include_plugins = scope == "all"

    entries: list[CommandOut] = []

    if project_cwd is not None:
        entries.extend(
            _entries_from(
                _walk_commands(project_cwd / ".claude" / "commands"),
                kind="command",
                scope="project",
            )
        )
        entries.extend(
            _entries_from(
                _walk_skills(project_cwd / ".claude" / "skills"),
                kind="skill",
                scope="project",
            )
        )

    if include_user:
        entries.extend(
            _entries_from(
                _walk_commands(home / ".claude" / "commands"),
                kind="command",
                scope="user",
            )
        )
        entries.extend(
            _entries_from(
                _walk_skills(home / ".claude" / "skills"),
                kind="skill",
                scope="user",
            )
        )

    if include_plugins:
        for plugin in _plugin_roots(home):
            prefix = f"{plugin.name}:"
            entries.extend(
                _entries_from(
                    _walk_commands(plugin / "commands"),
                    kind="command",
                    scope="plugin",
                    prefix=prefix,
                )
            )
            entries.extend(
                _entries_from(
                    _walk_skills(plugin / "skills"),
                    kind="skill",
                    scope="plugin",
                    prefix=prefix,
                )
            )

    seen: set[str] = set()
    deduped: list[CommandOut] = []
    for entry in entries:
        if entry.slug in seen:
            continue
        seen.add(entry.slug)
        deduped.append(entry)
    deduped.sort(key=lambda e: e.slug.lower())
    return deduped
