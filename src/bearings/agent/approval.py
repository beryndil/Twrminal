# mypy: disable-error-code=explicit-any
"""``can_use_tool`` ↔ approval-modal bridge.

Per Slice A4 of ``~/.claude/plans/wiring-agent-loop.md``: when the
SDK opens ``can_use_tool`` for a tool that requires approval, the
worker hands the request to the broker. The broker emits an
:class:`bearings.agent.events.ApprovalRequest` AgentEvent (so the
conversation pane opens its modal) and parks an
:class:`asyncio.Future` keyed by ``request_id``. The user's choice
arrives via :class:`bearings.web.routes.approvals` (REST) or via an
inbound WS ``approval_resolved`` frame, which calls
:meth:`ApprovalBroker.resolve` to fulfil the future. The SDK
callback awaits the future and returns the matching
``PermissionResultAllow`` / ``PermissionResultDeny``.

Per sign-off Q4 (accepted 2026-05-01) **no timeout** is enforced in
v1: a stuck modal is a UX bug, not a security issue. The user is
the only operator. If the user closes the tab, the WS disconnect
eventually triggers idle-reap (A5), which cancels the supervisor
task and propagates :class:`asyncio.CancelledError` through the
parked future.

References:

* ``docs/architecture-v1.md`` §2.1 — broker as future-map.
* ``docs/behavior/chat.md`` §"Approval modal" — the UX surface.
* SDK docs (``claude_agent_sdk.types.ToolPermissionContext``,
  ``PermissionResultAllow``, ``PermissionResultDeny``).
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from bearings.agent.events import ApprovalRequest, ApprovalResolved
from bearings.agent.runner import SessionRunner

# Hex bytes for the request id; 16 random bytes → 32 hex chars,
# enough entropy that a stuck broker never collides with a future
# request after restart even though the broker is in-memory only.
_REQUEST_ID_BYTES = 16


class ApprovalBroker:
    """Per-session in-memory broker for ``can_use_tool`` approvals.

    The broker is constructed once per session; the supervisor (in
    ``web/runner_factory.py``) wires its :meth:`callback` into
    :class:`OptionsKwargs.can_use_tool`. The route layer
    (``web/routes/approvals.py``) and the WS handler
    (``web/streaming.py``) call :meth:`resolve` when the user
    clicks Allow / Deny.

    Multiple in-flight approvals are supported — the broker keys
    futures by ``request_id`` so concurrent tool calls don't
    interfere.
    """

    def __init__(self, runner: SessionRunner) -> None:
        self._runner = runner
        self._pending: dict[str, asyncio.Future[bool]] = {}

    # ------------------------------------------------------------------
    # SDK-side: produce a callback the SDK invokes for each gated tool.
    # ------------------------------------------------------------------

    def callback(
        self,
    ) -> Any:
        """Return the SDK-shape ``can_use_tool`` callback bound to
        this broker.

        The SDK expects ``Callable[[str, dict[str, Any],
        ToolPermissionContext], Awaitable[PermissionResultAllow |
        PermissionResultDeny]]``. The callback opens an approval
        request on the broker, awaits the user's choice, and
        translates it into the SDK's union return type.
        """

        async def _can_use_tool(
            tool_name: str,
            tool_input: dict[str, Any],
            context: ToolPermissionContext,
        ) -> PermissionResultAllow | PermissionResultDeny:
            request_id = self._fresh_id()
            approved = await self.open(
                request_id=request_id,
                tool_name=tool_name,
                tool_input=tool_input,
            )
            if approved:
                return PermissionResultAllow(
                    behavior="allow",
                    updated_input=None,
                    updated_permissions=None,
                )
            return PermissionResultDeny(
                behavior="deny",
                message=f"User denied {tool_name} for tool_use {context.tool_use_id!r}",
                interrupt=False,
            )

        return _can_use_tool

    # ------------------------------------------------------------------
    # Broker surface — open / resolve / cancel.
    # ------------------------------------------------------------------

    async def open(
        self,
        *,
        request_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> bool:
        """Emit :class:`ApprovalRequest` and await the user's
        choice. Returns ``True`` for allow, ``False`` for deny.

        Per sign-off Q4 there is no timeout — the future blocks
        until either :meth:`resolve` is called OR the supervisor
        task is cancelled (in which case ``asyncio.CancelledError``
        propagates).
        """
        if not request_id:
            raise ValueError("ApprovalBroker.open: request_id must be non-empty")
        if request_id in self._pending:
            raise ValueError(f"ApprovalBroker.open: request_id {request_id!r} already pending")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._runner.emit(
                ApprovalRequest(
                    session_id=self._runner.session_id,
                    request_id=request_id,
                    tool_name=tool_name,
                    tool_input_json=json.dumps(tool_input, sort_keys=True),
                )
            )
            return await future
        finally:
            # Drop the entry whether the future resolved, raised, or
            # was cancelled. A subsequent open() with the same id is
            # then permitted.
            self._pending.pop(request_id, None)

    async def resolve(self, request_id: str, *, approved: bool) -> bool:
        """Mark ``request_id`` as resolved.

        Returns ``True`` if the future was resolved (i.e. the broker
        had a pending request with that id); ``False`` if the
        request_id was unknown (already resolved, or never opened —
        defensive against duplicate WS / REST resolutions). Emits
        :class:`ApprovalResolved` on the runner so all live
        subscribers see the modal close, regardless of which channel
        carried the resolution.
        """
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        await self._runner.emit(
            ApprovalResolved(
                session_id=self._runner.session_id,
                request_id=request_id,
                approved=approved,
            )
        )
        return True

    def cancel_all(self) -> None:
        """Cancel every pending approval future. Called by the
        supervisor on idle-reap / app shutdown so the SDK's
        ``can_use_tool`` callbacks raise CancelledError instead of
        blocking forever.
        """
        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()

    @property
    def pending_count(self) -> int:
        """Number of in-flight approval requests. Test introspection."""
        return len(self._pending)

    @staticmethod
    def _fresh_id() -> str:
        """Generate a fresh request id."""
        return secrets.token_hex(_REQUEST_ID_BYTES)


__all__ = ["ApprovalBroker"]
