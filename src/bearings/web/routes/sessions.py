"""Session routes — prompt endpoint + session row CRUD.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/sessions.py``
owns:

* ``GET    /api/sessions``                — list sessions (filtered).
* ``POST   /api/sessions``                — create a session (v1.1
                                            closing-sweep — previously
                                            deferred, never landed in
                                            v1.0).
* ``GET    /api/sessions/{id}``           — fetch one session row.
* ``PATCH  /api/sessions/{id}``           — title-only edit (item 1.7
                                            scope; description PATCH
                                            lands with item 2.x).
* ``PATCH  /api/sessions/{id}/model``     — swap the executor model
                                            (spec §7; v1.1 closing-
                                            sweep). DB-only today;
                                            live-runner forward
                                            deferred per TODO.md.
* ``DELETE /api/sessions/{id}``           — delete session (cascades).
* ``POST   /api/sessions/{id}/close``     — close (sets ``closed_at``).
* ``POST   /api/sessions/{id}/reopen``    — clear ``closed_at``.
* ``POST   /api/sessions/{id}/regenerate`` — replay the latest user
                                            prompt (v1.1 closing-
                                            sweep).
* ``POST   /api/sessions/{id}/viewed``    — stamp ``last_viewed_at``
                                            to now; broadcast upsert
                                            clears the unviewed-dot
                                            on other tabs.
* ``GET    /api/sessions/{id}/export``     — full JSON snapshot
                                            (session + messages + tool_calls
                                            + checkpoints + attachments)
                                            per ``docs/behavior/sessions.md``.
* ``POST   /api/sessions/import``         — restore a session from an
                                            export blob; 409 when the
                                            session_id already exists
                                            (use ``?force=true`` to
                                            overwrite).
* ``POST   /api/sessions/{id}/prompt``    — the prompt endpoint per
                                            ``docs/behavior/prompt-endpoint.md``.

Handler bodies are thin per arch §1.1.5: argument parsing, single
domain call, response formatting. Errors map :class:`PromptDispatchOutcome`
+ :class:`HTTPException` per behavior doc §"Failure responses".
"""

from __future__ import annotations

import json
from typing import Annotated, cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from bearings.agent.prompt_dispatch import (
    PromptDispatchOutcome,
    RateLimiter,
    dispatch_prompt,
)
from bearings.agent.runner import RunnerFactory
from bearings.config.constants import (
    KNOWN_SESSION_KINDS,
    PROMPT_ACK_QUEUED_KEY,
    PROMPT_ACK_SESSION_ID_KEY,
    TAG_CLASS_PROJECT,
    TAG_CLASS_SEVERITY,
)
from bearings.db import checkpoints as checkpoints_db
from bearings.db import messages as messages_db
from bearings.db import sdk_entries as sdk_entries_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db.sessions import Session
from bearings.web.models.sessions import (
    CheckpointExport,
    MessageExport,
    PairedChatInfo,
    PromptIn,
    SessionCreate,
    SessionExport,
    SessionModelUpdate,
    SessionOut,
    SessionPermissionModeUpdate,
    SessionPinnedUpdate,
    SessionTitleUpdate,
)
from bearings.web.routes.ws_sessions import SessionsBroadcaster
from bearings.web.runner_factory import InProcessRunnerRegistry

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _runner_factory(request: Request) -> RunnerFactory:
    """Pull the runner factory off ``app.state``.

    Per arch §3.2 the runner factory is injected at app construction
    so the agent layer never imports ``bearings.web``. The route layer
    reads it back through ``app.state`` here.
    """
    factory = getattr(request.app.state, "runner_factory", None)
    if factory is None:  # pragma: no cover — set by create_app
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runner_factory not configured on app.state",
        )
    return cast(RunnerFactory, factory)


def _rate_limiter(request: Request) -> RateLimiter:
    """Pull the per-app :class:`RateLimiter` off ``app.state``."""
    limiter = getattr(request.app.state, "prompt_rate_limiter", None)
    if limiter is None:  # pragma: no cover — set by create_app
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="prompt_rate_limiter not configured on app.state",
        )
    if not isinstance(limiter, RateLimiter):  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="prompt_rate_limiter on app.state is not a RateLimiter",
        )
    return limiter


