"""Session routes — prompt endpoint + session row CRUD.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/sessions.py``
owns:

* ``GET    /api/sessions``                — list sessions (filtered).
* ``GET    /api/sessions/{id}``           — fetch one session row.
* ``PATCH  /api/sessions/{id}``           — title-only edit (item 1.7
                                            scope; description PATCH
                                            lands with item 2.x).
* ``DELETE /api/sessions/{id}``           — delete session (cascades).
* ``POST   /api/sessions/{id}/close``     — close (sets ``closed_at``).
* ``POST   /api/sessions/{id}/reopen``    — clear ``closed_at``.
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
)
from bearings.db import sessions as sessions_db
from bearings.db.sessions import Session
from bearings.web.models.sessions import (
    PromptIn,
    SessionOut,
    SessionTitleUpdate,
)

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


def _to_out(session: Session) -> SessionOut:
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
    )


# ---- list / fetch -----------------------------------------------------------


@router.get("/api/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    kind: str | None = None,
    include_closed: bool = True,
    tag_ids: Annotated[list[int] | None, Query()] = None,
) -> list[SessionOut]:
    """List sessions filtered by ``kind`` + ``include_closed`` + ``tag_ids``.

    ``tag_ids`` is the sidebar tag-filter query surface from
    ``docs/behavior/chat.md`` § "When the user creates a chat" + the
    item 2.2 done-when criterion ("OR semantics across tags"). Repeat
    the parameter for multi-select filtering — ``?tag_ids=1&tag_ids=2``
    returns sessions attached to tag 1 OR tag 2 (the standard FastAPI
    list-query convention; a comma-list would have required custom
    parsing for no expressivity gain). Omitting the parameter applies
    no tag filter.
    """
    db = _db(request)
    if kind is not None and kind not in KNOWN_SESSION_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind {kind!r} not in {sorted(KNOWN_SESSION_KINDS)}",
        )
    # Normalize the empty-list-from-query edge case (FastAPI hands
    # ``[]`` if the client sends no ``tag_ids``; treat that the same as
    # "no filter" so the DB layer's contract — ``None`` for no filter,
    # non-empty tuple for OR — is honoured.
    tag_filter = tuple(tag_ids) if tag_ids else None
    rows = await sessions_db.list_all(
        db,
        kind=kind,
        include_closed=include_closed,
        tag_ids=tag_filter,
    )
    return [_to_out(row) for row in rows]


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
    return _to_out(row)


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
    return _to_out(row)


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
    return _to_out(row)


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
    return _to_out(row)


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
