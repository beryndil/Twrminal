"""End-to-end integration tests for item 1.9 message persistence.

Exercises :func:`bearings.agent.persistence.persist_assistant_turn`
against a real :class:`aiosqlite.Connection` + the full schema, then
reads the row back through :func:`bearings.db.messages.get` /
:func:`bearings.db.messages.list_for_session` to assert every spec
§5 routing/usage column round-tripped without loss.

Also verifies the data-flow continuity contract from item 1.7 +
1.8 + 1.9: the same :class:`bearings.agent.routing.RoutingDecision`
that the assembler computes (item 1.7 + 1.8 swap-in) is the one
the persistence layer writes (this item) — no field is dropped.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.persistence import persist_assistant_turn
from bearings.agent.routing import RoutingDecision
from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema


@pytest.fixture
async def conn(tmp_path: Path):
    db_path = tmp_path / "persist.db"
    async with aiosqlite.connect(db_path) as connection:
        await load_schema(connection)
        yield connection


async def _new_session(conn: aiosqlite.Connection) -> str:
    s = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/wd",
        model="sonnet",
    )
    return s.id


def _decision(
    *,
    matched_rule_id: int | None = 42,
    source: str = "system_rule",
) -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model="opus",
        advisor_max_uses=5,
        effort_level="auto",
        source=source,
        reason="Workhorse default",
        matched_rule_id=matched_rule_id,
    )


async def test_persist_writes_every_spec_5_column(
    conn: aiosqlite.Connection,
) -> None:
    sid = await _new_session(conn)
    decision = _decision()
    model_usage = {
        "claude-sonnet-4-6": {
            "inputTokens": 1500,
            "outputTokens": 400,
            "cacheReadInputTokens": 2000,
        },
        "claude-opus-4-6": {
            "inputTokens": 80,
            "outputTokens": 30,
            "cacheReadInputTokens": 10,
        },
    }
    msg = await persist_assistant_turn(
        conn,
        session_id=sid,
        content="here is my answer",
        decision=decision,
        model_usage=model_usage,
    )
    # Round-trip via the read path the messages API uses.
    fetched = await messages_db.get(conn, msg.id)
    assert fetched is not None
    assert fetched.role == "assistant"
    assert fetched.content == "here is my answer"
    # Routing-decision columns
    assert fetched.executor_model == "sonnet"
    assert fetched.advisor_model == "opus"
    assert fetched.effort_level == "auto"
    assert fetched.routing_source == "system_rule"
    assert fetched.routing_reason == "Workhorse default"
    assert fetched.matched_rule_id == 42
    # Per-model usage columns
    assert fetched.executor_input_tokens == 1500
    assert fetched.executor_output_tokens == 400
    assert fetched.advisor_input_tokens == 80
    assert fetched.advisor_output_tokens == 30
    assert fetched.advisor_calls_count == 1
    assert fetched.cache_read_tokens == 2010


async def test_persist_bumps_session_message_count(
    conn: aiosqlite.Connection,
) -> None:
    sid = await _new_session(conn)
    before = await sessions_db.get(conn, sid)
    assert before is not None and before.message_count == 0
    await persist_assistant_turn(
        conn,
        session_id=sid,
        content="hi",
        decision=_decision(),
        model_usage=None,
    )
    after = await sessions_db.get(conn, sid)
    assert after is not None and after.message_count == 1


async def test_persist_with_no_model_usage_writes_zero_token_columns(
    conn: aiosqlite.Connection,
) -> None:
    """A turn with ``model_usage=None`` (synthetic / replayed) writes
    zero-valued token columns (not NULL) per item 1.9 contract —
    NULL is reserved for legacy backfill carriers."""
    sid = await _new_session(conn)
    msg = await persist_assistant_turn(
        conn,
        session_id=sid,
        content="ok",
        decision=_decision(matched_rule_id=None, source="default"),
        model_usage=None,
    )
    fetched = await messages_db.get(conn, msg.id)
    assert fetched is not None
    assert fetched.executor_input_tokens == 0
    assert fetched.executor_output_tokens == 0
    assert fetched.advisor_input_tokens == 0
    assert fetched.advisor_output_tokens == 0
    assert fetched.advisor_calls_count == 0
    assert fetched.cache_read_tokens == 0


async def test_persist_no_advisor_decision_records_null_advisor_model(
    conn: aiosqlite.Connection,
) -> None:
    """Opus-solo decision (advisor_model=None) writes NULL on
    advisor_model and zero on advisor token columns."""
    sid = await _new_session(conn)
    decision = RoutingDecision(
        executor_model="opus",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="xhigh",
        source="system_rule",
        reason="Hard architectural reasoning — Opus solo with extended thinking",
        matched_rule_id=10,
    )
    msg = await persist_assistant_turn(
        conn,
        session_id=sid,
        content="think hard",
        decision=decision,
        model_usage={
            "claude-opus-4-7": {
                "inputTokens": 5000,
                "outputTokens": 800,
                "cacheReadInputTokens": 100,
            },
        },
    )
    fetched = await messages_db.get(conn, msg.id)
    assert fetched is not None
    assert fetched.executor_model == "opus"
    assert fetched.advisor_model is None
    assert fetched.executor_input_tokens == 5000
    assert fetched.advisor_input_tokens == 0
    assert fetched.advisor_calls_count == 0


async def test_persist_increments_session_total_cost_usd(
    conn: aiosqlite.Connection,
) -> None:
    """Each turn's ``ResultMessage.total_cost_usd`` accumulates onto the
    session row.

    Regression: ``sessions.total_cost_usd`` was initialised to ``0.0`` in
    :func:`bearings.db.sessions.create` and no codepath ever UPDATEd it,
    so the UI's "Total cost (USD)" surface displayed ``$0.00`` for every
    session indefinitely. This test pins the rollup.
    """
    sid = await _new_session(conn)
    before = await sessions_db.get(conn, sid)
    assert before is not None and before.total_cost_usd == 0.0
    # First turn: $0.05 billed.
    await persist_assistant_turn(
        conn,
        session_id=sid,
        content="first",
        decision=_decision(),
        model_usage=None,
        total_cost_usd=0.05,
    )
    mid = await sessions_db.get(conn, sid)
    assert mid is not None and mid.total_cost_usd == pytest.approx(0.05)
    # Second turn: $0.07 billed; rollup must accumulate, not replace.
    await persist_assistant_turn(
        conn,
        session_id=sid,
        content="second",
        decision=_decision(),
        model_usage=None,
        total_cost_usd=0.07,
    )
    after = await sessions_db.get(conn, sid)
    assert after is not None and after.total_cost_usd == pytest.approx(0.12)


async def test_persist_skips_total_cost_update_for_none_or_zero(
    conn: aiosqlite.Connection,
) -> None:
    """``total_cost_usd=None`` (default / cache-only turn) and ``0.0`` are
    no-ops for the session-row rollup so the column stays monotonic."""
    sid = await _new_session(conn)
    # default kwarg = None
    await persist_assistant_turn(
        conn,
        session_id=sid,
        content="cache hit",
        decision=_decision(),
        model_usage=None,
    )
    after_none = await sessions_db.get(conn, sid)
    assert after_none is not None and after_none.total_cost_usd == 0.0
    # explicit 0.0
    await persist_assistant_turn(
        conn,
        session_id=sid,
        content="zero billed",
        decision=_decision(),
        model_usage=None,
        total_cost_usd=0.0,
    )
    after_zero = await sessions_db.get(conn, sid)
    assert after_zero is not None and after_zero.total_cost_usd == 0.0


async def test_persist_appears_in_list_for_session(
    conn: aiosqlite.Connection,
) -> None:
    """The persisted assistant row interleaves with user rows in
    chronological order — confirms ``list_for_session`` reads back
    every column."""
    sid = await _new_session(conn)
    user = await messages_db.insert_user(conn, session_id=sid, content="hello")
    assistant = await persist_assistant_turn(
        conn,
        session_id=sid,
        content="hi back",
        decision=_decision(),
        model_usage=None,
    )
    rows = await messages_db.list_for_session(conn, sid)
    assert [row.id for row in rows] == [user.id, assistant.id]
    assert rows[0].role == "user"
    assert rows[1].role == "assistant"
    assert rows[1].matched_rule_id == 42
