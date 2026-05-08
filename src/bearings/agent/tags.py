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

Multi-tag precedence
--------------------

When a session carries multiple tags, the first tag with a non-null
``default_model`` / ``working_dir`` wins. The DB layer hands the list
to the agent in inheritance-precedence order — see
:func:`bearings.db.tags.list_for_session_ordered` for the ordering
contract (project class first, then general, then severity; ties
break on per-class ``sort_order`` then ``name``).

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
    * First tag with a non-null ``default_model`` (tags must arrive in
      inheritance-precedence order — see
      :func:`bearings.db.tags.list_for_session_ordered`).
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
    """Load CLAUDE.md files from each tag's ``working_dir`` in concatenation order.

    Returns CLAUDE.md file contents as a tuple of strings ordered from
    lowest-precedence tag to highest-precedence tag. The system prompt
    assembler concatenates the tuple in order, so the highest-precedence
    tag's CLAUDE.md appears last and wins on any directive conflicts.

    Precedence is defined by
    :func:`bearings.db.tags.list_for_session_ordered` (project >
    general > severity, then per-class ``sort_order``); this helper
    iterates that list in reverse so the highest-precedence block
    lands at the end of the returned tuple.

    Missing files or directories are silently skipped. If no tags
    exist or none have a ``working_dir`` set, returns an empty tuple.
    """
    from bearings.db import tags as tags_db

    ordered_tags = await tags_db.list_for_session_ordered(connection, session_id)

    blocks = []
    for tag in reversed(ordered_tags):  # lowest-precedence first; highest gets appended last
        if tag.working_dir is None:
            continue
        content = _load_claude_md_block(tag.working_dir)
        if content is not None:
            blocks.append(content)
    return tuple(blocks)


async def resolve_tag_memory_blocks(
    connection: aiosqlite.Connection,
    session_id: str,
) -> tuple[str, ...]:
    """Load enabled tag-memory bodies for each tag attached to ``session_id``.

    Returns memory ``body`` strings as a tuple ordered from
    lowest-precedence tag to highest-precedence tag. Within each tag,
    memories are in insertion order (``id ASC``). The system prompt
    assembler appends these after the CLAUDE.md extras tuple so DB
    memories win over per-tag CLAUDE.md content on any directive
    conflicts.

    Precedence follows
    :func:`bearings.db.tags.list_for_session_ordered` (project >
    general > severity, then per-class ``sort_order``); this helper
    iterates that list in reverse so the highest-precedence tag's
    memories land last.

    Memories with ``enabled=False`` are excluded. If no tags exist or
    none have enabled memories, returns an empty tuple.
    """
    from bearings.db import memories as memories_db
    from bearings.db import tags as tags_db

    ordered_tags = await tags_db.list_for_session_ordered(connection, session_id)

    blocks: list[str] = []
    for tag in reversed(ordered_tags):  # lowest-precedence first; highest appended last
        tag_memories = await memories_db.list_for_tag(connection, tag.id, only_enabled=True)
        for memory in tag_memories:
            blocks.append(memory.body)
    return tuple(blocks)


__all__ = [
    "resolve_claude_md_blocks",
    "resolve_default_model",
    "resolve_tag_memory_blocks",
    "resolve_working_dir",
]
