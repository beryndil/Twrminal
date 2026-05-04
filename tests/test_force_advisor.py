# mypy: disable-error-code=explicit-any
"""Tests for G9 — ``/advisor`` per-turn override.

Coverage:

* :class:`bearings.agent.runner.QueuedPrompt` carries ``force_advisor``
  (default ``False``; toggleable).
* :meth:`bearings.agent.runner.SessionRunner.enqueue_prompt` threads
  ``force_advisor`` through to the queued item.
* ``POST /api/sessions/{id}/prompt`` with ``force_advisor=true`` in the
  body surfaces as ``QueuedPrompt.force_advisor=True`` on the runner.
* ``POST`` without the flag leaves ``force_advisor=False``.
* The SDK loop prepends
  :data:`bearings.config.constants.FORCE_ADVISOR_INSTRUCTION` to the
  content it sends to ``client.query`` when ``force_advisor=True`` AND
  the session's routing decision has an advisor model configured.
* When ``force_advisor=True`` but the session has no advisor model, the
  content is sent unchanged (graceful degradation).
* ``force_advisor=False`` leaves content unchanged regardless of whether
  an advisor model is configured.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite
import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from fastapi.testclient import TestClient

from bearings.agent.bearings_mcp import CloseSessionDeps, build_bearings_mcp_server
from bearings.agent.options import compose_session_options
from bearings.agent.routing import RoutingDecision
from bearings.agent.runner import QueuedPrompt, SessionRunner
from bearings.agent.sdk_loop import run_session_loop
from bearings.agent.session import AgentSession, SessionConfig
from bearings.config.constants import FORCE_ADVISOR_INSTRUCTION, SESSION_KIND_CHAT
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app

# ---------------------------------------------------------------------------
# Infrastructure — fakes shared across test groups
# ---------------------------------------------------------------------------


class _FakeSDKClient:
    """Drop-in for ``ClaudeSDKClient`` that records ``query`` calls."""

    instances: ClassVar[list[_FakeSDKClient]] = []

    def __init__(self, *, options: Any) -> None:
        self.options = options
        self.queries: list[tuple[str, str]] = []
        self._turns: list[list[Any]] = []
        _FakeSDKClient.instances.append(self)

    def queue_turn(self, messages: list[Any]) -> None:
        self._turns.append(messages)

    async def __aenter__(self) -> _FakeSDKClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        pass

    async def query(self, prompt: str, session_id: str = "") -> None:
        self.queries.append((prompt, session_id))

    async def receive_response(self) -> AsyncIterator[Any]:
        if not self._turns:
            return
        for msg in self._turns.pop(0):
            yield msg


def _decision_with_advisor() -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model="opus",
        advisor_max_uses=5,
        effort_level="auto",
        source="default",
        reason="test",
        matched_rule_id=None,
    )


def _decision_no_advisor() -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="auto",
        source="default",
        reason="test",
        matched_rule_id=None,
    )


def _build_session(
    conn: aiosqlite.Connection, session_id: str, decision: RoutingDecision
) -> AgentSession:
    config = SessionConfig(
        session_id=session_id,
        working_dir="/tmp/wd",
        decision=decision,
        db=conn,
    )
    return AgentSession(config)


def _make_options(decision: RoutingDecision, server: Any) -> Any:
    return compose_session_options(
        decision=decision,
        session_instructions=None,
        working_dir="/tmp/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=server,
    )


def _result_msg(session_id: str) -> ResultMessage:
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


def _assistant_msg(session_id: str, text: str, uuid: str) -> AssistantMessage:
    """Construct a fully-specified :class:`AssistantMessage` for tests."""
    return AssistantMessage(
        content=[TextBlock(text=text)],
        model="claude-sonnet",
        message_id=f"msg_{uuid}",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        stop_reason="end_turn",
        session_id=session_id,
        uuid=uuid,
    )


def _unused_factory() -> Any:
    async def _f(session_id: str) -> SessionRunner:  # pragma: no cover
        raise NotImplementedError

    return _f


@pytest.fixture
async def conn(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    db_path = tmp_path / "fa_test.db"
    connection = await aiosqlite.connect(db_path)
    try:
        await load_schema(connection)
        yield connection
    finally:
        await connection.close()


@pytest.fixture(autouse=True)
def _reset_fakes() -> None:
    _FakeSDKClient.instances = []


# ---------------------------------------------------------------------------
# Unit tests — QueuedPrompt and SessionRunner.enqueue_prompt
# ---------------------------------------------------------------------------


def test_queued_prompt_defaults_force_advisor_false() -> None:
    """``force_advisor`` is ``False`` by default so callers that do not
    set it do not trigger the advisor override."""
    qp = QueuedPrompt(message_id="msg_1", content="hello")
    assert qp.force_advisor is False


def test_queued_prompt_force_advisor_true() -> None:
    """``force_advisor=True`` is preserved on the frozen dataclass."""
    qp = QueuedPrompt(message_id="msg_1", content="hello", force_advisor=True)
    assert qp.force_advisor is True


def test_enqueue_prompt_threads_force_advisor() -> None:
    """``enqueue_prompt(force_advisor=True)`` stores the flag in the
    queued item; the default is ``False``."""
    runner = SessionRunner("ses_test_fa")
    runner.enqueue_prompt(message_id="msg_a", content="no override")
    runner.enqueue_prompt(message_id="msg_b", content="with override", force_advisor=True)
    p1 = runner.pop_next_prompt()
    p2 = runner.pop_next_prompt()
    assert p1 is not None and p1.force_advisor is False
    assert p2 is not None and p2.force_advisor is True


# ---------------------------------------------------------------------------
# HTTP endpoint tests — force_advisor flows from POST body to runner queue
# ---------------------------------------------------------------------------


async def test_post_without_force_advisor_queues_false(conn: aiosqlite.Connection) -> None:
    """A plain POST with only ``content`` leaves ``force_advisor=False``
    on the queued prompt — normal routing, no advisor injection."""
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    captured: list[QueuedPrompt] = []

    async def _factory(session_id: str) -> SessionRunner:
        runner = SessionRunner(session_id)
        original = runner.enqueue_prompt

        def _capture(**kwargs: Any) -> None:
            original(**kwargs)
            item = runner.peek_next_prompt()
            if item is not None:
                captured.append(item)

        runner.enqueue_prompt = _capture  # type: ignore[method-assign]
        return runner

    app = create_app(db_connection=conn, runner_factory=_factory)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/prompt",
            json={"content": "hello"},
        )
    assert resp.status_code == 202
    assert len(captured) == 1
    assert captured[0].force_advisor is False


async def test_post_with_force_advisor_true_queues_true(conn: aiosqlite.Connection) -> None:
    """A POST with ``force_advisor=true`` sets the flag on the queued
    prompt — that turn's routing will inject the advisor instruction."""
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    captured: list[QueuedPrompt] = []

    async def _factory(session_id: str) -> SessionRunner:
        runner = SessionRunner(session_id)
        original = runner.enqueue_prompt

        def _capture(**kwargs: Any) -> None:
            original(**kwargs)
            item = runner.peek_next_prompt()
            if item is not None:
                captured.append(item)

        runner.enqueue_prompt = _capture  # type: ignore[method-assign]
        return runner

    app = create_app(db_connection=conn, runner_factory=_factory)
    with TestClient(app) as client:
        resp = client.post(
            f"/api/sessions/{session.id}/prompt",
            json={"content": "use advisor please", "force_advisor": True},
        )
    assert resp.status_code == 202
    assert len(captured) == 1
    assert captured[0].force_advisor is True


