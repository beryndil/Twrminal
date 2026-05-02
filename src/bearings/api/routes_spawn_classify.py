"""Wave 3 classify endpoint
(`~/.claude/plans/classifying-spawn-reply-wave-3.md`).

``POST /sessions/{id}/spawn_from_reply/{message_id}/classify``

Reads the target assistant reply, drives the LLM classifier (when
``agent.enable_llm_spawn_classifier`` is True), and returns a
``SpawnClassifyResult`` describing the recommended spawn shape.

Design notes:

- **Always 200.** The classifier is an enhancement, not a gate. When
  the config flag is off, or the LLM call fails after two retries, the
  endpoint returns a single_chat fallback result — never a 503.
  The frontend confirmation card renders whatever shape it receives.

- **Separate from the spawn endpoint.** The plan recommends keeping
  "decide" (this endpoint) apart from "do" (the existing
  ``POST /sessions/{id}/spawn_from_reply/{message_id}``). The UI calls
  this endpoint first, renders the confirmation card, then calls the
  appropriate spawn/create flow after the operator clicks Apply.

- **Cost attribution.** When the classifier runs, its cost rolls into
  the parent session's ``total_cost_usd`` via ``add_session_cost``,
  matching the TLDR pattern from ``routes_reply_actions.py``. If cost
  attribution fails it is logged and silently dropped — a failed DB
  write must not turn a successful classify response into an error.

- **400/404 gates.** Same validation as ``routes_spawn_from_reply``:
  404 on unknown session or message, 400 when the target message does
  not belong to this session or is not an assistant turn.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from bearings.agent.spawn_classifier import _fallback, classify_reply
from bearings.api.auth import require_auth
from bearings.api.models import SpawnClassifyResult
from bearings.db import store

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sessions",
    tags=["spawn"],
    dependencies=[Depends(require_auth)],
)


@router.post(
    "/{session_id}/spawn_from_reply/{message_id}/classify",
    response_model=SpawnClassifyResult,
)
async def classify_spawn(
    session_id: str,
    message_id: str,
    request: Request,
) -> SpawnClassifyResult:
    """Classify the shape of ``message_id``'s assistant reply.

    Always returns 200 — the response is either the LLM classifier
    result or a graceful single_chat fallback.

    404 when either id is unknown.
    400 when the message doesn't belong to this session or is not an
    assistant turn.
    """
    conn = request.app.state.db
    settings = request.app.state.settings

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
        raise HTTPException(
            status_code=400,
            detail="message does not belong to this session",
        )
    if msg_row["role"] != "assistant":
        raise HTTPException(
            status_code=400,
            detail="classify requires an assistant message",
        )

    reply_text = str(msg_row["content"] or "")

    if not settings.agent.enable_llm_spawn_classifier:
        log.debug(
            "classify_spawn: classifier disabled, returning fallback for message %s",
            message_id,
        )
        return _fallback(reply_text)

    # Use title_suggest_model when configured — same Haiku-class model
    # reuse rationale as the title suggester: classification is a
    # lightweight one-shot task that doesn't need Opus horsepower.
    model = settings.agent.title_suggest_model or str(parent["model"])

    result = await classify_reply(reply_text, model=model)

    # Cost attribution — best-effort, matching the TLDR pattern.
    cost = _extract_cost(result)
    if cost and cost > 0:
        try:
            await store.add_session_cost(conn, session_id, cost)
        except Exception:  # noqa: BLE001
            log.warning(
                "classify_spawn: failed to attribute cost %.6f to session %s",
                cost,
                session_id,
            )

    return result


def _extract_cost(result: SpawnClassifyResult) -> float | None:
    """Pull the LLM cost out of the result when the classifier attached
    it. Currently a stub — ``classify_reply`` uses the SDK ``query``
    helper which doesn't surface cost at the call site the way
    ``ClaudeSDKClient`` does. Reserved for a future pass that wraps
    the query call in a cost-tracking context; for now returns None
    so the cost-attribution block is a safe no-op."""
    return None
