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
from bearings.config import FsCfg, ServerCfg, Settings, StorageCfg, UploadsCfg, VaultCfg
from bearings.server import create_app

# TestClient's default base_url is `http://testserver`; WS tests run
# under that hostname, so we whitelist it in test settings and have the
# client fixture send a matching Origin header by default. Individual
# tests can still probe the origin check by overriding the header on
# `websocket_connect`.
TEST_ORIGIN = "http://testserver"

MOCK_MSG_ID = "mock-msg"
MOCK_TOOL_MSG_ID = "mock-tool-msg"


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Iterator[Settings]:
    cfg = Settings(
        server=ServerCfg(allowed_origins=[TEST_ORIGIN]),
        storage=StorageCfg(db_path=tmp_path / "db.sqlite"),
        # Redirect uploads at the tmp dir so routes_uploads tests don't
        # scribble into `~/.local/share/bearings/uploads`. Isolated
        # subdir keeps it clean-cut from the sqlite files.
        uploads=UploadsCfg(upload_dir=tmp_path / "uploads"),
        # `/api/fs/list` is clamped to `fs.allow_root` (default `$HOME`).
        # Tests operate inside `tmp_path`; point the allow-root there so
        # existing fs-route tests don't trip the clamp. Tests that
        # exercise the clamp itself (rejection, root, etc.) build their
        # own Settings.
        fs=FsCfg(allow_root=tmp_path),
        # Vault defaults point at `~/.claude/plans` and `~/Projects`,
        # which would leak the developer's real filesystem into the
        # test run. Pin both to empty under `tmp_path` so vault tests
        # populate their own fixture files and tests that don't touch
        # the vault see an empty index.
        vault=VaultCfg(
            plan_roots=[tmp_path / "plans"],
            todo_globs=[str(tmp_path / "todos" / "**" / "TODO.md")],
        ),
    )
    cfg.config_file = tmp_path / "config.toml"
    yield cfg


@pytest.fixture
def app(tmp_settings: Settings) -> FastAPI:
    return create_app(tmp_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:  # context triggers lifespan (init_db → app.state.db)
        # WS handshake needs an allowlisted Origin. Setting it on the
        # httpx-backed TestClient propagates to every request,
        # including websocket_connect — individual tests can still
        # override via `headers=` on the call.
        c.headers["origin"] = TEST_ORIGIN
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

    async def fake(self: AgentSession, prompt: str) -> AsyncIterator[AgentEvent]:
        # Fresh id per turn so a session can run multiple turns without
        # colliding on messages.id (UNIQUE).
        msg_id = uuid4().hex
        yield MessageStart(session_id=self.session_id, message_id=msg_id)
        yield Token(session_id=self.session_id, text="billed")
        yield MessageComplete(
            session_id=self.session_id,
            message_id=msg_id,
            cost_usd=0.01,
        )

    monkeypatch.setattr("bearings.agent.session.AgentSession.stream", fake)
