"""Server-wide pubsub for session-list events.

A single `SessionsBroker` lives at `app.state.sessions_broker` for the
FastAPI app's lifetime. Subscribers (the `/ws/sessions` handler) attach
via `subscribe()`; mutation paths (session CRUD routes + runner state
transitions) call `publish()` to fan events out. Frontend tabs get
sub-second sidebar updates without the Phase-1 `/api/sessions`
reconcile tick handling every change.

Event shapes sent on the wire:
- `{kind: "upsert", session: SessionOut}` — any state change on an
  existing session OR a newly-created session. Frontend upserts by id.
- `{kind: "delete", session_id: str}` — session was deleted.
- `{kind: "runner_state", session_id: str, is_running: bool}` — the
  in-flight-turn badge for the sidebar.

Subscriber queues are bounded (`SUBSCRIBER_QUEUE_MAX`) — a consumer that
can't keep up gets dropped rather than back-pressuring the publisher.
A dropped client's next reconnect runs one `softRefresh` to reconcile,
so the data loss is transient and bounded.

Publish is synchronous (put_nowait). It's safe to call from a DB
mutation path without awaiting, which means no mutation can stall on a
slow subscriber. This is the same discipline the per-session runner
uses for its subscriber queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiosqlite

log = logging.getLogger(__name__)

# Cap per subscriber to protect publishers from a backed-up consumer.
# A steady-state tab sees O(10) events/second at most (one turn start +
# one turn end + periodic updates); 500 covers ~a minute of burst
# before the slow client gets evicted. Dropped clients softRefresh on
# reconnect so this is a recoverable failure, not data loss.
SUBSCRIBER_QUEUE_MAX = 500


class SessionsBroker:
    """In-process pubsub for session-list events. Fans each published
    frame to every current subscriber. Publish is sync and non-blocking;
    subscribe / unsubscribe manage the queue set."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Return a new bounded queue registered as a subscriber. The
        caller is responsible for calling `unsubscribe()` in a finally
        block when it's done reading."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove `queue` from the subscriber set. No-op if it's already
        been evicted (slow-consumer drop) or was never registered."""
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        """Fan `event` to every subscriber with `put_nowait`. A full
        queue (slow subscriber) means the subscriber is dropped — its
        next reconnect's softRefresh reconciles."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning(
                    "sessions_broker: dropping slow subscriber (%d queued)",
                    queue.qsize(),
                )
                self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        """Observable size of the subscriber set. Exposed for tests and
        for the metrics endpoint to surface "sidebars currently
        connected"."""
        return len(self._subscribers)


async def publish_session_upsert(
    broker: SessionsBroker | None,
    conn: aiosqlite.Connection,
    session_id: str,
) -> None:
    """Fetch the current session row and broadcast it as an upsert. If
    the row is gone by the time we look (racy delete), emits a
    `delete` instead so subscribers converge. No-op when `broker` is
    `None` — keeps the hook cheap to call from tests that don't wire
    a broker.

    Import of `SessionOut` is deferred to call time to avoid a cycle
    between the agent and api packages at module import.
    """
    if broker is None:
        return
    # Local imports keep this module free of a hard dependency on the
    # api layer — the broker itself is pure pubsub.
    from bearings.api.models import SessionOut
    from bearings.db import store

    row = await store.get_session(conn, session_id)
    if row is None:
        broker.publish({"kind": "delete", "session_id": session_id})
        return
    dto = SessionOut(**row).model_dump(mode="json")
    broker.publish({"kind": "upsert", "session": dto})


def publish_session_delete(
    broker: SessionsBroker | None,
    session_id: str,
) -> None:
    """Fire a `delete` frame without fetching the row. Used when the
    caller already knows the row is gone (DELETE handler) and a fetch
    would just re-confirm it."""
    if broker is None:
        return
    broker.publish({"kind": "delete", "session_id": session_id})


def publish_runner_state(
    broker: SessionsBroker | None,
    session_id: str,
    *,
    is_running: bool,
) -> None:
    """Announce a runner state transition (idle ↔ running). The sidebar
    uses this to update the green "currently running" ping without
    waiting on the Phase-1 running poll."""
    if broker is None:
        return
    broker.publish({"kind": "runner_state", "session_id": session_id, "is_running": is_running})
