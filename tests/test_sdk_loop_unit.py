# mypy: disable-error-code=explicit-any
"""Unit tests for ``bearings.agent.sdk_loop.run_session_loop``.

Per Slice A1 of ``~/.claude/plans/wiring-agent-loop.md``: the worker
loop is the SDK-binding layer; tests use a fake SDK client (same
async-cm + query + receive_response surface as
:class:`claude_agent_sdk.ClaudeSDKClient`) to drive end-to-end turns
without spawning the SDK subprocess.

Coverage:

* Happy-path single-turn end-to-end (UserMessage + MessageStart +
  Token deltas + MessageComplete + assistant row persisted).
* Multi-prompt FIFO ordering (two prompts queued before the loop
  starts; both run in arrival order).
* Idle wait — loop blocks on ``new_prompt_event`` between turns.
* Cancellation — supervisor cancellation tears down cleanly without
  marking the session ERROR.
* Error path — an SDK exception transitions the session to ERROR
  and emits a fatal ErrorEvent.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    Message,
    ResultMessage,
    StreamEvent,
    TextBlock,
)

from bearings.agent.bearings_mcp import (
    CloseSessionDeps,
    build_bearings_mcp_server,
)
from bearings.agent.events import (
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Token,
    UserMessage,
)
from bearings.agent.options import compose_session_options
from bearings.agent.routing import RoutingDecision
from bearings.agent.runner import SessionRunner
from bearings.agent.sdk_loop import run_session_loop
from bearings.agent.session import (
    AgentSession,
    SessionConfig,
    SessionState,
)
from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.db.messages import Message as DbMessage

# ---------------------------------------------------------------------------
# Test infrastructure — a fake SDK client + persistence sink
# ---------------------------------------------------------------------------


class FakeSDKClient:
    """Drop-in replacement for ``ClaudeSDKClient`` exposing the same
    async-cm + query + receive_response surface.

    Constructed per-session (matching the real SDK lifecycle). The
    test queues a per-turn message script via :meth:`queue_turn` —
    each call to ``query()`` consumes the next script and
    ``receive_response()`` yields its messages in order.
    """

    instances: ClassVar[list[FakeSDKClient]] = []

    def __init__(self, *, options: Any) -> None:
        self.options = options
        self.turns: list[list[Message]] = []
        self.queries: list[tuple[str, str]] = []
        self.entered = False
        self.exited = False
        FakeSDKClient.instances.append(self)

    def queue_turn(self, messages: list[Message]) -> None:
        self.turns.append(messages)

    async def __aenter__(self) -> FakeSDKClient:
        self.entered = True
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.exited = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.queries.append((prompt, session_id))

    async def receive_response(self) -> AsyncIterator[Message]:
        if not self.turns:
            return
        messages = self.turns.pop(0)
        for msg in messages:
            yield msg


def _decision() -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="medium",
        source="default",
        reason="test",
        matched_rule_id=None,
    )


def _options(server: Any) -> Any:
    return compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/tmp/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=server,
    )


def _build_session(conn: aiosqlite.Connection, session_id: str) -> AgentSession:
    config = SessionConfig(
        session_id=session_id,
        working_dir="/tmp/wd",
        decision=_decision(),
        db=conn,
    )
    return AgentSession(config)


def _result_msg(session_id: str = "ses_t") -> ResultMessage:
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


@pytest.fixture
async def conn(tmp_path: Path):
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await load_schema(connection)
        yield connection


@pytest.fixture(autouse=True)
def _reset_fake_clients() -> None:
    FakeSDKClient.instances = []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_single_turn_runs_end_to_end(conn: aiosqlite.Connection) -> None:
    """Enqueue one prompt; the loop runs one turn; we observe
    UserMessage + MessageStart + Token + MessageComplete on the
    runner's ring buffer."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp/wd", model="sonnet"
    )
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )
    opts = _options(server)
    runner.enqueue_prompt(message_id="msg_user_1", content="What is 2+2?")

    persisted: list[dict[str, Any]] = []

    async def fake_persist(
        connection: aiosqlite.Connection,
        *,
        session_id: str,
        content: str,
        decision: RoutingDecision,
        model_usage: Any,
        total_cost_usd: float | None = None,
    ) -> DbMessage:
        persisted.append({"session_id": session_id, "content": content, "model_usage": model_usage})
        return await sessions_db.get(connection, session_id)  # type: ignore[return-value]

    # Script the SDK turn: assistant text + result.
    def boot_script() -> None:
        client = FakeSDKClient.instances[-1]
        client.queue_turn(
            [
                StreamEvent(
                    uuid="u1",
                    session_id=session_row.id,
                    event={"type": "message_start", "message": {"id": "msg_assist_1"}},
                ),
                StreamEvent(
                    uuid="u2",
                    session_id=session_row.id,
                    event={
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "The answer is 4."},
                    },
                ),
                AssistantMessage(
                    content=[TextBlock(text="The answer is 4.")],
                    model="claude-sonnet",
                    message_id="msg_assist_1",
                    parent_tool_use_id=None,
                    error=None,
                    usage=None,
                    stop_reason="end_turn",
                    session_id=session_row.id,
                    uuid="u-a",
                ),
                _result_msg(session_row.id),
            ]
        )

    # Wrap FakeSDKClient so the script lands the moment the loop
    # constructs the client (after __aenter__ returns).
    class ScriptingClient(FakeSDKClient):
        async def __aenter__(self) -> ScriptingClient:
            await super().__aenter__()
            boot_script()
            return self

    task = asyncio.create_task(
        run_session_loop(runner, agent, opts, persist=fake_persist, client_factory=ScriptingClient)
    )
    # Yield repeatedly so the worker loop reaches its idle await.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if persisted:
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # Persistence happened with the canonical body.
    assert persisted == [
        {
            "session_id": session_row.id,
            "content": "The answer is 4.",
            "model_usage": None,
        }
    ]
    # Wire events: ring buffer carries UserMessage, MessageStart,
    # Token, MessageComplete in order.
    events = [event for _, event in runner._buffer]
    types_seen = [type(e) for e in events]
    assert UserMessage in types_seen
    assert MessageStart in types_seen
    assert Token in types_seen
    assert MessageComplete in types_seen


