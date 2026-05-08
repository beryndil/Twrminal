"""Slash-command scanner route (item 2.3).

``GET /api/commands`` scans three locations for slash-command
definitions and returns the merged list so the frontend composer
typeahead can offer completions on ``/`` keypress.

Scanned locations and their ``source`` label:

* ``~/.claude/commands/**/*.md`` — user-level commands, ``source="user_commands"``
* ``~/.claude/skills/*/SKILL.md`` — user-level skills, ``source="user_skills"``
* ``<working_dir>/.claude/commands/**/*.md`` — project-level commands,
  ``source="project_commands"`` (working_dir defaults to ``Path.cwd()``
  when no project context is available at scan time)

Name extraction
---------------
Every ``.md`` file may start with YAML frontmatter bounded by ``---``
lines. When a ``name:`` key is present it takes precedence; otherwise
the stem of the file path (``commands/foo/bar.md`` → ``foo/bar``,
``commands/foo.md`` → ``foo``) is used as the name. ``SKILL.md``
files always live inside a directory whose name IS the skill slug —
that directory name is used as the fallback if ``name:`` is absent.

Description extraction
----------------------
The ``description:`` frontmatter key is used when present. If absent
the first non-empty non-frontmatter line of the file body is used,
truncated at 120 characters. If the file is empty the description is
the empty string.

Errors
------
The endpoint never 500s on scan errors: a missing directory is skipped
silently; a file that fails to parse logs a DEBUG-level message and is
skipped. The caller always receives a (possibly empty) list.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Query

from bearings.web.models.commands import CommandOut

logger = logging.getLogger(__name__)

router = APIRouter()

# Frontmatter delimiter
_FM_DELIM = "---"
# Maximum description length when inferred from file body
_DESC_MAX = 120
# Locations (relative to home) for user-level assets
_USER_COMMANDS_RELDIRS = (Path(".claude") / "commands",)
_USER_SKILLS_RELDIR = Path(".claude") / "skills"
# Project-level commands dir (relative to working_dir)
_PROJECT_COMMANDS_RELDIR = Path(".claude") / "commands"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_fields, body_text) from a markdown string.

    ``frontmatter_fields`` is empty when no valid ``---``-bounded block
    is present.  Only string-valued top-level keys are extracted; the
    body is everything after the closing ``---``.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM_DELIM:
        return {}, text
    end = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FM_DELIM:
            end = i
            break
    if end == -1:
        return {}, text
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1 :])
    fields: dict[str, str] = {}
    for fm_line in fm_lines:
        if ":" not in fm_line:
            continue
        key, _, val = fm_line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val:
            fields[key] = val
    return fields, body


def _first_body_line(body: str) -> str:
    """Return the first non-empty line of body, truncated to ``_DESC_MAX``."""
    for line in body.splitlines():
        stripped = line.strip()
        # Skip heading markers and decorators
        if stripped and not stripped.startswith("#"):
            return stripped[:_DESC_MAX]
    return ""


def _scan_command_file(path: Path, fallback_name: str, source: str) -> CommandOut | None:
    """Parse one ``.md`` file into a :class:`CommandOut`.

    Returns ``None`` if the file cannot be read or yields no useful content.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.debug("commands scanner: could not read %s", path)
        return None
    fields, body = _parse_frontmatter(text)
    name = fields.get("name") or fallback_name
    description = fields.get("description") or _first_body_line(body)
    return CommandOut(name=name, description=description, source=source)


def _scan_commands_dir(root: Path, source: str) -> list[CommandOut]:
    """Recursively collect ``CommandOut`` entries from ``.md`` files under *root*.

    The ``name`` fallback for a file at ``root/foo/bar.md`` is ``foo/bar``.
    """
    results: list[CommandOut] = []
    if not root.is_dir():
        return results
    for md_path in sorted(root.rglob("*.md")):
        rel = md_path.relative_to(root)
        # Strip the ``.md`` suffix to form the fallback name; convert
        # path separators to ``/`` for cross-platform consistency.
        fallback = "/".join(rel.with_suffix("").parts)
        entry = _scan_command_file(md_path, fallback, source)
        if entry is not None:
            results.append(entry)
    return results


def _scan_skills_dir(skills_root: Path) -> list[CommandOut]:
    """Collect one ``CommandOut`` per skill directory under *skills_root*.

    Each skill is a directory containing a ``SKILL.md`` file. The
    directory name is the fallback ``name`` if frontmatter is absent.
    """
    results: list[CommandOut] = []
    if not skills_root.is_dir():
        return results
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        entry = _scan_command_file(skill_md, skill_dir.name, "user_skills")
        if entry is not None:
            results.append(entry)
    return results


def _scan_all(working_dir: Path | None = None) -> list[CommandOut]:
    """Merge all three scan locations and return a deduplicated list.

    Deduplication key is ``(name, source)``; first occurrence wins.
    """
    home = Path.home()
    results: list[CommandOut] = []
    seen: set[tuple[str, str]] = set()

    def _add(entries: list[CommandOut]) -> None:
        for e in entries:
            key = (e.name, e.source)
            if key not in seen:
                seen.add(key)
                results.append(e)

    for rel in _USER_COMMANDS_RELDIRS:
        _add(_scan_commands_dir(home / rel, "user_commands"))
    _add(_scan_skills_dir(home / _USER_SKILLS_RELDIR))
    wd = working_dir if working_dir is not None else Path.cwd()
    _add(_scan_commands_dir(wd / _PROJECT_COMMANDS_RELDIR, "project_commands"))
    return results


@router.get("/api/commands", response_model=list[CommandOut], operation_id="list-commands")
async def list_commands(
    cwd: str | None = Query(
        default=None,
        description=(
            "Working directory used to scope project-level commands "
            "(.claude/commands/**/*.md walk-up from this path). "
            "Omit to use the server's launch directory (backward compat)."
        ),
    ),
) -> list[CommandOut]:
    """Return all discovered slash-commands from user + project locations.

    When ``cwd`` is supplied the project-commands scan is rooted there,
    so the response is scoped to that session's working directory.
    Omitting ``cwd`` preserves the previous behaviour (server process cwd).
    """
    working_dir = Path(cwd) if cwd else None
    return _scan_all(working_dir)


__all__ = ["router"]
