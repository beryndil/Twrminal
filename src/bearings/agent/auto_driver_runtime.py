"""Concrete `DriverRuntime` binding — plus the per-app
`AutoDriverRegistry` that owns live `Driver` tasks.

The state machine in `auto_driver.py` is runtime-agnostic by design.
This module wires it to the real world:

- `AgentRunnerDriverRuntime` implements the `DriverRuntime` protocol
  against the app's existing `RunnerRegistry` + `SessionRunner` stack.
  `spawn_leg` creates a fresh paired chat session, inheriting the
  parent checklist's tags + working-dir; `run_turn` drives one turn
  through a real runner and returns the assistant's final message
  body for the sentinel parser; `teardown_leg` drops the runner
  (session row stays for the audit trail).

- `AutoDriverRegistry` owns the lifecycle of running `Driver` tasks
  so the HTTP layer can start / query / stop them without juggling
  `asyncio.Task`s themselves. One driver per checklist session; a
  second start request while one is running is a 409, not a silent
  clobber.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from bearings import metrics
from bearings.agent.auto_driver import (
    Driver,
    DriverConfig,
    DriverOutcome,
    DriverResult,
)
from bearings.db import store

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)


class AgentRunnerDriverRuntime:
    """Binds the `DriverRuntime` protocol to the app's real agent
    runners. Construct with the FastAPI `app` so the runtime can
    pull `app.state.db`, `app.state.runners`, and the default-budget
    setting as it spawns legs.
    """

    def __init__(self, *, app: FastAPI, config: DriverConfig | None = None) -> None:
        self._app = app
        # Driver config — accessed for the per-leg permission_mode so
        # spawn_leg can persist `bypassPermissions` (default for
        # autonomous mode) onto the new chat session BEFORE the runner
        # is built. The runner reads `permission_mode` off the row at
        # construction time (see `ws_agent._build_runner`), so this
        # has to happen before the first `run_turn` call.
        self._config = config or DriverConfig()
        # Per-session last-observed ContextUsage percentage. Populated
        # as `run_turn` drains the runner's event stream after the
        # turn's MessageComplete arrives (ContextUsage fires right
        # after). The driver polls this via `last_context_percentage`
        # to decide whether to inject a handoff nudge. Unbounded dict
        # in principle, but keyed by leg session_id which the driver
        # tears down on its own cadence — not a leak in practice.
        self._last_pct: dict[str, float] = {}

    async def spawn_leg(
        self,
        *,
        item: dict[str, Any],
        leg_number: int,
        plug: str | None,
    ) -> str:
        """Create a fresh paired chat session for `item` as leg N.

        Inherits the parent checklist's working_dir, model, and tag
        set — matches the logic in `routes_checklists.spawn_paired_chat`
        with two differences:

        1. No idempotency. Each call creates a NEW session; the
           forward pointer (`checklist_items.chat_session_id`) is
           advanced to the new leg so the "current leg" view matches.
           Prior legs are still enumerable via the reverse pointer
           (`store.list_item_sessions`).
        2. `plug` — the handoff text from the prior leg — lands in
           `description` so the sidebar shows it, and in
           `session_instructions` so every turn in this leg carries
           it into the prompt (matches Dave's manual handoff
           discipline from `~/.claude/CLAUDE.md`).
        """
        conn = self._app.state.db
        parent_session_id = item["checklist_id"]
        parent_session = await store.get_session(conn, parent_session_id)
        assert parent_session is not None, "checklist_id must refer to an existing session"
        parent_tags = await store.list_session_tags(conn, parent_session_id)

        # Title carries the leg number only for legs ≥ 2 so the
        # sidebar doesn't clutter itself for the common one-leg case.
        title = f"{item['label']} (leg {leg_number})" if leg_number > 1 else str(item["label"])
        budget = self._app.state.settings.agent.default_max_budget_usd

        leg_row = await store.create_session(
            conn,
            working_dir=parent_session["working_dir"],
            model=parent_session["model"],
            title=title,
            description=plug,
            max_budget_usd=budget,
            kind="chat",
            checklist_item_id=int(item["id"]),
        )
        for tag in parent_tags:
            await store.attach_tag(conn, leg_row["id"], tag["id"])
        # Inherit default severity the same way the manual spawn path
        # does. See migration 0021.
        await store.ensure_default_severity(conn, leg_row["id"])
        # Persist the plug as session_instructions so every turn in
        # this leg rehydrates the handoff state, not just the kickoff.
        if plug is not None:
            await store.update_session(
                conn,
                leg_row["id"],
                fields={"session_instructions": plug},
            )
        # Set the leg's PermissionMode BEFORE the runner is built so
        # the SDK's can_use_tool hook doesn't park on every Edit/Bash.
        # `bypassPermissions` (the DriverConfig default) means the
        # autonomous run truly runs unattended; `acceptEdits` is a
        # mid-ground for cautious users; `default` is "still
        # supervised" and effectively breaks autonomy. Persisted via
        # store helper so a later WS reconnect or runner rebuild
        # picks up the same mode.
        await store.set_session_permission_mode(
            conn, leg_row["id"], self._config.leg_permission_mode
        )
        # Advance the current-leg pointer on the item.
        await store.set_item_chat_session(conn, int(item["id"]), leg_row["id"])
        metrics.sessions_created.inc()
        return str(leg_row["id"])

    async def run_turn(self, *, session_id: str, prompt: str) -> str:
        """Run one turn on `session_id` and return the assistant's
        final text. Blocks until the runner emits `message_complete`
        (or an error event — raised as an exception).

        Subscribes to the runner BEFORE submitting the prompt so we
        don't race past the completion event. Unsubscribes in a
        `finally` block so a cancelled turn doesn't leak the
        subscription set.
        """
        # Lazy import to avoid pulling FastAPI-specific plumbing into
        # modules that don't need it (the driver itself stays pure).
        from bearings.api.ws_agent import _build_runner

        async def _factory(sid: str) -> Any:
            return await _build_runner(self._app, sid)

        registry = self._app.state.runners
        runner = await registry.get_or_create(session_id, factory=_factory)
        queue, _replay = await runner.subscribe(since_seq=0)
        try:
            await runner.submit_prompt(prompt)
            message_id = await self._await_message_complete(queue, session_id)
            # ContextUsage fires right after MessageComplete (see
            # session.py around line 260). Drain the queue briefly to
            # catch it — bounded by a short timeout so a runner that
            # never emits one doesn't stall the driver.
            await self._drain_trailing_context_usage(queue, session_id)
        finally:
            runner.unsubscribe(queue)

        conn = self._app.state.db
        # Pull the just-persisted assistant row. list_messages is
        # ordered by created_at; the completion we're waiting for is
        # whichever row carries `message_id`.
        messages = await store.list_messages(conn, session_id)
        for msg in messages:
            if msg["id"] == message_id and msg["role"] == "assistant":
                content = msg.get("content")
                return str(content) if content is not None else ""
        raise RuntimeError(
            f"assistant message {message_id!r} not found after completion "
            f"event on session {session_id!r}"
        )

    async def teardown_leg(self, session_id: str) -> None:
        """Drop the leg's runner. The `sessions` row stays in the DB
        (audit trail, legs expander). Idempotent — `.drop()` no-ops
        when the session id isn't registered."""
        await self._app.state.runners.drop(session_id)
        # Discard any cached context pressure reading so a future leg
        # that somehow reuses the same session id (shouldn't happen in
        # practice but the driver's session_id lookup should stay
        # honest) doesn't inherit stale state.
        self._last_pct.pop(session_id, None)

    def last_context_percentage(self, session_id: str) -> float | None:
        """Return the most recent ContextUsage percentage (0..100)
        captured for `session_id`, or None if none was observed. Feeds
        the driver's handoff-nudge branch. See `DriverConfig.
        handoff_threshold_percent`."""
        return self._last_pct.get(session_id)

    async def _drain_trailing_context_usage(
        self,
        queue: asyncio.Queue[Any],
        session_id: str,
    ) -> None:
        """Peek at any events that arrive right after MessageComplete
        and stash the percentage from the first `context_usage` event
        we find. Bounded by a short timeout — if nothing arrives
        promptly, give up; the runner either isn't going to emit one
        this turn (synthetic completion path), or we lost the race.
        Missing a pressure reading opts this leg out of the nudge
        branch, which is the safe default (no unnecessary nudges)."""
        # 50ms is enough slack for the runner's post-turn ContextUsage
        # emit (it fires in-line after MessageComplete on the same
        # task). Pay the budget once; further drains just slow the
        # driver's per-turn latency.
        deadline = asyncio.get_running_loop().time() + 0.05
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            try:
                env = await asyncio.wait_for(queue.get(), timeout=remaining)
            except TimeoutError:
                return
            payload = env.payload
            if payload.get("type") != "context_usage":
                continue
            if payload.get("session_id") != session_id:
                continue
            pct = payload.get("percentage")
            if pct is not None:
                self._last_pct[session_id] = float(pct)
            return

    async def _await_message_complete(
        self,
        queue: asyncio.Queue[Any],
        session_id: str,
    ) -> str:
        """Block until a `message_complete` event for `session_id`
        appears on the queue. Error events raise. Any other event
        (tokens, thinking, tool calls, context usage) is skipped.
        """
        while True:
            env = await queue.get()
            payload = env.payload
            etype = payload.get("type")
            psid = payload.get("session_id")
            if psid != session_id:
                # Fresh runner per leg, so this shouldn't happen in
                # practice. Skip defensively rather than crash.
                continue
            if etype == "message_complete":
                return str(payload["message_id"])
            if etype == "error":
                msg = payload.get("message") or "unknown runner error"
                raise RuntimeError(f"runner error: {msg}")


