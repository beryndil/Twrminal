"""Tests for SessionsBroker — the server-wide sessions-list pubsub.

Covers the three invariants the broker is responsible for:

1. Fan-out — a single publish reaches every subscriber.
2. Slow-subscriber discipline — a subscriber whose queue fills up is
   dropped rather than back-pressuring the publisher.
3. Helper publishers — `publish_session_upsert`, `publish_session_delete`,
   `publish_runner_state` produce well-formed frames and short-circuit
   cleanly when the broker is `None` (the tests-without-broker path).
"""

from __future__ import annotations

import asyncio

import pytest

from bearings.agent import sessions_broker as sb
from bearings.db import store
from bearings.db._common import init_db


@pytest.mark.asyncio
async def test_publish_fans_out_to_every_subscriber() -> None:
    broker = sb.SessionsBroker()
    a = broker.subscribe()
    b = broker.subscribe()
    c = broker.subscribe()

    event = {"kind": "runner_state", "session_id": "s1", "is_running": True}
    broker.publish(event)

    assert a.get_nowait() == event
    assert b.get_nowait() == event
    assert c.get_nowait() == event


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_fanout() -> None:
    broker = sb.SessionsBroker()
    kept = broker.subscribe()
    gone = broker.subscribe()
    broker.unsubscribe(gone)

    broker.publish({"kind": "delete", "session_id": "s1"})

    assert kept.qsize() == 1
    assert gone.qsize() == 0


@pytest.mark.asyncio
async def test_subscriber_count_tracks_live_set() -> None:
    broker = sb.SessionsBroker()
    assert broker.subscriber_count == 0
    q1 = broker.subscribe()
    q2 = broker.subscribe()
    assert broker.subscriber_count == 2
    broker.unsubscribe(q1)
    assert broker.subscriber_count == 1
    broker.unsubscribe(q2)
    assert broker.subscriber_count == 0


@pytest.mark.asyncio
async def test_slow_subscriber_is_dropped_when_queue_fills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscriber whose queue is full during publish gets evicted so
    the publisher never blocks. Shrink SUBSCRIBER_QUEUE_MAX to keep the
    test cheap — the production cap (500) makes filling a queue slow."""
    monkeypatch.setattr(sb, "SUBSCRIBER_QUEUE_MAX", 2)
    broker = sb.SessionsBroker()
    fast = broker.subscribe()
    slow = broker.subscribe()

    # Publish three events, draining `fast` between each so it stays
    # below its cap. `slow` never drains, so it saturates at 2 items
    # and the third publish evicts it.
    broker.publish({"kind": "delete", "session_id": "s1"})
    fast.get_nowait()
    broker.publish({"kind": "delete", "session_id": "s2"})
    fast.get_nowait()
    assert slow.qsize() == 2
    assert broker.subscriber_count == 2

    # Third publish: `slow` overflows and is evicted; `fast` keeps
    # receiving events as normal.
    broker.publish({"kind": "delete", "session_id": "s3"})

    assert broker.subscriber_count == 1
    assert fast.qsize() == 1
    # The dropped queue retains whatever it held at eviction time —
    # production code won't read from it because it's out of the set.
    assert slow.qsize() == 2


@pytest.mark.asyncio
async def test_publish_none_helpers_are_noops_without_broker() -> None:
    """The helper publishers short-circuit on `broker is None` so
    tests and partial wirings can skip the broker without crashing."""
    # No assertion beyond "doesn't raise" — the explicit None branch.
    await sb.publish_session_upsert(None, conn=None, session_id="x")  # type: ignore[arg-type]
    sb.publish_session_delete(None, session_id="x")
    sb.publish_runner_state(None, "x", is_running=True)


@pytest.mark.asyncio
async def test_publish_session_upsert_emits_upsert_for_live_row(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = await init_db(tmp_path / "broker_upsert.sqlite")
    try:
        created = await store.create_session(
            conn,
            working_dir=str(tmp_path),
            model="test-model",
            title="Hello",
        )
        broker = sb.SessionsBroker()
        queue = broker.subscribe()

        await sb.publish_session_upsert(broker, conn, created["id"])

        event = queue.get_nowait()
        assert event["kind"] == "upsert"
        assert event["session"]["id"] == created["id"]
        assert event["session"]["title"] == "Hello"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_publish_session_upsert_emits_delete_for_missing_row(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Racy path: caller asked for an upsert but the row was deleted
    between the trigger and the fetch. Converge subscribers by emitting
    a `delete` instead of silently dropping the event."""
    conn = await init_db(tmp_path / "broker_racy.sqlite")
    try:
        broker = sb.SessionsBroker()
        queue = broker.subscribe()

        await sb.publish_session_upsert(broker, conn, "does-not-exist")

        event = queue.get_nowait()
        assert event == {"kind": "delete", "session_id": "does-not-exist"}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_publish_session_delete_shape() -> None:
    broker = sb.SessionsBroker()
    queue = broker.subscribe()

    sb.publish_session_delete(broker, "abc")

    assert queue.get_nowait() == {"kind": "delete", "session_id": "abc"}


@pytest.mark.asyncio
async def test_publish_runner_state_shape() -> None:
    broker = sb.SessionsBroker()
    queue = broker.subscribe()

    sb.publish_runner_state(broker, "abc", is_running=True)
    sb.publish_runner_state(broker, "abc", is_running=False)

    assert queue.get_nowait() == {
        "kind": "runner_state",
        "session_id": "abc",
        "is_running": True,
        "is_awaiting_user": False,
    }
    assert queue.get_nowait() == {
        "kind": "runner_state",
        "session_id": "abc",
        "is_running": False,
        "is_awaiting_user": False,
    }


@pytest.mark.asyncio
async def test_publish_runner_state_carries_awaiting_user() -> None:
    """Frame carries the `is_awaiting_user` axis when the runner is
    parked on a `can_use_tool` decision. Mirrors the `is_running` pair
    above so the full state space (running/awaiting cross-product) has
    an explicit wire-shape assertion."""
    broker = sb.SessionsBroker()
    queue = broker.subscribe()

    sb.publish_runner_state(broker, "abc", is_running=True, is_awaiting_user=True)

    assert queue.get_nowait() == {
        "kind": "runner_state",
        "session_id": "abc",
        "is_running": True,
        "is_awaiting_user": True,
    }


@pytest.mark.asyncio
async def test_queue_is_bounded_to_configured_max() -> None:
    broker = sb.SessionsBroker()
    q = broker.subscribe()
    assert q.maxsize == sb.SUBSCRIBER_QUEUE_MAX


@pytest.mark.asyncio
async def test_publish_does_not_stall_on_full_subscriber() -> None:
    """Regression: `put_nowait` + exception path must not leak into a
    `put` that blocks the publisher. The publisher returns promptly
    even when every subscriber is saturated."""

    async def _publish_under_deadline() -> None:
        # Shrink to 1 for fast saturation.
        orig = sb.SUBSCRIBER_QUEUE_MAX
        sb.SUBSCRIBER_QUEUE_MAX = 1
        try:
            broker = sb.SessionsBroker()
            broker.subscribe()
            broker.publish({"kind": "delete", "session_id": "s1"})
            # Second publish should drop the subscriber, not block.
            broker.publish({"kind": "delete", "session_id": "s2"})
        finally:
            sb.SUBSCRIBER_QUEUE_MAX = orig

    await asyncio.wait_for(_publish_under_deadline(), timeout=1.0)
