"""App-scoped registry of live `SessionRunner`s.

Separate from `runner.py` so the single-session execution concern (one
runner owns one agent + one stream loop) stays distinct from the fleet
concern (many runners keyed by session id, with app-lifecycle draining
and background eviction of idle runners).

Factory injection keeps the registry's import graph minimal: callers
build a closure over `app.state.db` / settings / whatever they need and
hand that in, so the registry itself doesn't pull FastAPI or the DB
module transitively."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from bearings.agent.runner import SessionRunner

log = logging.getLogger(__name__)

# Callable that turns a session id into a runner. Kept as a module-level
# type alias so the registry and its callers agree on the shape without
# circular imports through `runner.py`.
RunnerFactory = Callable[[str], Awaitable["SessionRunner"]]


class RunnerRegistry:
    """App-scoped registry of live runners, keyed by session id.

    First WS connect for a session lazily creates the runner; the
    `delete_session` route drops it. On app shutdown every runner is
    drained so no stream is left orphaned. An optional background
    reaper evicts runners that have been "quiet" (idle + zero
    subscribers) longer than `idle_ttl_seconds`, which bounds memory
    when a user hops through many sessions without deleting any."""

    def __init__(
        self,
        *,
        idle_ttl_seconds: float = 0.0,
        reap_interval_seconds: float = 60.0,
    ) -> None:
        self._runners: dict[str, SessionRunner] = {}
        self._lock = asyncio.Lock()
        self._idle_ttl = idle_ttl_seconds
        self._reap_interval = reap_interval_seconds
        self._reaper: asyncio.Task[None] | None = None

    async def get_or_create(
        self,
        session_id: str,
        *,
        factory: RunnerFactory,
    ) -> SessionRunner:
        async with self._lock:
            runner = self._runners.get(session_id)
            if runner is None:
                runner = await factory(session_id)
                runner.start()
                self._runners[session_id] = runner
            return runner

    def get(self, session_id: str) -> SessionRunner | None:
        return self._runners.get(session_id)

    def running_ids(self) -> set[str]:
        """Sessions whose worker currently has a turn in flight. Cheap
        to call — just iterates the dict."""
        return {sid for sid, r in self._runners.items() if r.is_running}

    def awaiting_user_ids(self) -> set[str]:
        """Sessions whose runner is parked on a `can_use_tool` decision
        right now (tool-use approval OR AskUserQuestion). Cheap — same
        dict walk as `running_ids`. Feeds the sidebar's red-flashing
        indicator via the `/api/sessions/running` fallback poll; the
        WS `runner_state` broadcast is the live path."""
        return {sid for sid, r in self._runners.items() if r.is_awaiting_user}

    async def drop(self, session_id: str) -> None:
        """Shut down and remove the runner for a deleted session. Safe
        when no runner exists (no-op)."""
        async with self._lock:
            runner = self._runners.pop(session_id, None)
        if runner is not None:
            await runner.shutdown()

    # ---- reaper ---------------------------------------------------

    def start_reaper(self) -> None:
        """Spawn the background eviction loop. No-op when the TTL is
        disabled (<=0) or the task is already running. Called once from
        the FastAPI `lifespan` after settings are applied."""
        if self._idle_ttl <= 0:
            return
        if self._reaper is not None and not self._reaper.done():
            return
        self._reaper = asyncio.create_task(self._reap_loop(), name="runner-reaper")

    async def _reap_loop(self) -> None:
        """Wake every `reap_interval_seconds`, evict quiet runners.
        Swallows per-iteration exceptions so one bad runner can't kill
        the reaper for the rest of the app's life — the loop logs and
        keeps going."""
        try:
            while True:
                await asyncio.sleep(self._reap_interval)
                try:
                    evicted = await self.reap_once()
                except Exception:
                    log.exception("runner registry: reaper iteration failed")
                    continue
                if evicted:
                    log.info("runner registry: evicted idle runners %s", evicted)
        except asyncio.CancelledError:
            return

    async def reap_once(self, *, now: float | None = None) -> list[str]:
        """Evict every runner currently eligible for reaping. Returns
        the ids that were shut down, in dict-iteration order. Safe to
        call directly — tests drive eviction through this entry point
        so they don't have to wait for `_reap_interval`."""
        if self._idle_ttl <= 0:
            return []
        moment = time.monotonic() if now is None else now
        async with self._lock:
            victims = {
                sid: runner
                for sid, runner in self._runners.items()
                if runner.should_reap(moment, self._idle_ttl)
            }
            for sid in victims:
                del self._runners[sid]
        # Shutdown outside the lock — each `shutdown()` awaits the
        # worker task, and we don't want to block other registry ops
        # behind a potentially slow SDK interrupt.
        for runner in victims.values():
            await runner.shutdown()
        return list(victims.keys())

    async def shutdown_all(self) -> None:
        # Cancel the reaper first so it can't race with the drain loop
        # below and try to evict a runner we're already shutting down.
        if self._reaper is not None and not self._reaper.done():
            self._reaper.cancel()
            try:
                await self._reaper
            except asyncio.CancelledError:
                pass
        async with self._lock:
            runners = list(self._runners.values())
            self._runners.clear()
        for r in runners:
            await r.shutdown()
