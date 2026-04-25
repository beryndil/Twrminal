"""Per-tool-call keepalive ticker manager.

Why a manager class: a long-running tool call (Task/Agent sub-agent,
slow grep, build) can park the SDK for tens of seconds with zero
events on the wire. Without a heartbeat, the UI's running spinner
reads as dead and the user starts wondering whether to cancel. The
manager spawns one ticker task per in-flight `tool_call_id` that fires
a `ToolProgress` event every cadence interval, fan-out-only (never
hits the ring buffer or DB).

Owned by the runner's worker task — single-task ownership, no locking
inside. Exposed as `_progress_tickers` and `_progress_started`
properties on `SessionRunner` for the unit tests that pin the
start/stop lifecycle directly.

Cadence is read via an `interval_getter` callable rather than baked
in at construction so test monkeypatching of
`runner.TOOL_PROGRESS_INTERVAL_S` is observed on the very next sleep
— matches the prior in-class implementation's semantics.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from bearings.agent.events import AgentEvent, ToolProgress

log = logging.getLogger(__name__)


class ProgressTickerManager:
    """Owns the per-`tool_call_id` ticker task dict + start times.

    `emit` is the runner's `_emit_ephemeral` (fan-out without ring
    buffer). `interval_getter` returns the current cadence in seconds;
    consulted on every loop iteration so a mid-turn config / test
    patch flows through without restarting tickers.
    """

    def __init__(
        self,
        session_id: str,
        emit: Callable[[AgentEvent], Awaitable[None]],
        interval_getter: Callable[[], float],
    ) -> None:
        self.session_id = session_id
        self._emit = emit
        self._interval_getter = interval_getter
        # Per-tool-call keepalive tickers. One task per in-flight tool
        # call. Managed only by the runner's worker task; no locking.
        self.tickers: dict[str, asyncio.Task[None]] = {}
        # Monotonic start time so each tick's `elapsed_ms` is
        # self-contained — UI doesn't need the original timestamp to
        # render the readout.
        self.started: dict[str, float] = {}

    def start(self, tool_call_id: str) -> None:
        """Spawn a per-call keepalive task on the running loop.

        Idempotent: a duplicate `ToolCallStart` for the same id (which
        the turn loop already treats as a no-op) keeps the original
        ticker rather than leaking a second one. Records the monotonic
        start so each tick's `elapsed_ms` can be self-contained."""
        if tool_call_id in self.tickers:
            return
        self.started[tool_call_id] = time.monotonic()
        self.tickers[tool_call_id] = asyncio.create_task(
            self._ticker(tool_call_id),
            name=f"tool-progress:{self.session_id}:{tool_call_id}",
        )

    def stop(self, tool_call_id: str) -> None:
        """Cancel the ticker for one call. Safe to call for an id that
        has no ticker (never started, or already stopped)."""
        task = self.tickers.pop(tool_call_id, None)
        self.started.pop(tool_call_id, None)
        if task is not None:
            task.cancel()

    async def stop_all(self) -> None:
        """Cancel every ticker and wait for the cancellations to take
        effect before returning. Called from the turn's `finally` so
        an interrupted or exception-exited turn doesn't strand timers.

        Awaiting the gather ensures we don't leave tasks half-cancelled
        when `_run_forever` flips `_status` back to idle — a dangling
        `Task` could still try to `put_nowait` onto a subscriber queue
        after the runner's subscribers set has been mutated elsewhere.
        `return_exceptions=True` swallows the expected
        `CancelledError`s from each task."""
        tasks = list(self.tickers.values())
        self.tickers.clear()
        self.started.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _ticker(self, tool_call_id: str) -> None:
        """Emit a `ToolProgress` event every interval until cancelled.

        Intentionally robust against late cancellation: if the ticker
        is cancelled while blocked in `asyncio.sleep`, the raise
        propagates out cleanly; if the start time was cleared under
        us (e.g. `stop_all` ran first), the loop exits without
        emitting anything.

        Errors during `emit` are logged and swallowed — the keepalive
        is advisory, and a broken fan-out must never kill the user's
        turn."""
        while True:
            try:
                await asyncio.sleep(self._interval_getter())
            except asyncio.CancelledError:
                return
            started = self.started.get(tool_call_id)
            if started is None:
                return
            elapsed_ms = int((time.monotonic() - started) * 1000)
            try:
                await self._emit(
                    ToolProgress(
                        session_id=self.session_id,
                        tool_call_id=tool_call_id,
                        elapsed_ms=elapsed_ms,
                    )
                )
            except Exception:
                log.exception(
                    "session %s: tool_progress emit failed for %s",
                    self.session_id,
                    tool_call_id,
                )