def _sessions_broadcaster(request: Request) -> SessionsBroadcaster | None:
    """Pull the optional sessions broadcaster off ``app.state``.

    Returns ``None`` when no broadcaster is wired (test-only paths
    that construct a minimal app without a DB); callers guard on
    ``if broadcaster is not None`` before publishing.
    """
    return cast(
        SessionsBroadcaster | None,
        getattr(request.app.state, "sessions_broadcaster", None),
    )


async def _validate_tag_cardinality(
    db: aiosqlite.Connection,
    tag_ids: tuple[int, ...],
) -> None:
    """Reject tag-id sets that violate the ≤1 project / ≤1 severity rule.

    Cardinality is enforced at the API boundary (not the schema) so a
    half-built create transaction can roll back cleanly. The bulk-replace
    path (``POST /api/sessions``, ``set_for_session``) calls this before
    persisting; single-attach via ``PUT /api/sessions/{sid}/tags/{tid}``
    intentionally does NOT validate, so the user can transiently land in
    a 2-project state via incremental edits — the next bulk replace will
    reject. (See plan §"Migration & risk notes".)

    Raises :class:`HTTPException` 422 with a structured detail listing
    the violating ids per class. Empty ``tag_ids`` is valid.
    """
    if not tag_ids:
        return
    # Resolve class for each id in one round-trip. Existing-id validation
    # happens upstream in :func:`create_session`; if any id is missing
    # here the count below simply ignores it (the missing-id 404 fires
    # before we reach this function).
    placeholders = ",".join("?" * len(tag_ids))
    cursor = await db.execute(
        f"SELECT id, class FROM tags WHERE id IN ({placeholders})",
        tag_ids,
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    by_class: dict[str, list[int]] = {}
    for row in rows:
        by_class.setdefault(str(row[1]), []).append(int(str(row[0])))
    project_ids = by_class.get(TAG_CLASS_PROJECT, [])
    severity_ids = by_class.get(TAG_CLASS_SEVERITY, [])
    violations: list[str] = []
    if len(project_ids) > 1:
        violations.append(f"≤1 project tag allowed (got {sorted(project_ids)})")
    if len(severity_ids) > 1:
        violations.append(f"≤1 severity tag allowed (got {sorted(severity_ids)})")
    if violations:
        # f-string keeps the detail value AST-detectable as string-typed
        # for the consistency_lint error-shape rule (which rejects bare
        # ``str.join`` calls — only ``str(...)``, literals, f-strings,
        # and string-typed ternaries are accepted).
        message = "; ".join(violations)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{message}",
        )


def _to_out(session: Session, paired_parent_title: str | None = None) -> SessionOut:
    """Wire shape for a session row."""
    return SessionOut(
        id=session.id,
        kind=session.kind,
        title=session.title,
        description=session.description,
        session_instructions=session.session_instructions,
        working_dir=session.working_dir,
        model=session.model,
        permission_mode=session.permission_mode,
        max_budget_usd=session.max_budget_usd,
        total_cost_usd=session.total_cost_usd,
        message_count=session.message_count,
        last_context_pct=session.last_context_pct,
        last_context_tokens=session.last_context_tokens,
        last_context_max=session.last_context_max,
        pinned=session.pinned,
        error_pending=session.error_pending,
        checklist_item_id=session.checklist_item_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_viewed_at=session.last_viewed_at,
        last_completed_at=session.last_completed_at,
        closed_at=session.closed_at,
        closing_summary=session.closing_summary,
        paired_parent_title=paired_parent_title,
    )


# ---- list / fetch -----------------------------------------------------------


