"""Integration tests for ``bearings.web.routes.quota`` (spec §9 quota).

Covers all 3 quota endpoints: ``GET /api/quota/current``,
``POST /api/quota/refresh``, ``GET /api/quota/history``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.agent.quota import (
    QuotaPoller,
    QuotaSnapshot,
    make_static_fetcher,
    record_snapshot,
)
from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0


@pytest.fixture
def app_client_no_poller(tmp_path: Path) -> Iterator[TestClient]:
    """App without a poller — exercises the DB-fallback paths."""
    db_path = tmp_path / "quota_api.db"

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


@pytest.fixture
def app_client_with_poller(tmp_path: Path) -> Iterator[TestClient]:
    """App with a poller backed by a static fetcher."""
    db_path = tmp_path / "quota_api_poller.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        snapshot = QuotaSnapshot(
            captured_at=int(time.time()),
            overall_used_pct=0.42,
            sonnet_used_pct=0.30,
            overall_resets_at=None,
            sonnet_resets_at=None,
            raw_payload='{"static": true}',
        )
        poller = QuotaPoller(conn, make_static_fetcher(snapshot))
        app = create_app(
            heartbeat_interval_s=_HEARTBEAT_S,
            db_connection=conn,
            quota_poller=poller,
        )
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_get_current_returns_404_when_empty(
    app_client_no_poller: TestClient,
) -> None:
    """No snapshots ever recorded → 404."""
    response = app_client_no_poller.get("/api/quota/current")
    assert response.status_code == 404


def test_get_current_404_body_shape(
    app_client_no_poller: TestClient,
) -> None:
    """404 body matches the declared DetailError schema (``{"detail": str}``)."""
    response = app_client_no_poller.get("/api/quota/current")
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], str)
    assert body["detail"] == "no quota snapshot recorded yet"


def test_get_current_returns_persisted_snapshot(
    tmp_path: Path,
) -> None:
    """A snapshot in the DB (no poller) surfaces via current."""
    db_path = tmp_path / "current.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        await record_snapshot(
            conn,
            QuotaSnapshot(
                captured_at=int(time.time()),
                overall_used_pct=0.55,
                sonnet_used_pct=0.20,
                overall_resets_at=None,
                sonnet_resets_at=None,
                raw_payload="{}",
            ),
        )
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/quota/current")
            assert response.status_code == 200
            body = response.json()
            assert body["overall_used_pct"] == pytest.approx(0.55)
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_post_refresh_returns_503_without_poller(
    app_client_no_poller: TestClient,
) -> None:
    """Refresh requires a configured poller."""
    response = app_client_no_poller.post("/api/quota/refresh")
    assert response.status_code == 503


def test_post_refresh_returns_snapshot_with_poller(
    app_client_with_poller: TestClient,
) -> None:
    """Refresh fires the fetcher and surfaces the result."""
    response = app_client_with_poller.post("/api/quota/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["overall_used_pct"] == pytest.approx(0.42)
    assert "static" in body["raw_payload"]


def test_get_history_returns_oldest_first(tmp_path: Path) -> None:
    """History returns snapshots oldest-first within the window."""
    db_path = tmp_path / "history.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        now = int(time.time())
        # Three snapshots: 2 days ago, 1 day ago, now.
        for offset_days, pct in [(2, 0.1), (1, 0.3), (0, 0.5)]:
            await record_snapshot(
                conn,
                QuotaSnapshot(
                    captured_at=now - offset_days * 86_400,
                    overall_used_pct=pct,
                    sonnet_used_pct=None,
                    overall_resets_at=None,
                    sonnet_resets_at=None,
                    raw_payload="{}",
                ),
            )
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/quota/history?days=7")
            assert response.status_code == 200
            rows = response.json()
            assert len(rows) == 3
            # ASC by captured_at: 0.1 first.
            assert rows[0]["overall_used_pct"] == pytest.approx(0.1)
            assert rows[-1]["overall_used_pct"] == pytest.approx(0.5)
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_get_history_rejects_zero_days(
    app_client_no_poller: TestClient,
) -> None:
    """``days <= 0`` rejected via Query validation (422)."""
    response = app_client_no_poller.get("/api/quota/history?days=0")
    assert response.status_code == 422
