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

# Tools the SDK classifies as edits. `acceptEdits` mode blankets
# these without prompting; anything outside this set still gates on
# per-call approval even in that mode. Kept in sync with the Claude
# Code SDK's own edit classification — adding a new edit tool here
# means it auto-resolves under `acceptEdits` the same as the rest.
EDIT_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

# Tools whose whole purpose is to collect a user response, so they
# must NEVER auto-allow regardless of permission_mode. Auto-allowing
# returns `PermissionResultAllow()` with no `updated_input`, which
# means the SDK invokes the tool with the original payload (the
# questions, no answers). The tool's stock output then says "User
# has answered your questions: ." (the empty value where the user's
# pick should go) and the agent loops or stalls — exactly the
# 2026-04-25 symptom on the autonomous tier-1 prereq leg where three
# AskUserQuestion calls in 30 minutes all auto-completed in <100ms
# with empty answers and the agent never made progress.
#
# Park these every time so the user actually sees the modal and the
# answer rides back via `PermissionResultAllow(updated_input=...)`
# (the AskUserQuestion modal's normal flow).
NEVER_AUTO_ALLOW_TOOLS: frozenset[str] = frozenset({"AskUserQuestion"})


class ApprovalBroker:
    """Owns the pending-approval Futures dict for one session.

    All three approval paths go through here:
    - `can_use_tool`: SDK callback that emits an ApprovalRequest and
      parks on a Future until a decision arrives.
    - `resolve`: WS-driven resolution from an `approval_response` frame.
    - `deny_all`: stop / shutdown path that unblocks every pending
      Future with `interrupt=True` so the SDK unwinds.
    - `resolve_for_mode`: permission-mode change path that retro-applies
      the new mode to already-parked approvals so the user can clear a
      live modal by escalating to `bypassPermissions` / `acceptEdits`
      instead of having to click through it.
    """

    def __init__(
        self,
        session_id: str,
        emit: EventEmitter,
        mode_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self.session_id = session_id
        self._emit = emit
        # Live read of the agent's current permission_mode. Threaded
        # through as a callable (not a stored value) so a mid-turn
        # `set_permission_mode` call is observed on the next
        # `can_use_tool` invocation without the broker having to
        # subscribe to anything. Default `None` getter preserves the
        # old "always park" behavior for tests / callers that don't
        # want mode-aware fast-paths.
        self._mode_getter: Callable[[], str | None] = mode_getter or (lambda: None)
        # Tool name is carried alongside the Future so `resolve_for_mode`
        # can apply the `acceptEdits` filter without reconstructing it
        # from the original `ApprovalRequest` event.
        self._pending: dict[str, tuple[str, asyncio.Future[PermissionResult]]] = {}

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
        so the agent stays ignorant of the runner.

        Mode-aware fast path (added 2026-04-25 after the fae8f1a8
        Settings-UX hang). The claude-agent-sdk invokes this callback
        for EVERY tool use even when `permission_mode='bypassPermissions'`
        is set on the SDK options — the mode controls the SDK's own
        prompt UI but a registered `can_use_tool` overrides it. Without
        the fast path below, an autonomous run hits a tool, our broker
        emits an `ApprovalRequest`, parks on a Future, and waits forever
        for a click that will never come. The 4-hour Edit hang on
        `~/.claude/plans/quiet-configuring-lighthouse.md` (item 42 of
        the fae8f1a8 tour) was exactly this: bypassPermissions on the
        row, factory rebuilt the runner with the right mode, agent
        invoked Edit, broker parked. Skipping the park entirely when
        the live mode says "auto-approve" is the correct answer.

        Matrix:
        - `bypassPermissions`: auto-allow every call (no event emitted,
          no Future, no park) — EXCEPT tools in
          `NEVER_AUTO_ALLOW_TOOLS` (e.g. `AskUserQuestion`) whose
          whole purpose is to collect user input.
        - `acceptEdits`: auto-allow Edit-class tools (`Edit`, `Write`,
          `MultiEdit`, `NotebookEdit`); park everything else.
        - `default` / `plan` / mode unknown: park as before so the user
          decides per call.
        """
        mode = self._mode_getter()
        # `AskUserQuestion` and any future input-collecting tool MUST
        # park even under `bypassPermissions`. Otherwise the SDK
        # invokes the tool with the original payload (no answer) and
        # the agent gets back "User has answered: ." (literal empty
        # answer), which loops the autonomous run. Place this check
        # BEFORE the bypass fast-path so it wins.
        if tool_name not in NEVER_AUTO_ALLOW_TOOLS:
            if mode == "bypassPermissions":
                return PermissionResultAllow()
            if mode == "acceptEdits" and tool_name in EDIT_TOOLS:
                return PermissionResultAllow()
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResult] = loop.create_future()
        self._pending[request_id] = (tool_name, future)
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

    async def resolve(
        self,
        request_id: str,
        decision: str,
        reason: str | None = None,
        updated_input: dict[str, Any] | None = None,
    ) -> None:
        """Resolve a pending approval raised by `can_use_tool`. Called
        by the WS handler on an `approval_response` frame. No-op if the
        id is unknown or already resolved — duplicate resolutions from
        two tabs answering the same modal mustn't crash.

        `updated_input` rides along with an allow decision so the
        permission component (the UI modal) can enrich what the SDK
        passes to the tool. The canonical use case is AskUserQuestion:
        the modal collects answers from the user, merges them into the
        original `questions` payload, and the SDK then invokes the tool
        with that enriched input — which is how the tool echoes the
        answers back to the agent. Ignored on deny."""
        entry = self._pending.get(request_id)
        if entry is None:
            return
        _tool_name, future = entry
        if future.done():
            return
        if decision == "allow":
            future.set_result(PermissionResultAllow(updated_input=updated_input))
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

    async def resolve_for_mode(self, new_mode: str) -> None:
        """Retro-apply a permission-mode change to already-parked
        approvals. The race this closes: the agent hits a gated tool,
        the broker parks on a Future and emits `ApprovalRequest`; the
        user responds by flipping the header selector to
        `bypassPermissions` instead of clicking the modal. Without this
        hook the SDK only consults the new mode on the *next* tool call
        — the current Future sits forever, the modal stays up, and the
        user has to click through the thing they just tried to dismiss
        wholesale.

        Matrix:
        - `bypassPermissions`: allow every parked approval EXCEPT
          tools in `NEVER_AUTO_ALLOW_TOOLS` (e.g. `AskUserQuestion`)
          whose whole purpose is to collect user input. Those stay
          parked so the user actually answers the question.
        - `acceptEdits`: allow parked approvals for SDK edit tools
          (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`); leave others
          parked.
        - `plan` or `default`: leave pending. Plan mode doesn't execute
          tools so the SDK will wind the current call down itself; the
          modal clearing there happens via the ordinary stop/interrupt
          path, not here.

        Fans `ApprovalResolved(decision=allow)` per cleared request so
        every mirroring tab drops the modal.
        """
        if new_mode not in ("bypassPermissions", "acceptEdits"):
            return
        # Snapshot before mutation: `resolve()` pops entries via the
        # `can_use_tool` finally-clause as soon as we set the result,
        # so iterating a live view would skip entries or raise.
        targets: list[str] = []
        for request_id, (tool_name, future) in self._pending.items():
            if future.done():
                continue
            # Mirror the `can_use_tool` fast-path policy: input-
            # collecting tools always park, even on a mid-park
            # bypass-mode flip. Otherwise the modal clears with no
            # answer and the agent loops the same way it does on a
            # fresh call.
            if tool_name in NEVER_AUTO_ALLOW_TOOLS:
                continue
            if new_mode == "bypassPermissions" or tool_name in EDIT_TOOLS:
                targets.append(request_id)
        for request_id in targets:
            entry = self._pending.get(request_id)
            if entry is None:
                continue
            _tool_name, future = entry
            if future.done():
                continue
            future.set_result(PermissionResultAllow())
            await self._emit(
                ApprovalResolved(
                    session_id=self.session_id,
                    request_id=request_id,
                    decision="allow",
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
        for request_id, (_tool_name, future) in self._pending.items():
            if not future.done():
                future.set_result(PermissionResultDeny(message=reason, interrupt=interrupt))
                denied.append(request_id)
        return denied
