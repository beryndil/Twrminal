"""System-prompt layer assembler for the Inspector Instructions tab.

Produces a typed breakdown of every layer that forms the executor's
assembled system prompt.  The breakdown is consumed by
``GET /api/sessions/{id}/system_prompt`` and surfaced in the
Inspector Instructions tab (``InspectorInstructions.svelte``).

Layer order
-----------

1. **``session_instructions``** — per-session steering from the session
   row's ``session_instructions`` column.  Omitted when ``None`` or
   empty-after-strip.
2. **``baseline``** — Bearings core surface
   (:data:`bearings.agent.bearings_mcp.CLOSE_SESSION_INSTRUCTION`).
   Always present.
3. **``project_claude_md``** — one layer per ``CLAUDE.md`` found walking
   up from the session's ``working_dir`` to the filesystem root.
   Each file yields its own row so the inspector can attribute the
   content to the exact path.
4a. **``tag_claude_md``** — one layer per tag whose ``working_dir`` yields
    a readable ``CLAUDE.md``.  Tag order mirrors the precedence order in
    :func:`bearings.db.tags.list_for_session_ordered` (project class
    first, then general, then severity; ties break on ``sort_order``
    then ``name``) then reversed so the highest-precedence block lands
    last.
4b. **``tag_memory``** — one layer per enabled row in the
    ``tag_memories`` table for the session's tags, in the same
    reversed-precedence tag order. Memory bodies are DB-resident;
    ``source_path`` is ``None``. Within each tag, memories are ordered
    by insertion (``id ASC``).
5. **``template_baseline``** — not emitted in v18.  Template
   ``system_prompt_baseline`` is copied into ``session_instructions``
   at session-creation time
   (``agent/templates.py`` §"system-prompt baseline flows through").
   There is no ``template_id`` FK on the session row, so the original
   baseline cannot be recovered.  The kind is defined here for API-shape
   stability; the assembler never emits it.

Token counts
------------

Token counts are approximated as ``len(body) // 4`` — a rough but
consistent estimate that avoids a heavy tokenizer dependency.  The
API response documents the approximation via the
``SystemPromptLayersOut.token_count_approximate`` flag (always
``true``).
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field

import aiosqlite

from bearings.agent.bearings_mcp import CLOSE_SESSION_INSTRUCTION
from bearings.db import memories as memories_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db.sessions import Session
from bearings.db.tags import Tag

# ---------------------------------------------------------------------------
# Layer kind constants (exported so the route and tests share the alphabet)
# ---------------------------------------------------------------------------

LAYER_KIND_BASELINE: str = "baseline"
LAYER_KIND_PROJECT_CLAUDE_MD: str = "project_claude_md"
LAYER_KIND_TAG_CLAUDE_MD: str = "tag_claude_md"
LAYER_KIND_TAG_MEMORY: str = "tag_memory"
LAYER_KIND_SESSION_INSTRUCTIONS: str = "session_instructions"
LAYER_KIND_TEMPLATE_BASELINE: str = "template_baseline"

KNOWN_LAYER_KINDS: frozenset[str] = frozenset(
    {
        LAYER_KIND_BASELINE,
        LAYER_KIND_PROJECT_CLAUDE_MD,
        LAYER_KIND_TAG_CLAUDE_MD,
        LAYER_KIND_TAG_MEMORY,
        LAYER_KIND_SESSION_INSTRUCTIONS,
        LAYER_KIND_TEMPLATE_BASELINE,
    }
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemPromptLayer:
    """One layer of the assembled system prompt.

    Attributes:
        kind: Which layer kind this row represents — one of the
            ``LAYER_KIND_*`` constants in this module.
        body: Text body of this layer.  Non-empty for every layer
            returned by :func:`assemble_system_prompt_layers`
            (absent layers are omitted from the list; the frontend
            renders empty-state rows per section when the kind is
            absent).
        token_count: Approximate token count (``len(body) // 4``).
        source_path: Human-readable absolute path provenance for
            layers with a filesystem source (``project_claude_md``,
            ``tag_claude_md``).  ``None`` for ``baseline``,
            ``session_instructions``, ``tag_memory``, and
            ``template_baseline``.
    """

    kind: str
    body: str
    token_count: int
    source_path: str | None = None


@dataclass
class SystemPromptLayers:
    """Full layer breakdown for one session.

    Attributes:
        layers: Ordered list of layers in display order.  Only layers
            with non-empty bodies are included; kinds with no content
            are omitted (the frontend shows an empty-state row per
            section when the kind is absent).
        total_tokens: Sum of all ``layer.token_count`` values.
    """

    layers: list[SystemPromptLayer] = field(default_factory=list)
    total_tokens: int = 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _approx_tokens(text: str) -> int:
    """Approximate token count as ``len(text) // 4``.

    The approximation is consistent across all layers and avoids a
    heavy tokenizer dependency.  The API documents the approximation
    via :attr:`SystemPromptLayersOut.token_count_approximate`.
    """
    return len(text) // 4


def _read_file_body(path: str) -> str | None:
    """Read a text file and return its contents, or ``None`` on any error."""
    with contextlib.suppress(OSError, UnicodeDecodeError), open(path, encoding="utf-8") as fh:
        return fh.read()
    return None


def _walk_up_claude_md(working_dir: str) -> list[tuple[str, str]]:
    """Walk from ``working_dir`` toward the root collecting CLAUDE.md files.

    Returns a list of ``(absolute_path, body)`` pairs in walk-up order
    (directory itself first, then parents, toward the root).  Missing
    files and read errors are silently skipped.
    """
    expanded = os.path.expanduser(working_dir) if working_dir else working_dir
    results: list[tuple[str, str]] = []
    try:
        current = os.path.abspath(expanded)
    except (ValueError, OSError):
        return results
    visited: set[str] = set()
    while True:
        if current in visited:
            break
        visited.add(current)
        candidate = os.path.join(current, "CLAUDE.md")
        if os.path.isfile(candidate):
            body = _read_file_body(candidate)
            if body is not None:
                results.append((candidate, body))
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return results


def _tag_claude_md_layer(working_dir: str) -> SystemPromptLayer | None:
    """Return a ``tag_claude_md`` layer for ``working_dir``, or ``None``.

    Pure sync so that the async assembler avoids ASYNC240 (no os.path
    calls inside an async function).  Returns ``None`` when the working
    directory has no readable ``CLAUDE.md``.
    """
    expanded = os.path.expanduser(working_dir)
    candidate = os.path.join(expanded, "CLAUDE.md")
    if not os.path.isfile(candidate):
        return None
    body = _read_file_body(candidate)
    if body is None:
        return None
    return SystemPromptLayer(
        kind=LAYER_KIND_TAG_CLAUDE_MD,
        body=body,
        token_count=_approx_tokens(body),
        source_path=os.path.abspath(candidate),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _append_session_instructions_layer(
    row: Session,
    layers: list[SystemPromptLayer],
) -> None:
    """Add layer 1 (session_instructions) when present and non-empty."""
    si = row.session_instructions
    if si is not None:
        stripped = si.strip()
        if stripped:
            layers.append(
                SystemPromptLayer(
                    kind=LAYER_KIND_SESSION_INSTRUCTIONS,
                    body=stripped,
                    token_count=_approx_tokens(stripped),
                    source_path=None,
                )
            )


async def _append_tag_layers(
    connection: aiosqlite.Connection,
    ordered_tags: list[Tag],
    layers: list[SystemPromptLayer],
) -> None:
    """Add layers 4a (per-tag CLAUDE.md) and 4b (tag DB memories) to ``layers``."""
    # Iterate in reverse so lowest-precedence tag is first, matching the
    # splice order in :func:`bearings.agent.tags.resolve_claude_md_blocks`.
    for tag in reversed(ordered_tags):
        if tag.working_dir is None:
            continue
        layer = _tag_claude_md_layer(tag.working_dir)
        if layer is not None:
            layers.append(layer)
    # Layer 4b: tag DB memories — re-read on every assemble so edits
    # take effect on the next prompt without restarting the worker.
    for tag in reversed(ordered_tags):
        tag_memories = await memories_db.list_for_tag(
            connection,
            tag.id,
            only_enabled=True,
        )
        for memory in tag_memories:
            layers.append(
                SystemPromptLayer(
                    kind=LAYER_KIND_TAG_MEMORY,
                    body=memory.body,
                    token_count=_approx_tokens(memory.body),
                    source_path=None,
                )
            )


async def assemble_system_prompt_layers(
    connection: aiosqlite.Connection,
    session_id: str,
) -> SystemPromptLayers | None:
    """Assemble the system-prompt layer breakdown for *session_id*.

    Args:
        connection: Open aiosqlite connection to the Bearings DB.
        session_id: The session to assemble layers for.

    Returns:
        :class:`SystemPromptLayers` with the ordered layer list and
        total token count, or ``None`` if the session is not found.
    """
    row = await sessions_db.get(connection, session_id)
    if row is None:
        return None

    layers: list[SystemPromptLayer] = []

    # Layer 1: session_instructions
    _append_session_instructions_layer(row, layers)
    # Layer 2: baseline (always present)
    layers.append(
        SystemPromptLayer(
            kind=LAYER_KIND_BASELINE,
            body=CLOSE_SESSION_INSTRUCTION,
            token_count=_approx_tokens(CLOSE_SESSION_INSTRUCTION),
            source_path=None,
        )
    )
    # Layer 3: project CLAUDE.md walk-up chain
    if row.working_dir:
        for path, body in _walk_up_claude_md(row.working_dir):
            layers.append(
                SystemPromptLayer(
                    kind=LAYER_KIND_PROJECT_CLAUDE_MD,
                    body=body,
                    token_count=_approx_tokens(body),
                    source_path=path,
                )
            )
    # Layers 4a + 4b: per-tag CLAUDE.md fragments + tag DB memories
    ordered_tags = await tags_db.list_for_session_ordered(connection, session_id)
    await _append_tag_layers(connection, ordered_tags, layers)

    # Layer 5: template_baseline (deferred — see project TODO.md).

    total_tokens = sum(layer.token_count for layer in layers)
    return SystemPromptLayers(layers=layers, total_tokens=total_tokens)


__all__ = [
    "KNOWN_LAYER_KINDS",
    "LAYER_KIND_BASELINE",
    "LAYER_KIND_PROJECT_CLAUDE_MD",
    "LAYER_KIND_SESSION_INSTRUCTIONS",
    "LAYER_KIND_TAG_CLAUDE_MD",
    "LAYER_KIND_TAG_MEMORY",
    "LAYER_KIND_TEMPLATE_BASELINE",
    "SystemPromptLayer",
    "SystemPromptLayers",
    "assemble_system_prompt_layers",
]