class AutoDriverRegistry:
    """App-scoped registry of running autonomous `Driver` tasks.

    Keyed by `checklist_session_id`. Each entry is a live
    `asyncio.Task` plus the `Driver` instance that owns the stop
    flag. The HTTP layer reads status off `.status()` and shuts
    drivers down via `.stop()` without managing task handles itself.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Driver, asyncio.Task[DriverResult]]] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        app: FastAPI,
        checklist_session_id: str,
        config: DriverConfig | None = None,
    ) -> None:
        """Launch a driver for `checklist_session_id` in the
        background. Raises `ValueError` if one is already running.
        """
        async with self._lock:
            existing = self._entries.get(checklist_session_id)
            if existing is not None and not existing[1].done():
                raise ValueError(
                    f"autonomous driver already running for checklist {checklist_session_id!r}"
                )
            # Resolve the effective config once and feed BOTH the
            # runtime (needs leg_permission_mode for spawn_leg) and
            # the driver (needs the safety caps + handoff threshold).
            # Two callers must agree on the same instance, hence the
            # explicit fallback to a fresh DriverConfig() here.
            effective_config = config or DriverConfig()
            runtime = AgentRunnerDriverRuntime(app=app, config=effective_config)
            driver = Driver(
                conn=app.state.db,
                runtime=runtime,
                checklist_session_id=checklist_session_id,
                config=effective_config,
            )
            task: asyncio.Task[DriverResult] = asyncio.create_task(
                driver.drive(),
                name=f"auto-driver:{checklist_session_id}",
            )
            self._entries[checklist_session_id] = (driver, task)

    def status(self, checklist_session_id: str) -> dict[str, Any] | None:
        """Return a plain-dict status snapshot, or `None` if no
        driver has ever been started for this checklist."""
        entry = self._entries.get(checklist_session_id)
        if entry is None:
            return None
        driver, task = entry
        if not task.done():
            return {
                "state": "running",
                "items_completed": driver._items_completed,
                "items_failed": driver._items_failed,
                "items_skipped": driver._items_skipped,
                "legs_spawned": driver._legs_spawned,
            }
        # Task finished — either cleanly with a result, or with an
        # exception. Both are observable through status.
        exc = task.exception()
        if exc is not None:
            return {
                "state": "errored",
                "error": f"{type(exc).__name__}: {exc}",
            }
        result: DriverResult = task.result()
        snapshot = asdict(result)
        # `DriverOutcome` is a StrEnum so asdict already serializes
        # it as the string value; explicit cast guards against a
        # future bare-Enum refactor.
        snapshot["outcome"] = (
            result.outcome.value
            if isinstance(result.outcome, DriverOutcome)
            else str(result.outcome)
        )
        snapshot["state"] = "finished"
        return snapshot

    async def stop(self, checklist_session_id: str) -> bool:
        """Flag the driver for `checklist_session_id` to exit at its
        next iteration boundary. Returns True if a running driver was
        signaled; False if none was registered or the driver is
        already finished.
        """
        entry = self._entries.get(checklist_session_id)
        if entry is None:
            return False
        driver, task = entry
        if task.done():
            return False
        driver.stop()
        return True

    async def shutdown_all(self) -> None:
        """App-shutdown hook. Signals every driver and awaits their
        natural exit. Used from the FastAPI lifespan so outstanding
        drivers don't get killed mid-leg."""
        async with self._lock:
            entries = list(self._entries.values())
        for driver, _task in entries:
            driver.stop()
        for _driver, task in entries:
            if not task.done():
                try:
                    await task
                except Exception:
                    # Logged inside the driver; nothing to re-raise
                    # on shutdown path.
                    log.exception("auto-driver task raised during shutdown")

    def forget(self, checklist_session_id: str) -> None:
        """Drop a finished driver's entry so a later run can start
        fresh. No-op if the driver isn't finished (prevents a caller
        from accidentally orphaning a live driver)."""
        entry = self._entries.get(checklist_session_id)
        if entry is None:
            return
        if entry[1].done():
            del self._entries[checklist_session_id]
