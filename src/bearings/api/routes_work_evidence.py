"""Synth-gate evidence endpoint
(`~/.claude/rules/decision-discipline.md` §4).

Single route: `GET /sessions/{session_id}/work_evidence` returns a
structured snapshot of the session's tool-call history that an
orchestrator can cross-check against the executor's `DONE` claim.
The endpoint never enforces — provides data, caller adjudicates.

See `bearings.agent.work_evidence.gather_work_evidence` for the
gathering logic and `models/work_evidence.py` for the response shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from bearings.agent.work_evidence import gather_work_evidence
from bearings.api.auth import require_auth
from bearings.api.models import WorkEvidence

router = APIRouter(
    prefix="/sessions",
    tags=["work_evidence"],
    dependencies=[Depends(require_auth)],
)


@router.get(
    "/{session_id}/work_evidence",
    response_model=WorkEvidence,
)
async def get_work_evidence(session_id: str, request: Request) -> WorkEvidence:
    """Return the executor session's work evidence for orchestrator
    cross-check. 404 if the session does not exist; otherwise a
    `WorkEvidence` body even for sessions with zero tool calls
    (empty arrays let the caller distinguish 'no work' from 'session
    not found')."""
    conn = request.app.state.db
    evidence = await gather_work_evidence(conn, session_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="session not found")
    return WorkEvidence(**evidence)
