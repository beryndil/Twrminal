from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from twrminal.agent.events import (
    AgentEvent,
    MessageComplete,
    MessageStart,
    Token,
    ToolCallEnd,
    ToolCallStart,
)
from twrminal.agent.session import AgentSession
from twrminal.config import Settings, StorageCfg
from twrminal.server import create_app

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

    monkeypatch.setattr("twrminal.agent.session.AgentSession.stream", fake)


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

    monkeypatch.setattr("twrminal.agent.session.AgentSession.stream", fake)
