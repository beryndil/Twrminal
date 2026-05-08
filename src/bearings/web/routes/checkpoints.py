"""Checkpoint REST endpoints (G6).

Per ``docs/architecture-v1.md`` §1.1.5 every route group lives in its
own module; this one owns:

* ``POST /api/checkpoints`` — create a checkpoint anchored at a message.
* ``GET /api/checkpoints?session_id=...`` — list checkpoints for one session.
* ``DELETE /api/checkpoints/{checkpoint_id}`` — delete one.
* ``POST /api/checkpoints/{checkpoint_id}/fork`` — clone the source
  session + copy messages up to & including the anchor into a new
  session.

The fork endpoint is the surface :mod:`bearings.db.checkpoints` was
written to support — per
``docs/behavior/context-menus.md`` §"Checkpoint (gutter chip)" the
primary action is ``checkpoint.fork``. There is intentionally no
"restore overwrite current session" semantic in v1 — fork is the only
mutation the gutter chip exposes.

Per ``docs/behavior/chat.md`` §"Slash commands in the composer" the
``/checkpoint`` slash command resolves to ``POST /api/checkpoints``
with the most-recent assistant message as the anchor; G3's
``message.split_here`` and ``message.fork_from_here`` context-menu
actions also dispatch through here (split = create checkpoint, fork =
create + immediately fork).

Handler bodies stay thin per arch §1.1.5: parse → single domain call →
shape adapter → response. Errors surface via :class:`HTTPException`
with structured ``detail`` strings — 404 for absent rows, 409 when the
per-session checkpoint cap is exceeded, 422 from the Pydantic input
validators (auto-emitted).
"""

from __future__ import annotations

from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.config.constants import (
    DEFAULT_CHECKPOINT_LABEL_TEMPLATE,
    MAX_CHECKPOINTS_PER_SESSION,
)
from bearings.db import checkpoints as checkpoints_db
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db._id import new_id, now_iso
from bearings.db.checkpoints import Checkpoint
from bearings.web.models.checkpoints import (
    CheckpointForkResult,
    CheckpointIn,
    CheckpointOut,
)

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state`` (503 if absent)."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _to_out(checkpoint: Checkpoint) -> CheckpointOut:
    """Translate :class:`Checkpoint` to the wire shape."""
    return CheckpointOut(
        id=checkpoint.id,
        session_id=checkpoint.session_id,
        message_id=checkpoint.message_id,
        label=checkpoint.label,
        created_at=checkpoint.created_at,
    )


@router.post(
    "/api/checkpoints",
    status_code=status.HTTP_201_CREATED,
    response_model=CheckpointOut,
    operation_id="create-checkpoint",
)
async def create_checkpoint(payload: CheckpointIn, request: Request) -> CheckpointOut:
    """Create a checkpoint anchored at ``payload.message_id``.

    When ``payload.label`` is omitted the route synthesises one from
    :data:`DEFAULT_CHECKPOINT_LABEL_TEMPLATE` using the next ordinal for
    the session ("Checkpoint 1", "Checkpoint 2", …).

    404 when the session or message is absent (FK violation in the DB
    layer surfaces as ``IntegrityError``).
    409 when the per-session cap from
    :data:`MAX_CHECKPOINTS_PER_SESSION` is exceeded.
    """
    db = _db(request)
    if not await sessions_db.exists(db, payload.session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {payload.session_id!r}",
        )
    message = await messages_db.get(db, payload.message_id)
    if message is None or message.session_id != payload.session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"no message matches {payload.message_id!r} on session {payload.session_id!r}"),
        )
    existing_count = await checkpoints_db.count_for_session(db, payload.session_id)
    if existing_count >= MAX_CHECKPOINTS_PER_SESSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"session {payload.session_id!r} already has "
                f"{existing_count} checkpoints (cap {MAX_CHECKPOINTS_PER_SESSION})"
            ),
        )
    label = payload.label
    if label is None or label.strip() == "":
        label = DEFAULT_CHECKPOINT_LABEL_TEMPLATE.format(n=existing_count + 1)
    try:
        checkpoint = await checkpoints_db.create(
            db,
            session_id=payload.session_id,
            message_id=payload.message_id,
            label=label,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _to_out(checkpoint)


@router.get("/api/checkpoints", response_model=list[CheckpointOut], operation_id="list-checkpoints")
async def list_checkpoints(
    request: Request,
    session_id: str = Query(
        ...,
        min_length=1,
        description="Restrict to checkpoints for this session.",
    ),
) -> list[CheckpointOut]:
    """Every checkpoint for ``session_id``, newest-first.

    Returns ``[]`` for an unknown session (matches the zero-row case for
    a session that exists but has no checkpoints — the gutter renders
    empty either way).
    """
    db = _db(request)
    rows = await checkpoints_db.list_for_session(db, session_id)
    return [_to_out(row) for row in rows]


@router.delete(
    "/api/checkpoints/{checkpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete-checkpoint",
)
async def delete_checkpoint(checkpoint_id: str, request: Request) -> None:
    """Delete one checkpoint; 204 on success, 404 when absent."""
    db = _db(request)
    removed = await checkpoints_db.delete(db, checkpoint_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no checkpoint matches {checkpoint_id!r}",
        )


@router.post(
    "/api/checkpoints/{checkpoint_id}/fork",
    status_code=status.HTTP_201_CREATED,
    response_model=CheckpointForkResult,
    operation_id="fork-checkpoint",
)
async def fork_checkpoint(checkpoint_id: str, request: Request) -> CheckpointForkResult:
    """Fork the source session at ``checkpoint_id``.

    Clones the source session row + copies every message up to & including
    the checkpoint anchor into a new session. The new session inherits
    the source's ``working_dir`` / ``model`` / routing fields and gets
    a derivative title (``"<source.title> (fork)"``).

    Per the SDK-primitives memory: Bearings owns this branching primitive
    rather than the SDK's ``fork_session`` because Bearings stores its own
    transcript and needs DB-level cloning to keep replay deterministic.

    404 when the checkpoint or its source session has gone away.
    """
    db = _db(request)
    checkpoint = await checkpoints_db.get(db, checkpoint_id)
    if checkpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no checkpoint matches {checkpoint_id!r}",
        )
    source = await sessions_db.get(db, checkpoint.session_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"checkpoint {checkpoint_id!r} points at a missing session",
        )
    anchor_message = await messages_db.get(db, checkpoint.message_id)
    if anchor_message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"checkpoint {checkpoint_id!r} points at a missing message",
        )
    # Build a derivative title that fits within the title-max cap. The
    # cap is enforced by sessions_db.create's __post_init__; we trim
    # rather than fail so a near-cap source title still forks cleanly.
    new_title = _derive_fork_title(source.title)
    new_session = await sessions_db.create(
        db,
        kind=source.kind,
        title=new_title,
        working_dir=source.working_dir,
        model=source.model,
        description=source.description,
        session_instructions=source.session_instructions,
        permission_mode=source.permission_mode,
        max_budget_usd=source.max_budget_usd,
        routing_advisor_model=source.routing_advisor_model,
        routing_advisor_max_uses=source.routing_advisor_max_uses,
        routing_effort_level=source.routing_effort_level,
    )
    copied = await _copy_messages_up_to_anchor(
        db,
        source_session_id=source.id,
        target_session_id=new_session.id,
        anchor_seq=anchor_message.seq,
    )
    return CheckpointForkResult(
        new_session_id=new_session.id,
        source_session_id=source.id,
        checkpoint_id=checkpoint_id,
        message_count=copied,
    )


