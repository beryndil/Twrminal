"""Turn-driver factory for the autonomous checklist driver.

Per ``docs/architecture-v1.md`` §1.1.4 + §3.2: this module provides
the production :data:`TurnDriver` callback injected into
:func:`bearings.agent.auto_driver_runtime.build_runtime`. It lives in
the ``agent/`` layer (no FastAPI imports) and bridges the
:class:`bearings.agent.runner.SessionRunner` event stream with the
:class:`bearings.agent.auto_driver.Driver`'s per-turn prompt contract.

Responsibility: given a runner and a prompt string, persist the user
message, enqueue on the runner, subscribe to the runner's event stream,
and drain events until :class:`bearings.agent.events.MessageComplete`
(success — return the assistant body text) or
:class:`bearings.agent.events.ErrorEvent` with ``fatal=True`` (raise
``RuntimeError``). Unsubscribes in a ``finally`` block so task
cancellation cannot leak the subscriber reference.

The ``TurnDriver`` type alias is defined in
:mod:`bearings.agent.auto_driver_runtime`:
``Callable[[SessionRunner, str], Awaitable[str]]``.

Why subscribe *after* snapshot + *before* enqueue is wrong:
Subscribing before the enqueue risks replaying prior events still in
the ring buffer (since_seq=last_seq snapshots the buffer position at
call time, so only events with higher seq are replayed). Enqueue
happens after subscribe so the ``new_prompt_event`` fires *after* the
subscriber is registered — the worker loop picks up the prompt and
emits events that land in the queue.

Actually the correct order is: snapshot ``last_seq``, then persist +
enqueue, then subscribe with ``since_seq=snapshot``. This guarantees:
1. ``since_seq`` is from before the enqueue, so any events the worker
   emits for *this* turn have seq > snapshot.
2. The subscribe call happens after enqueue so the snapshot is stable
   (no events are emitted between snapshot and subscribe that would
   fall through the crack).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import aiosqlite

from bearings.agent.events import ErrorEvent, MessageComplete
from bearings.agent.runner import SessionRunner
from bearings.db import messages as messages_db

_LOG = logging.getLogger(__name__)


async def _run_turn(
    db: aiosqlite.Connection,
    runner: SessionRunner,
    prompt: str,
) -> str:
    """Run one prompt turn on ``runner``; return the assistant body text.

    Steps:

    1. Snapshot ``runner.last_seq`` — the subscribe call uses this as
       ``since_seq`` so only events emitted *after* the enqueue are
       visible to the drain loop (no stale ring-buffer replays).
    2. Persist the user-role message row so the leg's conversation is
       durable before the runner dequeues the prompt.
    3. Enqueue the prompt on the runner (sets ``new_prompt_event``).
    4. Subscribe with ``since_seq=snapshot``. The returned replay list
       covers events emitted between snapshot and subscribe — unlikely
       for a driver leg (the runner is idle) but checked first for
       correctness.
    5. Drain the queue: ``MessageComplete`` → return ``event.content``;
       ``ErrorEvent(fatal=True)`` → raise; all other events continue.
    6. Unsubscribe in a ``finally`` so task cancellation cannot leak
       the subscriber reference.

    Raises:
        RuntimeError: When the runner emits a fatal ``ErrorEvent``
            before ``MessageComplete`` arrives.
    """
    session_id = runner.session_id
    since_seq = runner.last_seq

    msg = await messages_db.insert_user(
        db,
        session_id=session_id,
        content=prompt,
    )
    runner.enqueue_prompt(message_id=msg.id, content=prompt)

    replay, queue = runner.subscribe(since_seq=since_seq)

    # Check replay snapshot first (rare but correct).
    for _seq, event in replay:
        if isinstance(event, MessageComplete):
            runner.unsubscribe(queue)
            return event.content
        if isinstance(event, ErrorEvent) and event.fatal:
            runner.unsubscribe(queue)
            raise RuntimeError(
                f"auto_driver turn_driver: fatal agent error on {session_id!r}: {event.message}"
            )

    try:
        while True:
            seq, event = await queue.get()
            _LOG.debug(
                "turn_driver drain: session=%s seq=%d type=%s",
                session_id,
                seq,
                event.type,
            )
            if isinstance(event, MessageComplete):
                return event.content
            if isinstance(event, ErrorEvent) and event.fatal:
                raise RuntimeError(
                    f"auto_driver turn_driver: fatal agent error on {session_id!r}: {event.message}"
                )
    finally:
        runner.unsubscribe(queue)


def build_turn_driver(
    *,
    db_connection: aiosqlite.Connection,
) -> Callable[[SessionRunner, str], Awaitable[str]]:
    """Return a :data:`TurnDriver` closure bound to ``db_connection``.

    The returned callable satisfies
    ``Callable[[SessionRunner, str], Awaitable[str]]`` — the type the
    :func:`bearings.agent.auto_driver_runtime.build_runtime` factory
    expects. Typed as :class:`object` here to avoid importing
    ``TurnDriver`` (which lives in ``auto_driver_runtime``) and
    creating a circular import; the concrete type is enforced at the
    ``build_runtime`` call site.

    Args:
        db_connection: Long-lived ``aiosqlite.Connection`` shared with
            the rest of the app. The closure captures it so each
            ``turn_driver(runner, prompt)`` call persists the user
            message without needing the connection threaded through the
            ``DriverRuntime`` Protocol.
    """

    async def _turn_driver(runner: SessionRunner, prompt: str) -> str:
        return await _run_turn(db_connection, runner, prompt)

    return _turn_driver


__all__ = ["build_turn_driver"]
