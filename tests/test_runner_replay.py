"""Tests for runner-boot replay of orphaned user prompts.

When `bearings.service` is stopped (SIGTERM, crash, deploy) while a
turn is mid-flight, the SDK subprocess dies before emitting the
assistant reply. The user's message is already persisted; what's
missing is the follow-up. On next runner boot we want to resubmit
that prompt so the turn completes without user intervention — but we
must not loop if the replay itself also dies. These tests pin that
contract at two levels:

1. The store helpers (`find_replayable_prompt`, `mark_replay_attempted`)
   correctly identify orphan prompts and make the mark idempotent.
2. The `SessionRunner` worker, on first `start()`, consults the store
   and queues the orphan as its first turn, without duplicating the
   persisted user row and without replaying a second time on a second
   start.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.runner import SessionRunner
from bearings.db import store
from bearings.db._common import init_db
from tests.test_runner import ScriptedAgent, _message_script, _wait_until

# Match the shared db fixture shape from test_runner.py so this file
# stands alone — the fixture there is module-scoped to that file.


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await init_db(tmp_path / "replay.sqlite")
    await store.create_session(conn, working_dir="/tmp", model="m", title="t")
    yield conn
    await conn.close()


async def _session_id(conn: aiosqlite.Connection) -> str:
    rows = await store.list_sessions(conn)
    return rows[0]["id"]


# ---- store helpers -------------------------------------------------


@pytest.mark.asyncio
async def test_find_replayable_skips_when_no_messages(db: aiosqlite.Connection) -> None:
    """Empty session → nothing to replay. Rules out false positives
    for brand-new sessions whose user hasn't sent anything yet."""
    sid = await _session_id(db)
    assert await store.find_replayable_prompt(db, sid) is None


@pytest.mark.asyncio
async def test_find_replayable_returns_user_when_orphaned(
    db: aiosqlite.Connection,
) -> None:
    """Exact failure mode: a user row sits as the newest message with
    no assistant follower and no prior replay mark — must surface as
    replayable with its original content."""
    sid = await _session_id(db)
    row = await store.insert_message(db, session_id=sid, role="user", content="orphaned prompt")
    orphan = await store.find_replayable_prompt(db, sid)
    assert orphan is not None
    assert orphan["id"] == row["id"]
    assert orphan["content"] == "orphaned prompt"


@pytest.mark.asyncio
async def test_find_replayable_skips_when_assistant_follows(
    db: aiosqlite.Connection,
) -> None:
    """A completed turn (user then assistant) is not replayable — the
    newest row is the assistant reply, which decisively answers the
    user prompt that preceded it."""
    sid = await _session_id(db)
    await store.insert_message(db, session_id=sid, role="user", content="q")
    await store.insert_message(db, session_id=sid, role="assistant", content="a")
    assert await store.find_replayable_prompt(db, sid) is None


@pytest.mark.asyncio
async def test_find_replayable_skips_when_already_attempted(
    db: aiosqlite.Connection,
) -> None:
    """A previous boot already tried to replay this prompt. Whatever
    happened to that attempt (success, second crash, user navigated
    away), we don't retry — the mark is the fail-closed guard that
    prevents an infinite restart loop."""
    sid = await _session_id(db)
    row = await store.insert_message(db, session_id=sid, role="user", content="already tried")
    assert await store.mark_replay_attempted(db, row["id"]) is True
    assert await store.find_replayable_prompt(db, sid) is None


@pytest.mark.asyncio
async def test_find_replayable_skips_when_session_closed(
    db: aiosqlite.Connection,
) -> None:
    """Closed sessions express "the user is done with this thread" —
    even an unanswered prompt in a closed session should not spawn a
    surprise turn on the next server start."""
    sid = await _session_id(db)
    await store.insert_message(db, session_id=sid, role="user", content="q")
    await store.close_session(db, sid)
    assert await store.find_replayable_prompt(db, sid) is None


@pytest.mark.asyncio
async def test_mark_replay_attempted_is_idempotent(
    db: aiosqlite.Connection,
) -> None:
    """Second call on the same message is a no-op that returns False —
    callers treat False as "someone else beat me to it" and skip the
    replay, preserving single-fire semantics even across races."""
    sid = await _session_id(db)
    row = await store.insert_message(db, session_id=sid, role="user", content="q")
    assert await store.mark_replay_attempted(db, row["id"]) is True
    assert await store.mark_replay_attempted(db, row["id"]) is False


@pytest.mark.asyncio
async def test_mark_replay_attempted_unknown_message_returns_false(
    db: aiosqlite.Connection,
) -> None:
    """A bogus message id must not raise — it returns False so the
    caller logs and moves on. Guards against a stale replay attempt
    after a session / message deletion race."""
    assert await store.mark_replay_attempted(db, "not-a-real-id") is False


# ---- runner integration --------------------------------------------


