"""Subscriber fan-out + ring-buffer append for `SessionRunner`.

`emit_event` is the canonical "land this event on every subscriber AND
remember it for replay" path. `emit_ephemeral` is the same fan-out
without the ring-buffer append, used for `ToolProgress` keepalives that
are worthless on reconnect (a fresh client's own clock takes over on
the next live tick).

Free functions taking a `SessionRunner` rather than methods on the
class so `runner.py` stays focused on coordination and lifecycle.
Single-task ownership (the runner's worker) means no locking around
the subscribers set or the seq counter.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bearings import metrics
from bearings.agent.events import AgentEvent
from bearings.agent.runner_types import SUBSCRIBER_QUEUE_MAX, _Envelope

if TYPE_CHECKING:
    from bearings.agent.runner import SessionRunner

log = logging.getLogger(__name__)


async def emit_event(runner: SessionRunner, event: AgentEvent) -> None:
    """Fan an event out to every subscriber and append to the ring
    buffer. Subscriber queues are bounded by `SUBSCRIBER_QUEUE_MAX` —
    a stalled subscriber that fills its queue is evicted (its WS
    handler notices the dead queue on its next send and tears down the
    socket). The reconnecting client replays from the runner's ring
    buffer using its last `seq`. Broken queues from dead subscribers
    are also swept on the next emit."""
    payload = event.model_dump()
    env = _Envelope(runner._next_seq, payload)
    runner._next_seq += 1
    runner._event_log.append(env)
    metrics.ws_events_sent.labels(type=event.type).inc()
    _deliver(runner, env, ephemeral=False)


async def emit_ephemeral(runner: SessionRunner, event: AgentEvent) -> None:
    """Fan an event out to live subscribers WITHOUT appending to the
    ring buffer.

    Used for keepalives (`ToolProgress`) that need to arrive at
    connected clients in real time but have no value on replay — a
    reconnecting client's own clock takes over on the next live tick,
    and skipping the ring buffer prevents a long turn from chewing
    through the 5000-entry replay window with throwaway ticks. Seq
    advances so `_seq` stays monotonic for currently-connected
    clients; the skipped seqs simply aren't deliverable on future
    reconnects, which is what makes the event ephemeral."""
    payload = event.model_dump()
    env = _Envelope(runner._next_seq, payload)
    runner._next_seq += 1
    metrics.ws_events_sent.labels(type=event.type).inc()
    _deliver(runner, env, ephemeral=True)


def _deliver(runner: SessionRunner, env: _Envelope, *, ephemeral: bool) -> None:
    """Push an envelope onto every subscriber queue, evicting any that
    are full or otherwise misbehaving. Shared between durable and
    ephemeral fan-out so the eviction policy stays in one place."""
    label = "ephemeral" if ephemeral else "event"
    for queue in list(runner._subscribers):
        try:
            queue.put_nowait(env)
        except asyncio.QueueFull:
            # Subscriber's WS sender has fallen behind by
            # SUBSCRIBER_QUEUE_MAX events. Evict rather than block the
            # runner; the client will reconnect and replay from `seq`
            # against the ring buffer.
            log.warning(
                "runner %s: evicting subscriber on %s — queue full at %d events",
                runner.session_id,
                label,
                SUBSCRIBER_QUEUE_MAX,
            )
            runner._subscribers.discard(queue)
        except Exception:
            # Defensive: any other queue misbehavior also evicts.
            log.exception(
                "runner %s: subscriber put_nowait (%s) failed; evicting",
                runner.session_id,
                label,
            )
            runner._subscribers.discard(queue)