# ---------------------------------------------------------------------------
# SDK loop tests — force_advisor modifies query content
# ---------------------------------------------------------------------------


async def _run_one_turn_with_client(
    runner: SessionRunner,
    agent: AgentSession,
    opts: Any,
    turn_messages: list[Any],
    client_cls: type[_FakeSDKClient],
) -> _FakeSDKClient:
    """Run the SDK loop until the fake client has received at least one
    ``query`` call, then cancel the loop.

    Returns the fake client instance so the caller can inspect
    ``client.queries``.
    """

    class _ScriptingClient(client_cls):  # type: ignore[valid-type, misc]
        async def __aenter__(self) -> _ScriptingClient:
            await super().__aenter__()
            # Pre-load the turn so ``receive_response`` has something to yield.
            self.queue_turn(turn_messages)
            return self

    task = asyncio.create_task(
        run_session_loop(runner, agent, opts, client_factory=_ScriptingClient)
    )
    # Yield up to 50 x 10 ms = 500 ms for the turn to complete.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if _FakeSDKClient.instances and _FakeSDKClient.instances[-1].queries:
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert _FakeSDKClient.instances, "FakeSDKClient was never constructed"
    return _FakeSDKClient.instances[-1]


async def test_sdk_loop_prepends_instruction_when_advisor_configured(
    conn: aiosqlite.Connection,
) -> None:
    """When ``force_advisor=True`` and the session has ``advisor_model``
    configured, the SDK loop prepends
    :data:`FORCE_ADVISOR_INSTRUCTION` to the content passed to
    ``client.query``."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )
    decision = _decision_with_advisor()
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id, decision)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )
    opts = _make_options(decision, server)

    user_content = "think carefully about this"
    runner.enqueue_prompt(message_id="msg_u1", content=user_content, force_advisor=True)

    turn = [
        _assistant_msg(session_row.id, "I used the advisor.", "u-a"),
        _result_msg(session_row.id),
    ]
    client = await _run_one_turn_with_client(runner, agent, opts, turn, _FakeSDKClient)

    assert client.queries, "client.query was never called"
    sent_content = client.queries[0][0]
    assert sent_content.startswith(FORCE_ADVISOR_INSTRUCTION), (
        f"Expected FORCE_ADVISOR_INSTRUCTION prefix; got: {sent_content!r}"
    )
    assert user_content in sent_content, (
        f"Original user content missing from sent content: {sent_content!r}"
    )


async def test_sdk_loop_no_prefix_when_no_advisor(conn: aiosqlite.Connection) -> None:
    """When ``force_advisor=True`` but the session has no advisor model,
    the content is sent unchanged (graceful degradation)."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )
    decision = _decision_no_advisor()
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id, decision)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )
    opts = _make_options(decision, server)

    user_content = "normal message"
    runner.enqueue_prompt(message_id="msg_u2", content=user_content, force_advisor=True)

    turn = [
        _assistant_msg(session_row.id, "ok", "u-b"),
        _result_msg(session_row.id),
    ]
    client = await _run_one_turn_with_client(runner, agent, opts, turn, _FakeSDKClient)

    assert client.queries, "client.query was never called"
    sent_content = client.queries[0][0]
    assert sent_content == user_content, (
        f"Content should be unchanged without advisor model; got: {sent_content!r}"
    )


async def test_sdk_loop_no_prefix_when_flag_false(conn: aiosqlite.Connection) -> None:
    """When ``force_advisor=False`` (the default), the content is sent
    unchanged regardless of whether the session has an advisor configured."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )
    decision = _decision_with_advisor()
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id, decision)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )
    opts = _make_options(decision, server)

    user_content = "no advisor needed"
    runner.enqueue_prompt(message_id="msg_u3", content=user_content, force_advisor=False)

    turn = [
        _assistant_msg(session_row.id, "ok", "u-c"),
        _result_msg(session_row.id),
    ]
    client = await _run_one_turn_with_client(runner, agent, opts, turn, _FakeSDKClient)

    assert client.queries, "client.query was never called"
    sent_content = client.queries[0][0]
    assert sent_content == user_content, (
        f"Content should be unchanged with force_advisor=False; got: {sent_content!r}"
    )
