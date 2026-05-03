"""Approval-resolution route.

Per Slice A4 of ``~/.claude/plans/wiring-agent-loop.md``: when the
SDK opens ``can_use_tool`` mid-turn, the
:class:`bearings.agent.approval.ApprovalBroker` parks an
``asyncio.Future`` and emits an
:class:`bearings.agent.events.ApprovalRequest` so the conversation
pane opens its modal. The user clicks Allow or Deny; the frontend
POSTs the choice here. This route resolves the broker's future via
:meth:`ApprovalBroker.resolve` so the SDK callback returns and the
agent's turn proceeds.

Failure modes:

* ``404`` — no session matches the id, OR the session has no
  in-flight approval broker (e.g. the session has no live
  supervisor — the runner was reaped).
* ``409`` — the broker rejected the resolution (the request_id is
  unknown / already resolved). Per ``ApprovalBroker.resolve``'s
  defensive contract a duplicate REST + WS resolution surfaces as
  this 409 rather than silently double-approving.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from bearings.agent.approval import ApprovalBroker
from bearings.web.models.approvals import ApprovalResolution
from bearings.web.runner_factory import InProcessRunnerRegistry

router = APIRouter()


@router.post(
    "/api/sessions/{session_id}/approvals/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def resolve_approval(
    session_id: str,
    request_id: str,
    payload: ApprovalResolution,
    request: Request,
) -> None:
    """Resolve a pending approval-modal request.

    The SDK callback waiting on the broker future receives
    ``payload.approved`` and translates it into a
    :class:`PermissionResultAllow` / :class:`PermissionResultDeny`
    SDK return value.
    """
    factory = getattr(request.app.state, "runner_factory", None)
    if not isinstance(factory, InProcessRunnerRegistry):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="approval surface requires the in-process runner registry",
        )
    broker = factory.get_approval_broker(session_id)
    if broker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no approval broker for session {session_id!r}",
        )
    if not isinstance(broker, ApprovalBroker):  # pragma: no cover — type pin
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="approval broker has unexpected type",
        )
    resolved = await broker.resolve(request_id, approved=payload.approved, answer=payload.answer)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"approval request {request_id!r} is unknown or already resolved "
                f"on session {session_id!r}"
            ),
        )


__all__ = ["router"]
