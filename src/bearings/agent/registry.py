"""App-scoped registry of live `SessionRunner`s.

Separate from `runner.py` so the single-session execution concern (one
runner owns one agent + one stream loop) stays distinct from the fleet
concern (many runners keyed by session id, with app-lifecycle draining).

Factory injection keeps the registry's import graph minimal: callers
build a closure over `app.state.db` / settings / whatever they need and
hand that in, so the registry itself doesn't pull FastAPI or the DB
module transitively."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from bearings.agent.runner import SessionRunner

# Callable that turns a session id into a runner. Kept as a module-level
# type alias so the registry and its callers agree on the shape without
# circular imports through `runner.py`.
RunnerFactory = Callable[[str], Awaitable["SessionRunner"]]


class RunnerRegistry:
    """App-scoped registry of live runners, keyed by session id.

    First WS connect for a session lazily creates the runner; the
    `delete_session` route drops it. On app shutdown every runner is
    drained so no stream is left orphaned."""

    def __init__(self) -> None:
        self._runners: dict[str, SessionRunner] = {}
        self._lock = asyncio.Lock()

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

    async def drop(self, session_id: str) -> None:
        """Shut down and remove the runner for a deleted session. Safe
        when no runner exists (no-op)."""
        async with self._lock:
            runner = self._runners.pop(session_id, None)
        if runner is not None:
            await runner.shutdown()

    async def shutdown_all(self) -> None:
        async with self._lock:
            runners = list(self._runners.values())
            self._runners.clear()
        for r in runners:
            await r.shutdown()