async def test_loop_starts_session_lifecycle(conn: aiosqlite.Connection) -> None:
    """``run_session_loop`` transitions INITIALIZING → RUNNING after
    ``__aenter__`` and attaches the SDK client."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )

    task = asyncio.create_task(
        run_session_loop(runner, agent, _options(server), client_factory=FakeSDKClient)
    )
    for _ in range(20):
        await asyncio.sleep(0.01)
        if agent.state is SessionState.RUNNING:
            break
    assert agent.state is SessionState.RUNNING
    assert agent.has_sdk_client is True
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # On teardown the client detaches.
    assert agent.has_sdk_client is False


async def test_idle_loop_waits_on_new_prompt_event(conn: aiosqlite.Connection) -> None:
    """With no prompts queued, the loop blocks on
    ``runner.new_prompt_event``."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )

    task = asyncio.create_task(
        run_session_loop(runner, agent, _options(server), client_factory=FakeSDKClient)
    )
    # Let the loop reach its idle await.
    for _ in range(20):
        await asyncio.sleep(0.01)
        if runner.status.is_awaiting_user:
            break
    # Status snapshot reports awaiting-user.
    assert runner.status.is_running is False
    assert runner.status.is_awaiting_user is True
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_cancellation_tears_down_without_error_state(
    conn: aiosqlite.Connection,
) -> None:
    """Supervisor-initiated cancellation does NOT transition the
    session to ERROR (per sign-off Q7 — ERROR is reserved for SDK
    fatal errors, not graceful shutdown)."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )

    task = asyncio.create_task(
        run_session_loop(runner, agent, _options(server), client_factory=FakeSDKClient)
    )
    for _ in range(10):
        await asyncio.sleep(0.01)
        if agent.state is SessionState.RUNNING:
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert agent.state is not SessionState.ERROR


async def test_error_path_marks_session_error_and_emits_event(
    conn: aiosqlite.Connection,
) -> None:
    """An exception raised by the SDK during a turn transitions the
    session to ERROR and emits a fatal ErrorEvent."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )
    runner.enqueue_prompt(message_id="msg_u", content="boom")

    class ExplodingClient(FakeSDKClient):
        async def query(self, prompt: str, session_id: str = "default") -> None:
            raise RuntimeError("simulated SDK transport hangup")

    await run_session_loop(runner, agent, _options(server), client_factory=ExplodingClient)

    assert agent.state is SessionState.ERROR
    error_events = [evt for _, evt in runner._buffer if isinstance(evt, ErrorEvent)]
    assert len(error_events) == 1
    assert error_events[0].fatal is True
    assert "simulated SDK transport hangup" in error_events[0].message


async def test_multi_prompt_fifo_runs_in_arrival_order(
    conn: aiosqlite.Connection,
) -> None:
    """Two prompts enqueued in order both run; the second only fires
    after the first turn's ResultMessage is processed."""
    session_row = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    runner = SessionRunner(session_row.id)
    agent = _build_session(conn, session_row.id)
    server = build_bearings_mcp_server(
        CloseSessionDeps(session_id=session_row.id, db_factory=_unused_factory())
    )
    runner.enqueue_prompt(message_id="msg_u1", content="first")
    runner.enqueue_prompt(message_id="msg_u2", content="second")

    persisted: list[str] = []

    async def fake_persist(
        connection: aiosqlite.Connection,
        *,
        session_id: str,
        content: str,
        decision: RoutingDecision,
        model_usage: Any,
        total_cost_usd: float | None = None,
    ) -> DbMessage:
        persisted.append(content)
        return await sessions_db.get(connection, session_id)  # type: ignore[return-value]

    next_id = [1]

    class ScriptingClient(FakeSDKClient):
        async def query(self, prompt: str, session_id: str = "default") -> None:
            await super().query(prompt, session_id)
            mid = f"msg_assist_{next_id[0]}"
            next_id[0] += 1
            self.queue_turn(
                [
                    AssistantMessage(
                        content=[TextBlock(text=f"reply to {prompt}")],
                        model="claude-sonnet",
                        message_id=mid,
                        parent_tool_use_id=None,
                        error=None,
                        usage=None,
                        stop_reason="end_turn",
                        session_id=session_id,
                        uuid=f"u-a-{mid}",
                    ),
                    _result_msg(session_id),
                ]
            )

    task = asyncio.create_task(
        run_session_loop(
            runner, agent, _options(server), persist=fake_persist, client_factory=ScriptingClient
        )
    )
    # Give the event loop generous scheduling slots; small real-time
    # naps cover the per-turn awaits + the inter-turn pop.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(persisted) >= 2:
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert persisted == ["reply to first", "reply to second"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unused_factory() -> Callable[[], Awaitable[aiosqlite.Connection]]:
    async def _never() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError("unit test should not invoke close_session DB factory")

    return _never
