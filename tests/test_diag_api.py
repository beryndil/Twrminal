"""Integration tests for ``bearings.web.routes.diag`` (item 1.10)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "diag.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_diag_server_returns_version_pid_uptime(
    app_client: TestClient,
) -> None:
    response = app_client.get("/api/diag/server")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["version"], str) and body["version"]
    assert body["pid"] > 0
    assert body["uptime_s"] >= 0
    assert body["db_configured"] is True
    # billing_mode defaults to "payg" when not supplied to create_app.
    assert body["billing_mode"] == "payg"


def test_diag_server_db_configured_false_without_db() -> None:
    app = create_app(heartbeat_interval_s=_HEARTBEAT_S)
    with TestClient(app) as client:
        body = client.get("/api/diag/server").json()
        assert body["db_configured"] is False


def test_diag_server_exposes_subscription_billing_mode() -> None:
    app = create_app(heartbeat_interval_s=_HEARTBEAT_S, billing_mode="subscription")
    with TestClient(app) as client:
        body = client.get("/api/diag/server").json()
        assert body["billing_mode"] == "subscription"


def test_diag_sessions_initially_empty(app_client: TestClient) -> None:
    response = app_client.get("/api/diag/sessions")
    assert response.status_code == 200
    assert response.json() == {"runners": []}


def test_diag_drivers_initially_empty(app_client: TestClient) -> None:
    response = app_client.get("/api/diag/drivers")
    assert response.status_code == 200
    assert response.json() == {"drivers": []}


def test_diag_quota_no_poller(app_client: TestClient) -> None:
    response = app_client.get("/api/diag/quota")
    assert response.status_code == 200
    body = response.json()
    assert body["poller_configured"] is False
    assert body["has_snapshot"] is False
    assert body["captured_at"] is None


def test_diag_sessions_surfaces_a_runner(app_client: TestClient) -> None:
    """Touching the WS factory materialises a runner in the registry."""
    # Driving the runner factory's __call__ requires async; instead
    # we exercise via the public WS path indirectly. Easier: read
    # ``app.state.runner_factory._runners`` directly through the
    # diag endpoint by manually invoking the factory.
    factory = app_client.app.state.runner_factory  # type: ignore[attr-defined]

    async def _materialise() -> None:
        await factory("ses_diag_runner")

    asyncio.run(_materialise())
    response = app_client.get("/api/diag/sessions")
    runners = response.json()["runners"]
    assert any(r["session_id"] == "ses_diag_runner" for r in runners)
