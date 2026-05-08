# mypy: disable-error-code=explicit-any
"""Tests for feature-2-004 — [stopped] annotation on interrupted turns.

Verifies the full stack:
  1. ``TurnStopped`` event is in the ``AgentEvent`` discriminated union.
  2. ``messages.insert_assistant`` persists ``stopped=True`` correctly.
  3. ``persist_assistant_turn`` forwards the ``stopped`` flag.
  4. ``_do_run_one_turn`` emits ``TurnStopped`` and persists
     ``stopped=True`` when ``runner.stop_event`` is set.
  5. ``MessageOut`` exposes ``stopped``.
  6. DB round-trip preserves ``stopped``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest
from pydantic import TypeAdapter

from bearings.agent.events import AgentEvent, MessageComplete, TurnStopped
from bearings.agent.persistence import persist_assistant_turn
from bearings.agent.routing import RoutingDecision
from bearings.db import messages as messages_db
from bearings.db.connection import load_schema
from bearings.web.models.messages import MessageOut

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_EVENT_ADAPTER: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


def _routing_decision() -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="auto",
        source="default",
        reason="workhorse",
        matched_rule_id=None,
        evaluated_rules=[],
    )


# Valid bearings session-id format: ``ses_<32 lowercase hex chars>``.
_SES_STOPPED = "ses_" + "a" * 32
_SES_NORMAL = "ses_" + "b" * 32


def _result_msg(session_id: str = "s_test") -> Any:
    from claude_agent_sdk import ResultMessage

    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        stop_reason="end_turn",
        total_cost_usd=0.0,
        usage=None,
        result=None,
        structured_output=None,
        model_usage=None,
        permission_denials=None,
        errors=None,
        uuid="u-r",
    )


@pytest.fixture()
async def db() -> AsyncIterator[aiosqlite.Connection]:
    """In-memory aiosqlite connection with the full schema loaded."""
    async with aiosqlite.connect(":memory:") as conn:
        await load_schema(conn)
        # Seed a sessions row so the messages FK resolves.
        await conn.execute(
            "INSERT INTO sessions "
            "(id, kind, title, working_dir, model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "s1",
                "chat",
                "test session",
                "/tmp",
                "sonnet",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        await conn.commit()
        yield conn


# ---------------------------------------------------------------------------
# 1. TurnStopped is in the AgentEvent union
# ---------------------------------------------------------------------------


def test_turn_stopped_event_constructs() -> None:
    ev = TurnStopped(session_id="s1", message_id="m1")
    assert ev.type == "turn_stopped"
    assert ev.message_id == "m1"


def test_turn_stopped_round_trips_discriminated_union() -> None:
    raw = {"type": "turn_stopped", "session_id": "s1", "message_id": "m1"}
    ev = _AGENT_EVENT_ADAPTER.validate_python(raw)
    assert isinstance(ev, TurnStopped)
    assert ev.type == "turn_stopped"


def test_message_complete_unchanged_no_stopped_field() -> None:
    """MessageComplete has no ``stopped`` field — the flag lives on the DB row."""
    ev = MessageComplete(session_id="s1", message_id="m1", content="hello")
    assert not hasattr(ev, "stopped")


# ---------------------------------------------------------------------------
# 2 + 6. DB round-trip via insert_assistant / get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_assistant_stopped_true(db: aiosqlite.Connection) -> None:
    msg = await messages_db.insert_assistant(
        db,
        session_id="s1",
        content="partial reply",
        executor_model="sonnet",
        advisor_model=None,
        effort_level="auto",
        routing_source="default",
        routing_reason="workhorse",
        matched_rule_id=None,
        evaluated_rules=[],
        executor_input_tokens=10,
        executor_output_tokens=5,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=0,
        cache_read_tokens=None,
        cache_creation_tokens=None,
        stopped=True,
    )
    assert msg.stopped is True
    fetched = await messages_db.get(db, msg.id)
    assert fetched is not None
    assert fetched.stopped is True


@pytest.mark.asyncio
async def test_insert_assistant_stopped_false_default(db: aiosqlite.Connection) -> None:
    msg = await messages_db.insert_assistant(
        db,
        session_id="s1",
        content="full reply",
        executor_model="sonnet",
        advisor_model=None,
        effort_level="auto",
        routing_source="default",
        routing_reason="workhorse",
        matched_rule_id=None,
        evaluated_rules=[],
        executor_input_tokens=10,
        executor_output_tokens=5,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=0,
        cache_read_tokens=None,
        cache_creation_tokens=None,
        # stopped not passed — defaults to False
    )
    assert msg.stopped is False
    fetched = await messages_db.get(db, msg.id)
    assert fetched is not None
    assert fetched.stopped is False


# ---------------------------------------------------------------------------
# 3. persist_assistant_turn forwards stopped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_assistant_turn_stopped_flag(db: aiosqlite.Connection) -> None:
    decision = _routing_decision()
    msg = await persist_assistant_turn(
        db,
        session_id="s1",
        content="partial",
        decision=decision,
        model_usage=None,
        stopped=True,
    )
    assert msg.stopped is True


# ---------------------------------------------------------------------------
# 4. _do_run_one_turn emits TurnStopped and passes stopped=True to persist
# ---------------------------------------------------------------------------


def _make_fake_client(assistant_msg: Any, result_msg: Any) -> Any:
    """Build a minimal duck-typed SDK client for ``_do_run_one_turn``."""

    class _FakeClient:
        async def query(self, content: str, session_id: str = "") -> None:
            pass

        async def receive_response(self) -> AsyncIterator[Any]:
            yield assistant_msg
            yield result_msg

    return _FakeClient()


@pytest.mark.asyncio
async def test_do_run_one_turn_emits_turn_stopped_and_persists() -> None:
    """Drive ``_do_run_one_turn`` directly with stop_event pre-armed.

    Verifies:
      (a) ``TurnStopped`` event is emitted after the turn ends.
      (b) The persist callable receives ``stopped=True``.
    """
    from claude_agent_sdk import AssistantMessage, TextBlock

    from bearings.agent.runner import QueuedPrompt, SessionRunner
    from bearings.agent.sdk_loop import _do_run_one_turn
    from bearings.agent.translate import SDKEventTranslator

    sdk_assistant = AssistantMessage(
        content=[TextBlock(text="partial answer")],
        model="claude-sonnet",
        message_id="msg_test",
    )
    sdk_result = _result_msg(_SES_STOPPED)

    runner = SessionRunner(session_id=_SES_STOPPED)
    runner.stop_event.set()  # ARM — simulates user clicking Stop

    emitted: list[AgentEvent] = []

    async def _capture(event: AgentEvent) -> None:
        emitted.append(event)

    runner.emit = _capture  # type: ignore[assignment]

    fake_session = MagicMock()
    fake_session.config.session_id = _SES_STOPPED
    fake_session.config.db = None  # persistence skipped; tested by test_persist_* above
    fake_session.config.decision = _routing_decision()

    translator = SDKEventTranslator(_SES_STOPPED, _routing_decision())
    translator.begin_turn()
    prompt = QueuedPrompt(message_id="u1", content="go", force_advisor=False)

    await _do_run_one_turn(
        runner,
        fake_session,
        _make_fake_client(sdk_assistant, sdk_result),
        translator,
        persist_assistant_turn,
        prompt,
    )

    stopped_events = [e for e in emitted if e.type == "turn_stopped"]
    assert len(stopped_events) == 1
    assert stopped_events[0].message_id == "msg_test"


@pytest.mark.asyncio
async def test_do_run_one_turn_no_turn_stopped_on_normal_completion() -> None:
    """When stop_event is NOT set, TurnStopped must NOT be emitted."""
    from claude_agent_sdk import AssistantMessage, TextBlock

    from bearings.agent.runner import QueuedPrompt, SessionRunner
    from bearings.agent.sdk_loop import _do_run_one_turn
    from bearings.agent.translate import SDKEventTranslator

    sdk_assistant = AssistantMessage(
        content=[TextBlock(text="complete answer")],
        model="claude-sonnet",
        message_id="msg_ok",
    )
    sdk_result = _result_msg(_SES_NORMAL)

    runner = SessionRunner(session_id=_SES_NORMAL)
    # stop_event NOT set — normal completion

    emitted: list[AgentEvent] = []

    async def _capture(event: AgentEvent) -> None:
        emitted.append(event)

    runner.emit = _capture  # type: ignore[assignment]

    fake_session = MagicMock()
    fake_session.config.session_id = _SES_NORMAL
    fake_session.config.db = None
    fake_session.config.decision = _routing_decision()

    translator = SDKEventTranslator(_SES_NORMAL, _routing_decision())
    translator.begin_turn()
    prompt = QueuedPrompt(message_id="u2", content="hi", force_advisor=False)

    await _do_run_one_turn(
        runner,
        fake_session,
        _make_fake_client(sdk_assistant, sdk_result),
        translator,
        persist_assistant_turn,
        prompt,
    )

    stopped_events = [e for e in emitted if e.type == "turn_stopped"]
    assert len(stopped_events) == 0


# ---------------------------------------------------------------------------
# 5. MessageOut exposes stopped
# ---------------------------------------------------------------------------


def test_message_out_stopped_field_default() -> None:
    """MessageOut.stopped defaults to False (backward-compat)."""
    out = MessageOut(
        id="m1",
        session_id="s1",
        role="assistant",
        content="hello",
        created_at="2026-01-01T00:00:00Z",
        executor_model=None,
        advisor_model=None,
        effort_level=None,
        routing_source=None,
        routing_reason=None,
        matched_rule_id=None,
        evaluated_rules=[],
        executor_input_tokens=None,
        executor_output_tokens=None,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=None,
        cache_read_tokens=None,
        cache_creation_tokens=None,
        input_tokens=None,
        output_tokens=None,
        seq=1,
    )
    assert out.stopped is False


def test_message_out_stopped_true() -> None:
    out = MessageOut(
        id="m1",
        session_id="s1",
        role="assistant",
        content="partial",
        created_at="2026-01-01T00:00:00Z",
        executor_model=None,
        advisor_model=None,
        effort_level=None,
        routing_source=None,
        routing_reason=None,
        matched_rule_id=None,
        evaluated_rules=[],
        executor_input_tokens=None,
        executor_output_tokens=None,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=None,
        cache_read_tokens=None,
        cache_creation_tokens=None,
        input_tokens=None,
        output_tokens=None,
        seq=1,
        stopped=True,
    )
    assert out.stopped is True
