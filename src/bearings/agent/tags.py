"""Tag → :class:`SessionConfig` default-overlay helper.

Per ``docs/architecture-v1.md`` §1.1.4 the ``agent`` layer owns
domain-level glue between the SDK-shaped runtime types
(:class:`bearings.agent.session.SessionConfig`,
:class:`bearings.agent.routing.RoutingDecision`) and the storage layer
(:class:`bearings.db.tags.Tag`). The DB layer cannot import from
``agent`` (arch §3.1 layer rule), so the bridge lives here.

Per ``docs/behavior/checklists.md`` "the chat inherits the checklist's
working directory, model, and tags" — tags carry inheritance fields
(:attr:`Tag.default_model`, :attr:`Tag.working_dir`) that flow into the
session at creation time. Per ``docs/behavior/chat.md`` §"When the user
creates a chat" the user's explicit picks (working directory,
executor model in the routing-preview line) are also valid sources of
the same fields. This module specifies the precedence so the call site
in the API layer (item 1.5+) is deterministic.

Multi-tag precedence with priority ordering
--------------------------------------------

When a session carries multiple tags (passed in priority order from the
DB layer), the first tag with a non-null ``default_model`` /
``working_dir`` wins. Tags are assumed to arrive in priority order:
index 0 = highest priority. Lower-priority tags provide fallbacks.

Caller-supplied overrides beat every tag: the API layer can pass an
explicit ``working_dir`` or executor model, and that overrides any
tag-derived default. This mirrors
:func:`bearings.agent.templates.build_session_config_from_template`'s
resolution order.
"""

from __future__ import annotations

import contextlib
import os

import aiosqlite

from bearings.db.tags import Tag


def resolve_default_model(
    tags: list[Tag],
    *,
    explicit: str | None = None,
) -> str | None:
    """Return the resolved executor model for a session carrying ``tags``.

    Resolution order (most specific wins):

    * ``explicit`` argument — caller's explicit pick from the
      new-session dialog or the API request body.
    * First tag with a non-null ``default_model`` (tags assumed to be
      in priority order: index 0 = highest priority).
    * ``None`` if no source supplies a model — the caller layers
      template / system-default resolution downstream.
    """
    if explicit is not None:
        return explicit
    for tag in tags:
        if tag.default_model is not None:
            return tag.default_model
    return None


def resolve_working_dir(
    tags: list[Tag],
    *,
    explicit: str | None = None,
) -> str | None:
    """Return the resolved working directory for a session carrying ``tags``.

    Same resolution order as :func:`resolve_default_model`. ``None``
    means no source supplied a directory and the caller must surface a
    validation error to the user (per ``docs/behavior/chat.md`` "a
    working directory" is a required field of the new-session dialog).
    """
    if explicit is not None:
        return explicit
    for tag in tags:
        if tag.working_dir is not None:
            return tag.working_dir
    return None


def _load_claude_md_block(working_dir: str) -> str | None:
    """Load a single CLAUDE.md file from a working directory.

    Returns the file contents as a string, or None if the file is missing
    or can't be read. This is a sync helper to avoid ASYNC240 linting
    warnings in the async caller.
    """
    expanded_dir = os.path.expanduser(working_dir)
    claude_md_path = os.path.join(expanded_dir, "CLAUDE.md")
    if os.path.isfile(claude_md_path):
        with (
            contextlib.suppress(OSError, UnicodeDecodeError),
            open(claude_md_path, encoding="utf-8") as f,
        ):
            return f.read()
    return None


async def resolve_claude_md_blocks(
    connection: aiosqlite.Connection,
    session_id: str,
) -> tuple[str, ...]:
    """Load CLAUDE.md files from each tag's working_dir in reverse priority order.

    Returns CLAUDE.md file contents as a tuple of strings, ordered from
    lowest-priority tag to highest-priority tag. This ordering ensures
    that when the system prompt assembler concatenates them, the
    highest-priority tag's CLAUDE.md appears last and thus wins on
    any directive conflicts.

    Missing files or directories are silently skipped. If no tags exist
    or none have a working_dir set, returns an empty tuple.
    """
    from bearings.db import tags as tags_db

    ordered_tags = await tags_db.list_for_session_ordered(connection, session_id)

    blocks = []
    for tag in reversed(ordered_tags):  # Reverse: lowest priority first
        if tag.working_dir is None:
            continue
        content = _load_claude_md_block(tag.working_dir)
        if content is not None:
            blocks.append(content)
    return tuple(blocks)


__all__ = ["resolve_claude_md_blocks", "resolve_default_model", "resolve_working_dir"]
