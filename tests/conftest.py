from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.agent.events import (
    AgentEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    Token,
    ToolCallEnd,
    ToolCallStart,
)
from bearings.agent.session import AgentSession
from bearings.config import Settings, StorageCfg
from bearings.server import create_app

MOCK_MSG_ID = "mock-msg"
MOCK_TOOL_MSG_ID = "mock-tool-msg"


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Iterator[Settings]:
    cfg = Settings(
        storage=StorageCfg(db_path=tmp_path / "db.sqlite"),
    )
    cfg.config_file = tmp_path / "config.toml"
    yield cfg


@pytest.fixture
def app(tmp_settings: Settings) -> FastAPI:
    return create_app(tmp_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:  # context triggers lifespan (init_db → app.state.db)
        yield c


@pytest.fixture
def mock_agent_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AgentSession, prompt: str) -> AsyncIterator[AgentEvent]:
        yield MessageStart(session_id=self.session_id, message_id=MOCK_MSG_ID)
        yield Token(session_id=self.session_id, text="hello ")
        yield Token(session_id=self.session_id, text="world")
        yield MessageComplete(session_id=self.session_id, message_id=MOCK_MSG_ID)

    monkeypatch.setattr("bearings.agent.session.AgentSession.stream", fake)


@pytest.fixture
def mock_agent_tool_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AgentSession, prompt: str) -> AsyncIterator[AgentEvent]:
        yield MessageStart(session_id=self.session_id, message_id=MOCK_TOOL_MSG_ID)
        yield ToolCallStart(
            session_id=self.session_id,
            tool_call_id="tool-1",
            name="Read",
            input={"path": "/etc/hosts"},
        )
        yield ToolCallEnd(
            session_id=self.session_id,
            tool_call_id="tool-1",
            ok=True,
            output="127.0.0.1 localhost",
            error=None,
        )
        yield MessageComplete(session_id=self.session_id, message_id=MOCK_TOOL_MSG_ID)

    monkeypatch.setattr("bearings.agent.session.AgentSession.stream", fake)


@pytest.fixture
def mock_agent_thinking_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AgentSession, prompt: str) -> AsyncIterator[AgentEvent]:
        yield MessageStart(session_id=self.session_id, message_id=MOCK_MSG_ID)
        yield Thinking(session_id=self.session_id, text="first I consider...")
        yield Thinking(session_id=self.session_id, text=" then I decide.")
        yield Token(session_id=self.session_id, text="answer")
        yield MessageComplete(session_id=self.session_id, message_id=MOCK_MSG_ID)

    monkeypatch.setattr("bearings.agent.session.AgentSession.stream", fake)


@pytest.fixture
def mock_agent_long_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Emits many tokens with `asyncio.sleep(0)` between yields so the
    event loop can surface a queued stop frame. Without a stop, would
    eventually emit MessageComplete; with a stop, the server breaks
    out early and synthesises one itself."""

    import asyncio

    async def fake(self: AgentSession, prompt: str) -> AsyncIterator[AgentEvent]:
        yield MessageStart(session_id=self.session_id, message_id=MOCK_MSG_ID)
        for i in range(200):
            yield Token(session_id=self.session_id, text=f"t{i} ")
            # Enough slack for the reader task to actually receive any
            # queued stop frame. asyncio.sleep(0) alone doesn't give
            # Starlette's WS transport a chance to deliver.
            await asyncio.sleep(0.005)
        yield MessageComplete(session_id=self.session_id, message_id=MOCK_MSG_ID)

    monkeypatch.setattr("bearings.agent.session.AgentSession.stream", fake)


@pytest.fixture
def mock_agent_cost_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    # `claude-agent-sdk`'s ResultMessage.total_cost_usd is cumulative
    # across a resumed CLI session, so simulate that: each turn reports
    # the running total, not the per-turn delta. The runner converts
    # this back to a delta before persisting/emitting.
    cumulative = {"usd": 0.0}

    async def fake(self: AgentSession, prompt: str) -> AsyncIterator[AgentEvent]:
        # Fresh id per turn so a session can run multiple turns without
        # colliding on messages.id (UNIQUE).
        msg_id = uuid4().hex
        yield MessageStart(session_id=self.session_id, message_id=msg_id)
        yield Token(session_id=self.session_id, text="billed")
        cumulative["usd"] += 0.01
        yield MessageComplete(
            session_id=self.session_id,
            message_id=msg_id,
            cost_usd=cumulative["usd"],
        )

    monkeypatch.setattr("bearings.agent.session.AgentSession.stream", fake)