@router.get("/api/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    kind: str | None = None,
    include_closed: bool = True,
    tag_ids: Annotated[list[int] | None, Query()] = None,
    tag_ids_project: Annotated[list[int] | None, Query()] = None,
    tag_ids_severity: Annotated[list[int] | None, Query()] = None,
    tag_ids_other: Annotated[list[int] | None, Query()] = None,
) -> list[SessionOut]:
    """List sessions filtered by ``kind`` + ``include_closed`` + tag filters.

    Two filter shapes coexist:

    * ``tag_ids`` — legacy flat OR (back-compat). Returns sessions
      attached to **at least one** of the listed tags regardless of
      class. Repeat the parameter for multi-select.
    * ``tag_ids_project`` / ``tag_ids_severity`` / ``tag_ids_other`` —
      three-section faceted filter from the tag-class feature. OR
      within each class; AND across classes. An omitted (or empty)
      section means "no constraint from this class," NOT "exclude
      everything" — the empty-section state lets the filter panel
      render an empty section without blanking out results.

    All four can be combined; each is an additional AND constraint at
    the SQL layer (legacy ``tag_ids`` joins; per-class params use
    correlated EXISTS subqueries). A frontend that only uses the new
    surface should leave ``tag_ids`` empty.
    """
    db = _db(request)
    if kind is not None and kind not in KNOWN_SESSION_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind {kind!r} not in {sorted(KNOWN_SESSION_KINDS)}",
        )
    # Normalize the empty-list-from-query edge cases. FastAPI hands
    # ``[]`` if the client sends no values; the DB layer's contract is
    # ``None`` for no filter, non-empty tuple otherwise — translate
    # accordingly.
    tag_filter = tuple(tag_ids) if tag_ids else None
    project_filter = tuple(tag_ids_project) if tag_ids_project else None
    severity_filter = tuple(tag_ids_severity) if tag_ids_severity else None
    other_filter = tuple(tag_ids_other) if tag_ids_other else None
    rows = await sessions_db.list_all(
        db,
        kind=kind,
        include_closed=include_closed,
        tag_ids=tag_filter,
        tag_ids_project=project_filter,
        tag_ids_severity=severity_filter,
        tag_ids_other=other_filter,
    )
    # Fetch paired-chat parent titles for chat rows (sidebar annotation).
    # Build a map of session_id → parent_title for efficient lookup.
    paired_info_map: dict[str, str | None] = {}
    for row in rows:
        if row.kind == "chat" and row.checklist_item_id is not None:
            info = await sessions_db.get_paired_chat_info(db, row.id)
            paired_info_map[row.id] = info[0] if info else None

    return [_to_out(row, paired_parent_title=paired_info_map.get(row.id)) for row in rows]


