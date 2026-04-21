"""Per-session broker for tool-use approval gating.

Why separate from the runner: the `can_use_tool` SDK callback, the
WS-driven `approval_response` resolution, and the stop/shutdown
deny-all paths all share one dict of pending Futures. Keeping them in
a small helper keeps `SessionRunner` focused on stream + prompt-queue
plumbing and leaves the approval protocol testable on its own.

The runner composes one of these per session and late-binds
`broker.can_use_tool` onto the `AgentSession` (see
`ws_agent._build_runner`). The broker never touches the SDK session
directly — it only emits events via the callback the runner hands in
and resolves Futures the SDK is awaiting.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import uuid4

from claude_agent_sdk import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from bearings.agent.events import AgentEvent, ApprovalRequest, ApprovalResolved

EventEmitter = Callable[[AgentEvent], Awaitable[None]]


class ApprovalBroker:
    """Owns the pending-approval Futures dict for one session.

    All three approval paths go through here:
    - `can_use_tool`: SDK callback that emits an ApprovalRequest and
      parks on a Future until a decision arrives.
    - `resolve`: WS-driven resolution from an `approval_response` frame.
    - `deny_all`: stop / shutdown path that unblocks every pending
      Future with `interrupt=True` so the SDK unwinds.
    """

    def __init__(self, session_id: str, emit: EventEmitter) -> None:
        self.session_id = session_id
        self._emit = emit
        self._pending: dict[str, asyncio.Future[PermissionResult]] = {}

    # ---- public API (also the SDK callback) -----------------------

    async def can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        """SDK `can_use_tool` callback. Emits an `ApprovalRequest` event
        and blocks on a Future until the WS handler receives the
        matching `approval_response` frame (or a stop/shutdown denies
        it). Bound to `agent.can_use_tool` by `ws_agent._build_runner`
        so the agent stays ignorant of the runner."""
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResult] = loop.create_future()
        self._pending[request_id] = future
        await self._emit(
            ApprovalRequest(
                session_id=self.session_id,
                request_id=request_id,
                tool_name=tool_name,
                input=dict(tool_input),
                tool_use_id=context.tool_use_id,
            )
        )
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def resolve(self, request_id: str, decision: str, reason: str | None = None) -> None:
        """Resolve a pending approval raised by `can_use_tool`. Called
        by the WS handler on an `approval_response` frame. No-op if the
        id is unknown or already resolved — duplicate resolutions from
        two tabs answering the same modal mustn't crash."""
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        if decision == "allow":
            future.set_result(PermissionResultAllow())
            resolved: Literal["allow", "deny"] = "allow"
        else:
            future.set_result(
                PermissionResultDeny(message=reason or "denied by user", interrupt=False)
            )
            resolved = "deny"
        await self._emit(
            ApprovalResolved(
                session_id=self.session_id,
                request_id=request_id,
                decision=resolved,
            )
        )

    async def deny_all(self, reason: str, *, interrupt: bool) -> None:
        """Deny every pending approval (stop / shutdown path) and fan
        `ApprovalResolved(decision=deny)` events for each denied id so
        mirroring tabs can clear their stale modals. The initiator's
        own tab has already dismissed optimistically; this covers
        every other observer."""
        denied = self._deny_sync(reason, interrupt=interrupt)
        for request_id in denied:
            await self._emit(
                ApprovalResolved(
                    session_id=self.session_id,
                    request_id=request_id,
                    decision="deny",
                )
            )

    # ---- internals -------------------------------------------------

    def _deny_sync(self, reason: str, *, interrupt: bool) -> list[str]:
        """Resolve every pending Future with `PermissionResultDeny`
        synchronously. Sync on purpose: the Future resolution has to
        land before the SDK wakes so the stream loop can reach its
        stop / shutdown check — if we awaited between Futures, the
        first wake could let the SDK re-enter `can_use_tool` and park
        a fresh Future behind our back."""
        denied: list[str] = []
        for request_id, future in self._pending.items():
            if not future.done():
                future.set_result(PermissionResultDeny(message=reason, interrupt=interrupt))
                denied.append(request_id)
        return denied
