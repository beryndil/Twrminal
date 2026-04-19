from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from twrminal.config import AuthCfg, Settings, StorageCfg
from twrminal.server import create_app


@pytest.fixture
def auth_settings(tmp_path) -> Iterator[Settings]:
    cfg = Settings(
        storage=StorageCfg(db_path=tmp_path / "db.sqlite"),
        auth=AuthCfg(enabled=True, token="s3cret"),
    )
    cfg.config_file = tmp_path / "config.toml"
    yield cfg


@pytest.fixture
def auth_app(auth_settings: Settings) -> FastAPI:
    return create_app(auth_settings)


@pytest.fixture
def auth_client(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as c:
        yield c


def test_health_reports_required_when_enabled(auth_client: TestClient) -> None:
    body = auth_client.get("/api/health").json()
    assert body["auth"] == "required"


def test_health_reports_disabled_when_off(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["auth"] == "disabled"


def test_sessions_requires_bearer_when_enabled(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/sessions")
    assert resp.status_code == 401
    resp = auth_client.get(
        "/api/sessions",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401
    resp = auth_client.get(
        "/api/sessions",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert resp.status_code == 200


def test_history_export_also_gated(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/history/export")
    assert resp.status_code == 401
    resp = auth_client.get(
        "/api/history/export",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert resp.status_code == 200


def test_health_and_metrics_stay_open_under_auth(auth_client: TestClient) -> None:
    # No bearer needed.
    assert auth_client.get("/api/health").status_code == 200
    assert auth_client.get("/metrics").status_code == 200


def test_ws_missing_token_closes_4401(auth_client: TestClient) -> None:
    # Can't create a session without a token, so use the DB directly via
    # the Bearer path just to get a valid session id.
    tag = auth_client.post(
        "/api/tags",
        json={"name": "default"},
        headers={"Authorization": "Bearer s3cret"},
    ).json()
    sid = auth_client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "m",
            "title": None,
            "tag_ids": [tag["id"]],
        },
        headers={"Authorization": "Bearer s3cret"},
    ).json()["id"]

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with auth_client.websocket_connect(f"/ws/sessions/{sid}") as ws:
            ws.receive_text()
    assert excinfo.value.code == 4401


def test_ws_bad_token_closes_4401(auth_client: TestClient) -> None:
    tag = auth_client.post(
        "/api/tags",
        json={"name": "default"},
        headers={"Authorization": "Bearer s3cret"},
    ).json()
    sid = auth_client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "m",
            "title": None,
            "tag_ids": [tag["id"]],
        },
        headers={"Authorization": "Bearer s3cret"},
    ).json()["id"]

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with auth_client.websocket_connect(f"/ws/sessions/{sid}?token=wrong") as ws:
            ws.receive_text()
    assert excinfo.value.code == 4401


def test_ws_good_token_accepts_and_streams(
    auth_client: TestClient, mock_agent_stream: None
) -> None:
    tag = auth_client.post(
        "/api/tags",
        json={"name": "default"},
        headers={"Authorization": "Bearer s3cret"},
    ).json()
    sid = auth_client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "m",
            "title": None,
            "tag_ids": [tag["id"]],
        },
        headers={"Authorization": "Bearer s3cret"},
    ).json()["id"]

    with auth_client.websocket_connect(f"/ws/sessions/{sid}?token=s3cret") as ws:
        ws.send_json({"type": "prompt", "content": "hi"})
        frames = [json.loads(ws.receive_text()) for _ in range(4)]
    assert [f["type"] for f in frames] == [
        "message_start",
        "token",
        "token",
        "message_complete",
    ]


def test_enabled_without_token_returns_500(tmp_path) -> None:
    cfg = Settings(
        storage=StorageCfg(db_path=tmp_path / "db.sqlite"),
        auth=AuthCfg(enabled=True, token=None),
    )
    cfg.config_file = tmp_path / "config.toml"
    with TestClient(create_app(cfg)) as c:
        resp = c.get("/api/sessions")
        assert resp.status_code == 500
        assert "token is empty" in resp.json()["detail"]
