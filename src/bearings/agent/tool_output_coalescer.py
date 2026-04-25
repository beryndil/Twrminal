"""Per-`tool_call_id` write coalescer for `ToolOutputDelta` chunks.

Why separate from the runner: a chatty tool (tree, grep, long build
log) can emit hundreds of small deltas per second. Persisting each as
its own `append_tool_output` ran a full UPDATE + commit on the
aiosqlite thread per chunk. Buffering by `tool_call_id` and flushing
on either a chunk-count or a time threshold collapses N writes into
one without delaying live WS fan-out — only DB writes are batched;
subscribers still see every delta in real time. Keeping the buffers
dict + the timer plumbing in a small helper lets `SessionRunner` stay
focused on the stream / prompt-queue path.

Lifecycle, all driven from the runner's worker task (single owner —
no locking inside):
- `buffer()` accumulates a chunk and either arms the flush timer
  (first chunk for a call) or triggers a synchronous flush
  (count threshold reached).
- `_delayed_flush()` is the timer task: fires once per buffered burst
  and no-ops if the buffer has already drained.
- `flush_all()` drains every buffer at once — used on turn teardown
  so mid-stream chunks aren't stranded if no `ToolCallEnd` arrives
  (e.g. user stop, exception).
- `drop()` discards buffered chunks without writing — used in the
  `ToolCallEnd` arm because `finish_tool_call` overwrites `output`
  with the canonical final string anyway, so a buffered write would
  just be amplification.
"""

from __future__ import annotations

import asyncio
import logging

import aiosqlite

from bearings.db import store

log = logging.getLogger(__name__)

# Coalescing window for `ToolOutputDelta` → DB writes. The threshold
# pair is tuned together: at this interval/count, mid-stream
# visibility lag stays under one window of the live stream while
# bursty tools collapse to ~5% of their pre-coalesce write count.
# WS fan-out is NOT coalesced — only DB writes are batched.
FLUSH_INTERVAL_S = 0.075
FLUSH_CHUNK_COUNT = 32


class _ToolOutputBuffer:
    """Pending deltas for one `tool_call_id` waiting on a coalesced write.

    `flush_task` is the asyncio timer that will fire at
    `FLUSH_INTERVAL_S` after the first chunk landed. It's `None`
    between flushes; a new timer is scheduled the next time a chunk
    arrives into an empty buffer. `chunks` accumulates raw delta
    strings — they're joined once at flush time so we only pay the
    concat cost per flush, not per arrival.
    """

    __slots__ = ("chunks", "flush_task")

    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.flush_task: asyncio.Task[None] | None = None


class ToolOutputCoalescer:
    """Owns the per-`tool_call_id` buffer dict for one session runner.

    Constructed with the runner's DB connection and `session_id` so
    the runner can stay oblivious to flush cadence and DB write
    plumbing. All public methods assume single-task ownership — they
    mutate `_buffers` without locking — which matches the runner's
    actual usage (worker task only).
    """

    def __init__(self, db: aiosqlite.Connection, session_id: str) -> None:
        self.db = db
        self.session_id = session_id
        # Per-tool-call coalescing buffers. Entries are created on
        # first chunk arrival and removed on flush, on `drop()`, or on
        # `flush_all()` teardown. Exposed as `_buffers` rather than
        # private-via-property because callers (runner, tests) only
        # inspect it; the public surface is the four methods below.
        self._buffers: dict[str, _ToolOutputBuffer] = {}

    async def buffer(self, tool_call_id: str, chunk: str) -> None:
        """Append a `ToolOutputDelta` chunk to its per-tool-call buffer.

        Triggers an immediate synchronous flush if the chunk count hits
        `FLUSH_CHUNK_COUNT`; otherwise arms a timer so the buffer
        drains within `FLUSH_INTERVAL_S` of the first buffered chunk."""
        buf = self._buffers.get(tool_call_id)
        if buf is None:
            buf = _ToolOutputBuffer()
            self._buffers[tool_call_id] = buf
        buf.chunks.append(chunk)
        if len(buf.chunks) >= FLUSH_CHUNK_COUNT:
            # Count-triggered flush: cancel the pending timer so it
            # doesn't fire on an already-drained buffer, then write now.
            if buf.flush_task is not None:
                buf.flush_task.cancel()
                buf.flush_task = None
            await self._flush(tool_call_id)
            return
        if buf.flush_task is None:
            buf.flush_task = asyncio.create_task(
                self._delayed_flush(tool_call_id),
                name=f"tool-flush:{self.session_id}:{tool_call_id}",
            )

    def drop(self, tool_call_id: str) -> None:
        """Discard any buffered deltas for `tool_call_id` without
        writing them. Used by the runner's `ToolCallEnd` arm:
        `finish_tool_call` overwrites `output` with the canonical
        final string, so any buffered chunks would be immediately
        clobbered anyway."""
        buf = self._buffers.pop(tool_call_id, None)
        if buf is not None and buf.flush_task is not None:
            buf.flush_task.cancel()

    async def flush_all(self) -> None:
        """Drain every buffered tool call. Called on turn teardown
        (normal completion, stop, exception) and runner shutdown so
        mid-stream chunks don't get stranded if no `ToolCallEnd`
        arrives (e.g. interrupted turn)."""
        for tool_call_id in list(self._buffers):
            await self._flush(tool_call_id)

    async def _delayed_flush(self, tool_call_id: str) -> None:
        """Timer coroutine: wait the coalescing window, then flush.

        No-op if the buffer was already drained (count trigger, turn
        teardown, or `ToolCallEnd`) before the timer fired. Swallows
        `CancelledError` from the synchronous-flush path."""
        try:
            await asyncio.sleep(FLUSH_INTERVAL_S)
        except asyncio.CancelledError:
            return
        buf = self._buffers.get(tool_call_id)
        if buf is not None:
            # Clear the handle before flushing so a chunk that arrives
            # mid-flush is free to arm a fresh timer.
            buf.flush_task = None
            await self._flush(tool_call_id)

    async def _flush(self, tool_call_id: str) -> None:
        """Pop the buffer for `tool_call_id` and write its joined
        chunks in a single `append_tool_output` call.

        No-op if no buffer exists or it's empty. Safe to call any
        number of times; each call is a single UPDATE + commit."""
        buf = self._buffers.pop(tool_call_id, None)
        if buf is None or not buf.chunks:
            return
        if buf.flush_task is not None:
            # Defensive: the caller is expected to clear/cancel, but
            # covering both paths keeps the contract simple.
            buf.flush_task.cancel()
            buf.flush_task = None
        payload = "".join(buf.chunks)
        try:
            await store.append_tool_output(self.db, tool_call_id=tool_call_id, chunk=payload)
        except Exception:
            # Mirror the pre-coalescing behavior: a DB hiccup on a
            # streamed delta shouldn't kill the turn. `finish_tool_call`
            # will still land the canonical output on `ToolCallEnd`.
            log.exception(
                "session %s: failed to flush tool output for %s",
                self.session_id,
                tool_call_id,
            )