@pytest.mark.asyncio
async def test_runner_replays_orphan_on_first_start(
    db: aiosqlite.Connection,
) -> None:
    """Integration: seed the DB with an orphaned user prompt, start the
    runner, and verify the worker's first turn is for that prompt —
    the assistant reply lands without any new user submission."""
    sid = await _session_id(db)
    await store.insert_message(db, session_id=sid, role="user", content="replayed ask")
    script = _message_script(sid, "msg-replayed", "answer-to-replay")
    agent = ScriptedAgent(sid, scripts=[script])
    runner = SessionRunner(sid, agent, db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        seen: list[str] = []
        while "message_complete" not in seen:
            env = await asyncio.wait_for(queue.get(), timeout=2.0)
            seen.append(env.payload["type"])
        # The turn_replayed event is the tell: a replay fired, not a
        # normal user-driven turn.
        assert "turn_replayed" in seen
        assert agent.prompts == ["replayed ask"]

        rows = await store.list_messages(db, sid)
        contents = [(r["role"], r["content"]) for r in rows]
        # Exactly one user row (original, not duplicated by replay) +
        # one assistant row (from the replayed turn).
        assert contents.count(("user", "replayed ask")) == 1
        assert ("assistant", "answer-to-replay") in contents
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_runner_does_not_replay_when_nothing_orphaned(
    db: aiosqlite.Connection,
) -> None:
    """Fresh session → no replay event, no spurious first turn. Keeps
    the replay invisible to users whose sessions closed cleanly."""
    sid = await _session_id(db)
    agent = ScriptedAgent(sid, scripts=[])
    runner = SessionRunner(sid, agent, db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        # Brief window for any spurious replay to have fired; none is
        # expected because there is no prior user message.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.1)
        assert agent.prompts == []
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_runner_does_not_replay_twice_across_restarts(
    db: aiosqlite.Connection,
) -> None:
    """Second runner over the same DB must NOT re-queue the same
    orphan. This is the loop-prevention contract: the first runner
    marked the prompt before enqueueing; the second runner sees the
    mark and stays quiet.

    We simulate the second-boot case by booting a runner, letting it
    process the replay, shutting it down, and starting a fresh runner
    on the same DB — the fresh runner's agent must receive no prompt.
    """
    sid = await _session_id(db)
    await store.insert_message(db, session_id=sid, role="user", content="one-shot")

    first_script = _message_script(sid, "first-msg", "first-answer")
    first_agent = ScriptedAgent(sid, scripts=[first_script])
    first_runner = SessionRunner(sid, first_agent, db)
    q1, _ = await first_runner.subscribe(0)
    first_runner.start()
    try:
        seen: list[str] = []
        while "message_complete" not in seen:
            env = await asyncio.wait_for(q1.get(), timeout=2.0)
            seen.append(env.payload["type"])
        assert first_agent.prompts == ["one-shot"]
    finally:
        await first_runner.shutdown()

    # Second runner, same DB — it should find no replayable prompt.
    second_agent = ScriptedAgent(sid, scripts=[])
    second_runner = SessionRunner(sid, second_agent, db)
    q2, _ = await second_runner.subscribe(0)
    second_runner.start()
    try:
        await _wait_until(lambda: second_runner._status == "idle")
        # A short window for any (unexpected) replay event.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q2.get(), timeout=0.1)
        assert second_agent.prompts == []
    finally:
        await second_runner.shutdown()


@pytest.mark.asyncio
async def test_runner_replay_does_not_duplicate_user_row(
    db: aiosqlite.Connection,
) -> None:
    """Specific regression guard: the replay path must set
    `persist_user=False` on `_execute_turn` so the orphan user row is
    not inserted a second time. A duplicate would confuse history and
    break reorg/dedup elsewhere."""
    sid = await _session_id(db)
    row = await store.insert_message(db, session_id=sid, role="user", content="replay-me")
    script = _message_script(sid, "msg-dup", "ok")
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[script]), db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        seen: list[str] = []
        while "message_complete" not in seen:
            env = await asyncio.wait_for(queue.get(), timeout=2.0)
            seen.append(env.payload["type"])
    finally:
        await runner.shutdown()

    rows = await store.list_messages(db, sid)
    user_rows = [r for r in rows if r["role"] == "user"]
    assert len(user_rows) == 1
    assert user_rows[0]["id"] == row["id"]


@pytest.mark.asyncio
async def test_runner_replay_emits_turn_replayed_event(
    db: aiosqlite.Connection,
) -> None:
    """The `turn_replayed` event must fire exactly once, naming the
    replayed message id. Subscribers that subscribed before the worker
    started see it via their live queue; a later-arriving subscriber
    sees it via `since_seq=0` replay from the ring buffer."""
    sid = await _session_id(db)
    row = await store.insert_message(db, session_id=sid, role="user", content="mark me")
    script = _message_script(sid, "msg-evt", "ok")
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[script]), db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        replay_events: list[dict[str, object]] = []
        seen: list[str] = []
        while "message_complete" not in seen:
            env = await asyncio.wait_for(queue.get(), timeout=2.0)
            seen.append(env.payload["type"])
            if env.payload["type"] == "turn_replayed":
                replay_events.append(env.payload)
        assert len(replay_events) == 1
        assert replay_events[0]["session_id"] == sid
        assert replay_events[0]["message_id"] == row["id"]
    finally:
        await runner.shutdown()
