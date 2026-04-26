"""L4.3.1 — `POST /sessions/{id}/spawn_from_reply/{message_id}`.

Wave 2 lane 1 of the assistant-reply action row (TODO.md: research entry
2026-04-22). Click `＋ SPAWN` on a finished assistant reply → a brand-new
`chat`-kind Bearings session lands in the sidebar seeded with that
reply's content, inheriting the parent's tags + `working_dir`. v0
hard-codes the single-chat shape; Wave 3 (deferred) will swap in an LLM
classifier that may pick checklist / N-chat shapes instead.

Mirrors the structure of `routes_regenerate.py` but takes a different
shape:
  - source message must be the **assistant** turn (we're spawning *from
    the reply*, not regenerating a user prompt). Validate role.
  - new session is empty — no message rows copied. The reply is
    materialized as the new session's `description` (its plug), with a
    provenance line so a fresh spawn reading the description knows where
    it came from.
  - title = first ~60 chars of the reply, or `Spawn from <parent title>`
    when the reply is empty / starts blank.
  - inherits `working_dir`, `model`, and tags from the parent. Default
    severity is auto-attached when the parent had none (idempotent).

The frontend `Conversation` component opens the new session in the
conversation pane on success; the sidebar picks it up via the
`/ws/sessions` upsert broadcast or the next poll, whichever fires first.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from bearings import metrics
from bearings.agent.sessions_broker import publish_session_upsert
from bearings.api.auth import require_auth
from bearings.api.models import SessionOut
from bearings.db import store

router = APIRouter(
    prefix="/sessions",
    tags=["spawn"],
    dependencies=[Depends(require_auth)],
)


# Cap on the synthesized title. 60 chars matches the human note in the
# Bearings session-handoff discipline (the sidebar truncates beyond
# that anyway). A character-count cap rather than a word cap keeps the
# behavior predictable on emoji / CJK heavy replies — the column is
# rendered with a fixed-width font budget, not word-aware ellipsis.
_TITLE_CHAR_CAP = 60
# Sentinel used when the reply is empty / pure whitespace. Falls back
# to embedding the parent title so the new session still has something
# human-readable in the sidebar.
_TITLE_FALLBACK_PREFIX = "Spawn from "


def _synthesize_title(reply: str, parent_title: str | None) -> str:
    """Pull a sidebar-friendly title out of the assistant reply.

    Strategy: first non-blank line, with leading markdown noise
    (`# `, `## `, `> `, `- `, `* `, `1. `) stripped, trimmed, truncated
    to `_TITLE_CHAR_CAP` chars with a trailing `…` when over.

    Falls back to `Spawn from <parent title>` when nothing usable
    survives — empty reply, whitespace-only, or every line is bare
    markdown punctuation.
    """
    for raw_line in reply.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = _strip_md_prefix(line).strip()
        if not cleaned:
            continue
        if len(cleaned) > _TITLE_CHAR_CAP:
            return cleaned[: _TITLE_CHAR_CAP - 1] + "…"
        return cleaned
    parent = (parent_title or "").strip()
    if not parent:
        return _TITLE_FALLBACK_PREFIX.rstrip()
    return f"{_TITLE_FALLBACK_PREFIX}{parent}"


def _strip_md_prefix(line: str) -> str:
    """Trim common markdown line prefixes (heading hashes, blockquote
    arrows, bullet/numbered list markers). Conservative — only strips
    whitespace-followed prefixes so we don't eat content that just
    happens to begin with `#` (e.g. a hashtag-style ID)."""
    # Headings: any run of `#` followed by a space.
    stripped = line.lstrip("#")
    if stripped != line and stripped.startswith(" "):
        return stripped.lstrip()
    # Blockquote.
    if line.startswith("> "):
        return line[2:]
    # Unordered list.
    if line.startswith(("- ", "* ")):
        return line[2:]
    # Numbered list — strip up to a small digit run + `. `.
    head = line[:5]
    dot = head.find(". ")
    if dot > 0 and head[:dot].isdigit():
        return line[dot + 2 :]
    return line


def _build_description(reply: str, parent_session_id: str, message_id: str) -> str:
    """Embed the full reply as the new session's plug, plus a
    provenance footer so an agent reading the session description on a
    fresh spawn sees where this thread came from. Two newlines between
    body and footer keeps it readable in the sidebar's monospace
    rendering."""
    body = reply.rstrip()
    footer = f"— Spawned from session {parent_session_id}, message {message_id}"
    if not body:
        return footer
    return f"{body}\n\n{footer}"


@router.post(
    "/{session_id}/spawn_from_reply/{message_id}",
    response_model=SessionOut,
    status_code=201,
)
async def spawn_from_reply(
    session_id: str,
    message_id: str,
    request: Request,
) -> SessionOut:
    """Create a fresh chat session seeded with `message_id`'s reply
    content. v0 always single-chat shape (Wave 3 will classify).

    400 when the target message is not in this session, or is not an
    assistant-role turn (we don't spawn from user prompts — the
    semantics are "extract the reply").
    404 when either id is unknown.
    """
    conn = request.app.state.db
    parent = await store.get_session(conn, session_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="session not found")

    async with conn.execute(
        "SELECT id, session_id, role, content FROM messages WHERE id = ?",
        (message_id,),
    ) as cursor:
        msg_row = await cursor.fetchone()
    if msg_row is None:
        raise HTTPException(status_code=404, detail="message not found")
    if msg_row["session_id"] != session_id:
        raise HTTPException(status_code=400, detail="message does not belong to this session")
    if msg_row["role"] != "assistant":
        raise HTTPException(
            status_code=400,
            detail="spawn_from_reply requires an assistant message",
        )

    reply_content = str(msg_row["content"] or "")
    title = _synthesize_title(reply_content, parent.get("title"))
    description = _build_description(reply_content, session_id, message_id)

    new_row = await store.create_session(
        conn,
        working_dir=parent["working_dir"],
        model=parent["model"],
        title=title,
        description=description,
        # Inherit the parent's per-session budget cap. The user can
        # bump it via PATCH if the spawned thread runs hotter than
        # expected. Carrying it forward beats silently dropping a cap
        # the operator set on the parent.
        max_budget_usd=parent.get("max_budget_usd"),
        kind="chat",
    )

    # Inherit every parent tag. Severity tag rides along in this loop
    # since it's just another row in `session_tags`. `attach_tag` is
    # idempotent on duplicates and silently no-ops on a deleted tag,
    # so a parent with a malformed tag set degrades to "best effort
    # inheritance" rather than a 500.
    parent_tags = await store.list_session_tags(conn, session_id)
    for tag in parent_tags:
        await store.attach_tag(conn, new_row["id"], tag["id"])
    # Insurance: if the parent somehow has no severity (pre-0021 row,
    # or operator hand-edited the DB), backfill the default so the
    # spawned session still renders a shield in the sidebar. No-op
    # when the parent already passed one through.
    await store.ensure_default_severity(conn, new_row["id"])

    metrics.sessions_created.inc()
    await publish_session_upsert(
        getattr(request.app.state, "sessions_broker", None), conn, new_row["id"]
    )

    refreshed = await store.get_session(conn, new_row["id"])
    assert refreshed is not None  # just inserted
    return SessionOut(**refreshed)