@router.post(
    "/api/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: SessionCreate,
    request: Request,
    response: Response,
) -> SessionOut:
    """Create a session row + attach tags atomically.

    Per arch §1.1.5 the v1 session-create surface — the closing-sweep
    audit (2026-05-02) found this endpoint missing despite the master
    checklist marking the item DONE.

    Validation precedence:

    * ``kind`` must be in :data:`KNOWN_SESSION_KINDS` → 422 otherwise.
    * Every id in ``tag_ids`` must reference an existing tag row → 404
      with the missing list otherwise. Tag existence is checked BEFORE
      :func:`sessions_db.create` so a bad tag id never leaves an
      orphaned session.
    * ``working_dir`` is required. If omitted, the first tag (in order)
      with a non-null ``working_dir`` is used. Returns 422 if both the
      payload field is None/omitted and no tag provides a directory.
    * Deeper field invariants (model name format, permission-mode enum,
      title bounds beyond Pydantic's) raise ``ValueError`` from
      :class:`Session.__post_init__` and surface as 422.

    Returns 201 with ``Location: /api/sessions/<id>``.
    """
    db = _db(request)
    if payload.kind not in KNOWN_SESSION_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind {payload.kind!r} not in {sorted(KNOWN_SESSION_KINDS)}",
        )
    tag_ids = tuple(payload.tag_ids)
    if tag_ids:
        existing_ids = {tag.id for tag in await tags_db.list_all(db)}
        missing = sorted({tid for tid in tag_ids if tid not in existing_ids})
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"unknown tag_ids: {missing}",
            )
        # ≤1 project / ≤1 severity per session — see
        # ``_validate_tag_cardinality`` for the rationale and the
        # single-attach exemption.
        await _validate_tag_cardinality(db, tag_ids)
    # Resolve working_dir: explicit > first tag with a working_dir set > error
    resolved_working_dir = payload.working_dir
    if resolved_working_dir is None and tag_ids:
        tag_list = await tags_db.list_all(db)
        tag_map = {tag.id: tag for tag in tag_list}
        for tid in tag_ids:
            tag = tag_map.get(tid)
            if tag is not None and tag.working_dir is not None:
                resolved_working_dir = tag.working_dir
                break
    if resolved_working_dir is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="working_dir is required — supply it explicitly or attach a tag with "
            "a working_dir set",
        )
    try:
        row = await sessions_db.create(
            db,
            kind=payload.kind,
            title=payload.title,
            working_dir=resolved_working_dir,
            model=payload.model,
            description=payload.description,
            session_instructions=payload.session_instructions,
            permission_mode=payload.permission_mode,
            max_budget_usd=payload.max_budget_usd,
            routing_advisor_model=payload.routing_advisor_model,
            routing_advisor_max_uses=payload.routing_advisor_max_uses,
            routing_effort_level=payload.routing_effort_level,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if tag_ids:
        await tags_db.set_for_session(db, session_id=row.id, tag_ids=tag_ids)
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    response.headers["Location"] = f"/api/sessions/{row.id}"
    return out


@router.get("/api/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, request: Request) -> SessionOut:
    """Fetch one session by id; 404 if absent."""
    db = _db(request)
    row = await sessions_db.get(db, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    # Fetch paired-chat parent title if this is a paired chat.
    paired_parent_title: str | None = None
    if row.kind == "chat" and row.checklist_item_id is not None:
        info = await sessions_db.get_paired_chat_info(db, session_id)
        paired_parent_title = info[0] if info else None
    return _to_out(row, paired_parent_title=paired_parent_title)


@router.patch("/api/sessions/{session_id}", response_model=SessionOut)
async def patch_session(
    session_id: str,
    payload: SessionTitleUpdate,
    request: Request,
) -> SessionOut:
    """Title-only PATCH for v0.18.0; description editor lands later."""
    db = _db(request)
    try:
        row = await sessions_db.update_title(db, session_id, title=payload.title)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.delete(
    "/api/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(session_id: str, request: Request) -> None:
    """Cascade-delete a session row + messages + checkpoints."""
    db = _db(request)
    removed = await sessions_db.delete(db, session_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_delete(session_id)


@router.post("/api/sessions/{session_id}/close", response_model=SessionOut)
async def close_session(session_id: str, request: Request) -> SessionOut:
    """Stamp ``closed_at`` so the prompt-endpoint returns 409 on next POST."""
    db = _db(request)
    row = await sessions_db.close(db, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.patch("/api/sessions/{session_id}/model", response_model=SessionOut)
async def patch_session_model(
    session_id: str,
    payload: SessionModelUpdate,
    request: Request,
) -> SessionOut:
    """Swap the session's executor model (spec §7; arch §1.1.5).

    Persists the new model name on the session row, then recycles the
    live SDK supervisor for that session via
    :meth:`InProcessRunnerRegistry.recycle`. The Claude CLI bakes
    ``--model`` in at process spawn — there is no in-band control
    message to swap models on a running subprocess — so the live
    forward reduces to "tear the subprocess down and let the next
    prompt respawn it." The ring buffer survives the recycle (the
    runner stays in ``_runners``), so the prior turn's deltas remain
    available for replay; only the SDK worker bound to the old model
    is torn down. The next prompt arriving at this session triggers
    the registry's reap-recovery branch, which re-spawns
    ``run_session_loop`` with a freshly-bootstrapped
    :class:`AgentSession` reading the just-updated ``model`` column.

    422 on unknown model names; the validator delegates to
    :func:`sessions_db._is_known_model_name` so the alphabet stays in
    one place.
    """
    db = _db(request)
    try:
        row = await sessions_db.update_model(db, session_id, model=payload.model)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    # Live-runner forward: tear down the supervisor so the next prompt
    # respawns the SDK subprocess with ``--model <new>``. Narrow to
    # the in-process registry concretely (mirrors ``stop_session_turn``
    # at the same module) — the ``RunnerFactory`` Protocol intentionally
    # exposes only ``__call__``; lifecycle controls are concrete-only.
    factory = getattr(request.app.state, "runner_factory", None)
    if isinstance(factory, InProcessRunnerRegistry):
        await factory.recycle(session_id)
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.patch("/api/sessions/{session_id}/permission_mode", response_model=SessionOut)
async def patch_session_permission_mode(
    session_id: str,
    payload: SessionPermissionModeUpdate,
    request: Request,
) -> SessionOut:
    """Swap the session's permission mode mid-session (item 3.3).

    DB-only today: persists the new mode on the session row so the
    runner picks it up on the next turn. ``None`` clears the column,
    letting the runner fall back to the profile default.

    422 on unknown mode strings (validated against
    :data:`KNOWN_SDK_PERMISSION_MODES`); 404 when the session is absent.
    """
    db = _db(request)
    try:
        row = await sessions_db.update_permission_mode(
            db, session_id, permission_mode=payload.permission_mode
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.patch("/api/sessions/{session_id}/pinned", response_model=SessionOut)
async def patch_session_pinned(
    session_id: str,
    payload: SessionPinnedUpdate,
    request: Request,
) -> SessionOut:
    """Pin or unpin a session row via ``PATCH /api/sessions/{id}/pinned``.

    ``{pinned: true}`` pins the row; ``{pinned: false}`` unpins it.
    Idempotent — setting the same value twice is a no-op. Returns the
    updated session row. 404 when the session is absent.
    """
    db = _db(request)
    row = await sessions_db.update_pinned(db, session_id, pinned=payload.pinned)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.post("/api/sessions/{session_id}/reopen", response_model=SessionOut)
async def reopen_session(session_id: str, request: Request) -> SessionOut:
    """Clear ``closed_at`` per behavior doc §"Reopen semantics"."""
    db = _db(request)
    row = await sessions_db.reopen(db, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.post("/api/sessions/{session_id}/viewed", response_model=SessionOut)
async def update_session_viewed(session_id: str, request: Request) -> SessionOut:
    """Stamp ``last_viewed_at`` to now; broadcast the upsert.

    Called by the frontend whenever the user selects a sidebar row or
    refocuses the browser tab while a row is already selected. The
    broadcast clears the unviewed amber dot on every other open tab /
    window within a single WebSocket tick.

    - ``404`` — session not found.
    - ``200`` — updated session row with a fresh ``last_viewed_at``.
    """
    db = _db(request)
    row = await sessions_db.mark_viewed(db, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.post("/api/sessions/{session_id}/recover", response_model=SessionOut)
async def resume_session(session_id: str, request: Request) -> SessionOut:
    """User-driven recovery from ERROR state.

    Clears the ``error_pending`` flag in the DB and triggers a runner
    respawn so the next user prompt can proceed. Per
    ``docs/behavior/chat.md`` §"Error states" and ``TODO.md`` §"POST
    /api/sessions/{id}/recover HTTP route".

    - ``404`` — session not found.
    - ``200`` — session row returned with ``error_pending=False``; the
      runner respawn is a side-effect (transparent to the caller).
    """
    db = _db(request)
    row = await sessions_db.set_error_pending(db, session_id, False)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    # Trigger reap-recovery: if the supervisor task is gone the next
    # __call__ will respawn it, making the session ready for the next
    # prompt without the user sending a message first.
    factory = getattr(request.app.state, "runner_factory", None)
    if isinstance(factory, InProcessRunnerRegistry):
        await factory(session_id)
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    return out


@router.get("/api/sessions/{session_id}/paired-chat-info")
async def get_paired_chat_info_route(session_id: str, request: Request) -> PairedChatInfo | None:
    """Fetch paired-chat metadata for a chat session.

    Per ``docs/behavior/paired-chats.md`` §"From the chat side" — when a
    chat session is paired to a checklist item, the breadcrumb shows
    ``<parent checklist title> > <item label>``. This endpoint returns
    those two fields when a pairing exists, or ``None`` when the chat is
    unpaired.

    Returns 200 with ``{parent_title, item_label}`` when paired, or
    200 with ``null`` when unpaired or the session is absent. (Returning
    200 for both cases avoids the cognitive overhead of decoding a 404
    as "not paired" vs "session missing" — the UI reads the None value
    and hides the breadcrumb.)
    """
    db = _db(request)
    info = await sessions_db.get_paired_chat_info(db, session_id)
    if info is None:
        return None
    parent_title, item_label = info
    return PairedChatInfo(parent_title=parent_title, item_label=item_label)


# ---- export / import -------------------------------------------------------


def _slugify(title: str) -> str:
    """Convert a session title to a safe ASCII filename stem.

    Collapses non-alphanumeric runs to ``-``, strips leading/trailing
    dashes, lowercases. An empty result (title contained only special
    chars) falls back to ``session``.
    """
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "session"


@router.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, request: Request) -> Response:
    """Snapshot-export a session to a self-contained JSON blob.

    Per ``docs/behavior/sessions.md`` §"Export contract":

    * ``200`` — JSON body conforming to :class:`SessionExport`; the
      ``Content-Disposition`` header carries a suggested download
      filename ``<slug>.json`` derived from the session title.
    * ``404`` — session not found.

    Closed sessions are exportable — ``closed_at`` being set does not
    block this endpoint (contrast with the prompt endpoint which returns
    409 on closed sessions).

    The export body contains:

    * ``session`` — session row (``SessionOut`` shape).
    * ``messages`` — every message in chronological order.
    * ``tool_calls`` — raw SDK transcript entries (opaque blobs).
    * ``checkpoints`` — every checkpoint chronologically.
    * ``attachments`` — always ``[]`` in v0.18.x (no per-session upload
      linking table yet).
    """
    db = _db(request)
    row = await sessions_db.get(db, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    # Fetch paired-chat parent title for the session row header.
    paired_parent_title: str | None = None
    if row.kind == "chat" and row.checklist_item_id is not None:
        info = await sessions_db.get_paired_chat_info(db, session_id)
        paired_parent_title = info[0] if info else None

    messages = await messages_db.list_for_session(db, session_id)
    tool_calls = await sdk_entries_db.load(db, session_id=session_id)
    checkpoints = await checkpoints_db.list_for_session(db, session_id)

    export = SessionExport(
        session=_to_out(row, paired_parent_title=paired_parent_title),
        messages=[
            MessageExport(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                executor_model=m.executor_model,
                advisor_model=m.advisor_model,
                effort_level=m.effort_level,
                routing_source=m.routing_source,
                routing_reason=m.routing_reason,
                matched_rule_id=m.matched_rule_id,
                executor_input_tokens=m.executor_input_tokens,
                executor_output_tokens=m.executor_output_tokens,
                advisor_input_tokens=m.advisor_input_tokens,
                advisor_output_tokens=m.advisor_output_tokens,
                advisor_calls_count=m.advisor_calls_count,
                cache_read_tokens=m.cache_read_tokens,
                input_tokens=m.input_tokens,
                output_tokens=m.output_tokens,
                seq=m.seq,
                pinned=m.pinned,
                hidden_from_context=m.hidden_from_context,
            )
            for m in messages
        ],
        tool_calls=tool_calls,
        checkpoints=[
            CheckpointExport(
                id=c.id,
                session_id=c.session_id,
                message_id=c.message_id,
                label=c.label,
                created_at=c.created_at,
            )
            for c in checkpoints
        ],
        attachments=[],
    )
    slug = _slugify(row.title)
    body = json.dumps(export.model_dump(), ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{slug}.json"'},
    )


@router.post(
    "/api/sessions/import",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_session(
    body: SessionExport,
    request: Request,
    response: Response,
    force: bool = False,
) -> SessionOut:
    """Restore a session from an export blob.

    Per ``docs/behavior/sessions.md`` §"Import contract":

    * ``201`` — session row (plus messages, tool_calls, checkpoints)
      inserted; ``Location`` header points at the new row.
    * ``409`` — ``session_id`` already exists AND ``force=false``.
      Pass ``?force=true`` to delete the existing row first and
      reimport.
    * ``422`` — body does not parse as ``SessionExport`` or a field
      fails DB-layer validation (e.g. unknown model name, bad kind).

    ``checklist_item_id`` is cleared on import — the FK target
    (``checklist_items``) does not exist in the destination instance.
    Routing-decision columns default to ``auto/5/null`` because
    ``SessionOut`` does not carry them.
    """
    db = _db(request)
    session_id = body.session.id
    if await sessions_db.exists(db, session_id):
        if not force:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"session {session_id!r} already exists; pass ?force=true to overwrite"),
            )
        await sessions_db.delete(db, session_id)
        broadcaster = _sessions_broadcaster(request)
        if broadcaster is not None:
            broadcaster.publish_delete(session_id)
    s = body.session
    try:
        row = await sessions_db.import_session(
            db,
            session_id=s.id,
            kind=s.kind,
            title=s.title,
            description=s.description,
            session_instructions=s.session_instructions,
            working_dir=s.working_dir,
            model=s.model,
            permission_mode=s.permission_mode,
            max_budget_usd=s.max_budget_usd,
            total_cost_usd=s.total_cost_usd,
            message_count=len(body.messages),
            last_context_pct=s.last_context_pct,
            last_context_tokens=s.last_context_tokens,
            last_context_max=s.last_context_max,
            pinned=s.pinned,
            closed_at=s.closed_at,
            closing_summary=s.closing_summary,
            created_at=s.created_at,
            updated_at=s.updated_at,
            last_viewed_at=s.last_viewed_at,
            last_completed_at=s.last_completed_at,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if body.messages:
        try:
            await messages_db.import_messages(db, messages=[m.model_dump() for m in body.messages])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
    for cp in body.checkpoints:
        try:
            await checkpoints_db.import_checkpoint(
                db,
                checkpoint_id=cp.id,
                session_id=cp.session_id,
                message_id=cp.message_id,
                label=cp.label,
                created_at=cp.created_at,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
    if body.tool_calls:
        await sdk_entries_db.append(db, session_id=session_id, entries=body.tool_calls)
    out = _to_out(row)
    broadcaster = _sessions_broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_upsert(out)
    response.headers["Location"] = f"/api/sessions/{session_id}"
    return out


# ---- regenerate ------------------------------------------------------------


@router.post(
    "/api/sessions/{session_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_session(session_id: str, request: Request) -> Response:
    """Re-enqueue the latest user prompt for ``session_id``.

    Per arch §1.1.5 the v1 regenerate surface — landed in the v1.1
    closing-sweep. Semantics: the latest user-role message is replayed
    through :func:`dispatch_prompt`, which queues it behind any
    in-flight turn. The previous assistant turn is left in the
    transcript; "regenerate" produces a new assistant turn alongside
    rather than replacing the old one.

    Failure modes mirror the prompt endpoint:

    * 404 — session missing OR session has no user messages yet to
      regenerate from.
    * 409 — session closed (the prompt queue rejects).
    * 429 — rate limit (per-session window enforced by the same
      limiter the prompt endpoint uses).

    Returns 202 with a JSON envelope echoing the queued state, mirror
    of the prompt endpoint's ack shape.
    """
    db = _db(request)
    factory = _runner_factory(request)
    limiter = _rate_limiter(request)
    if not await sessions_db.exists(db, session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    content = await messages_db.latest_user_content(db, session_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id!r} has no user messages to regenerate from",
        )
    result = await dispatch_prompt(
        db,
        factory,
        limiter,
        session_id=session_id,
        content=content,
    )
    outcome = result.outcome
    if outcome is PromptDispatchOutcome.QUEUED:
        body = {
            PROMPT_ACK_QUEUED_KEY: True,
            PROMPT_ACK_SESSION_ID_KEY: session_id,
        }
        return Response(
            content=json.dumps(body),
            status_code=status.HTTP_202_ACCEPTED,
            media_type="application/json",
            headers={"Location": f"/api/sessions/{session_id}"},
        )
    if outcome is PromptDispatchOutcome.NOT_FOUND:  # pragma: no cover — guarded above
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.detail or f"no session matches {session_id!r}",
        )
    if outcome is PromptDispatchOutcome.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.detail or "session is closed",
        )
    if outcome is PromptDispatchOutcome.RATE_LIMITED:
        retry_after = result.retry_after_s or 1
        return Response(
            content=json.dumps({"detail": result.detail or "rate limit exceeded"}),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            media_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )
    raise HTTPException(  # pragma: no cover — exhaustive enum match above
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"unhandled regenerate dispatch outcome {outcome.value!r}",
    )


# ---- stop / cancel turn ----------------------------------------------------


@router.post(
    "/api/sessions/{session_id}/stop",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def stop_session_turn(session_id: str, request: Request) -> None:
    """Ask the runner to interrupt the current in-flight turn.

    Calls :meth:`SessionRunner.request_stop`, which sets the runner's
    stop event. The SDK loop's watcher coroutine detects the edge and
    forwards an interrupt to :meth:`AgentSession.interrupt` →
    :meth:`ClaudeSDKClient.interrupt`.

    Idempotent: returns 204 even when no turn is running (the stop
    signal will be picked up at the start of the next turn and cleared
    immediately, or ignored if the queue is empty).

    Failure modes:

    * ``404`` — no session row found (prevents spurious stop on a
      typo'd session id that has never existed).
    * ``503`` — the runner registry is not wired (misconfigured app).
    """
    db = _db(request)
    if not await sessions_db.exists(db, session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    factory = getattr(request.app.state, "runner_factory", None)
    if not isinstance(factory, InProcessRunnerRegistry):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stop requires the in-process runner registry",
        )
    runner = factory.get(session_id)
    if runner is not None:
        runner.request_stop()
    # Runner absent means the session has no live worker (idle-reaped or
    # never materialised) — no-op; the turn is not running.


# ---- prompt endpoint -------------------------------------------------------


@router.post(
    "/api/sessions/{session_id}/prompt",
    status_code=status.HTTP_202_ACCEPTED,
)
async def prompt_session(
    session_id: str,
    payload: PromptIn,
    request: Request,
) -> Response:
    """Inject a user-role prompt into a session's queue.

    Per ``docs/behavior/prompt-endpoint.md`` §"202 semantics" the
    success response is 202 Accepted with ``Location:
    /api/sessions/<id>``, body ``{queued: true, session_id: <id>}``.
    Failure modes per §"Failure responses": 400 (empty content / bad
    kind), 404 (session missing), 409 (closed), 422 (Pydantic
    validation), 429 (rate limit).

    The 422 path is handled by FastAPI / Pydantic *before* this body
    runs (a non-string ``content`` or missing key surfaces as 422
    automatically). The 400 + 404 + 409 + 429 paths are mapped from
    :class:`PromptDispatchOutcome` below.
    """
    db = _db(request)
    factory = _runner_factory(request)
    limiter = _rate_limiter(request)
    result = await dispatch_prompt(
        db,
        factory,
        limiter,
        session_id=session_id,
        content=payload.content,
        force_advisor=payload.force_advisor,
    )
    outcome = result.outcome
    if outcome is PromptDispatchOutcome.QUEUED:
        body = {
            PROMPT_ACK_QUEUED_KEY: True,
            PROMPT_ACK_SESSION_ID_KEY: session_id,
        }
        return Response(
            content=json.dumps(body),
            status_code=status.HTTP_202_ACCEPTED,
            media_type="application/json",
            headers={"Location": f"/api/sessions/{session_id}"},
        )
    if outcome is PromptDispatchOutcome.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.detail or f"no session matches {session_id!r}",
        )
    if outcome is PromptDispatchOutcome.BAD_KIND:  # pragma: no cover — schema CHECK
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.detail or "session kind does not support prompts",
        )
    if outcome is PromptDispatchOutcome.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.detail or "session is closed",
        )
    if outcome is PromptDispatchOutcome.EMPTY_CONTENT:
        # Per behavior doc — 400 (not 422) for "content is the empty
        # string after stripping whitespace".
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.detail or "content is empty",
        )
    if outcome is PromptDispatchOutcome.CONTENT_TOO_LARGE:  # pragma: no cover — Pydantic guards
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=result.detail or "content too large",
        )
    if outcome is PromptDispatchOutcome.RATE_LIMITED:
        retry_after = result.retry_after_s or 1
        return Response(
            content=json.dumps({"detail": result.detail or "rate limit exceeded"}),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            media_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )
    raise HTTPException(  # pragma: no cover — exhaustive enum match above
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"unhandled dispatch outcome {outcome.value!r}",
    )


__all__ = ["router"]
