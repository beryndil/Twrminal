"""Tests for the WS Origin check (2026-04-21 security audit §1).

Both `/ws/sessions/{id}` (per-session agent stream) and `/ws/sessions`
(sessions-list broadcast) share the same cross-origin guard: browsers
always send `Origin` on a WS handshake, so a missing or non-allowlisted
value is evidence the request came from a tab the user didn't intend
to grant the agent. Rejection closes with 4403 before any subscription
is registered.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bearings.api.auth import _allowed_origins, check_ws_origin
from bearings.config import ServerCfg, Settings, StorageCfg
from bearings.server import create_app


@pytest.fixture
def origin_settings(tmp_path) -> Iterator[Settings]:
    """Settings with an empty `allowed_origins` list so we can control
    exactly which origins the test server accepts. Using the
    conftest-wide `TEST_ORIGIN` defaults would mask the rejection
    path."""
    cfg = Settings(
        server=ServerCfg(allowed_origins=["http://allowed.test"]),
        storage=StorageCfg(db_path=tmp_path / "db.sqlite"),
    )
    cfg.config_file = tmp_path / "config.toml"
    yield cfg


@pytest.fixture
def origin_app(origin_settings: Settings) -> FastAPI:
    return create_app(origin_settings)


@pytest.fixture
def origin_client(origin_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(origin_app) as c:
        yield c


def _create_session(c: TestClient, origin: str = "http://allowed.test") -> str:
    """Create a session for WS tests. HTTP routes don't care about
    Origin (only WS does), but we pass it for consistency with how a
    real browser would behave."""
    headers = {"origin": origin}
    tag = c.post("/api/tags", json={"name": "default"}, headers=headers).json()
    resp = c.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "m",
            "title": None,
            "tag_ids": [tag["id"]],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def test_agent_ws_rejects_missing_origin(origin_client: TestClient) -> None:
    sid = _create_session(origin_client)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with origin_client.websocket_connect(
            f"/ws/sessions/{sid}",
            headers={},  # explicit empty → httpx drops default origin
        ) as ws:
            ws.receive_text()
    assert excinfo.value.code == 4403


def test_agent_ws_rejects_foreign_origin(origin_client: TestClient) -> None:
    sid = _create_session(origin_client)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with origin_client.websocket_connect(
            f"/ws/sessions/{sid}",
            headers={"origin": "http://evil.example"},
        ) as ws:
            ws.receive_text()
    assert excinfo.value.code == 4403


def test_agent_ws_accepts_allowlisted_origin(origin_client: TestClient) -> None:
    """Happy path — the configured allowlist entry opens the socket.
    Connection is closed without sending a prompt, so we only verify
    the handshake succeeded (no 4403)."""
    sid = _create_session(origin_client)
    with origin_client.websocket_connect(
        f"/ws/sessions/{sid}",
        headers={"origin": "http://allowed.test"},
    ) as ws:
        # First frame on every connection is the runner_status snapshot;
        # receiving it proves the socket was accepted.
        frame = ws.receive_json()
        assert frame["type"] == "runner_status"


def test_sessions_ws_rejects_foreign_origin(origin_client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with origin_client.websocket_connect(
            "/ws/sessions",
            headers={"origin": "http://evil.example"},
        ) as ws:
            ws.receive_text()
    assert excinfo.value.code == 4403


def test_sessions_ws_rejects_missing_origin(origin_client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with origin_client.websocket_connect(
            "/ws/sessions",
            headers={},
        ) as ws:
            ws.receive_text()
    assert excinfo.value.code == 4403


def test_allowlist_includes_loopback_defaults(origin_client: TestClient) -> None:
    """The loopback defaults (`127.0.0.1`, `localhost`, `[::1]` on the
    configured port) are always present alongside user-supplied entries
    so the user never loses access to their own UI by forgetting to
    list it explicitly."""
    settings: Settings = origin_client.app.state.settings  # type: ignore[attr-defined]

    class _StubWS:
        def __init__(self, app) -> None:
            class _State:
                pass

            s = _State()
            s.settings = settings
            self.app = type("A", (), {"state": s})()

    origins = _allowed_origins(_StubWS(origin_client.app))  # type: ignore[arg-type]
    port = settings.server.port
    assert f"http://127.0.0.1:{port}" in origins
    assert f"http://localhost:{port}" in origins
    assert f"http://[::1]:{port}" in origins
    # User-supplied entry is merged, not shadowed.
    assert "http://allowed.test" in origins


def test_check_ws_origin_fails_closed_on_missing_header() -> None:
    """Unit-level coverage of the helper: no `Origin` header means no
    access, even if the server has a populated allowlist."""
    settings = Settings(server=ServerCfg(allowed_origins=["http://anything"]))

    class _StubHeaders:
        def get(self, key: str, default: object | None = None) -> object | None:
            return default

    class _StubWS:
        def __init__(self) -> None:
            self.headers = _StubHeaders()

            class _State:
                pass

            s = _State()
            s.settings = settings
            self.app = type("A", (), {"state": s})()

    assert check_ws_origin(_StubWS()) is False  # type: ignore[arg-type]