def _derive_fork_title(source_title: str) -> str:
    """Append ``" (fork)"`` to ``source_title``, trimming if it would overflow."""
    suffix = " (fork)"
    from bearings.config.constants import SESSION_TITLE_MAX_LENGTH

    if len(source_title) + len(suffix) <= SESSION_TITLE_MAX_LENGTH:
        return source_title + suffix
    # Trim the source so the suffix fits within the cap.
    keep = SESSION_TITLE_MAX_LENGTH - len(suffix)
    return source_title[:keep] + suffix


async def _copy_messages_up_to_anchor(
    connection: aiosqlite.Connection,
    *,
    source_session_id: str,
    target_session_id: str,
    anchor_seq: int,
) -> int:
    """Copy messages with ``rowid <= anchor_seq`` from source → target.

    Returns the number of rows inserted. Uses a single ``INSERT INTO …
    SELECT …`` so the bulk copy is one round-trip; new ids are minted
    per-row so the target session has its own immutable identifiers.
    The ``message_count`` on ``sessions(target_session_id)`` is bumped
    once at the end to match.
    """
    # SQLite's row generator can't mint app-prefix ids in-SQL, so we
    # iterate the rows and INSERT one at a time. The set is bounded by
    # the source session's transcript length up to the checkpoint anchor;
    # for typical sessions (≤ 100 turns) this is an O(N) loop with no
    # noticeable latency.
    cursor = await connection.execute(
        "SELECT id, role, content, created_at, executor_model, advisor_model, "
        "effort_level, routing_source, routing_reason, matched_rule_id, "
        "executor_input_tokens, executor_output_tokens, advisor_input_tokens, "
        "advisor_output_tokens, advisor_calls_count, cache_read_tokens, "
        "input_tokens, output_tokens, pinned, hidden_from_context "
        "FROM messages WHERE session_id = ? AND rowid <= ? "
        "ORDER BY rowid ASC",
        (source_session_id, anchor_seq),
    )
    try:
        rows = list(await cursor.fetchall())
    finally:
        await cursor.close()
    if not rows:
        return 0
    timestamp = now_iso()
    for row in rows:
        await connection.execute(
            "INSERT INTO messages ("
            "id, session_id, role, content, created_at, "
            "executor_model, advisor_model, effort_level, "
            "routing_source, routing_reason, matched_rule_id, "
            "executor_input_tokens, executor_output_tokens, "
            "advisor_input_tokens, advisor_output_tokens, "
            "advisor_calls_count, cache_read_tokens, "
            "input_tokens, output_tokens, pinned, hidden_from_context"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("msg"),
                target_session_id,
                str(row[1]),  # role
                str(row[2]),  # content
                str(row[3]),  # created_at — preserve original ts so order matches
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
                row[13],
                row[14],
                row[15],
                row[16],
                row[17],
                row[18],
                row[19],
            ),
        )
    await connection.execute(
        "UPDATE sessions SET message_count = message_count + ?, updated_at = ? WHERE id = ?",
        (len(rows), timestamp, target_session_id),
    )
    await connection.commit()
    return len(rows)


__all__ = ["router"]
