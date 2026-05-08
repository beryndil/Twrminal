"""Integration tests for the notify_on_complete preference (gap-cycle-07-001).

Acceptance criteria covered:

1. GET /api/preferences returns ``notify_on_complete`` field (default False).
2. PATCH /api/preferences with ``notify_on_complete: true`` persists and
   round-trips the value.
3. PATCH with ``notify_on_complete: false`` clears the value.
4. Omitting ``notify_on_complete`` from a PATCH leaves the current value
   unchanged (Pydantic model_fields_set semantics).
5. Existing PreferencesOut consumers are not broken (other fields present).

CCW-2 / feature-8-003: PATCH with null returns 422 (column is NOT NULL).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: float = 5.0


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    """Boot the app with a sandboxed DB."""
    db_path = tmp_path / "prefs_notify.db"
    avatars_root = tmp_path / "avatars"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(
            heartbeat_interval_s=_HEARTBEAT_S,
            db_connection=conn,
            avatars_root=avatars_root,
        )
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1. GET — field present with default False
# ---------------------------------------------------------------------------


def test_get_preferences_includes_notify_on_complete(app_client: TestClient) -> None:
    response = app_client.get("/api/preferences")
    assert response.status_code == 200
    payload = response.json()
    assert "notify_on_complete" in payload
    assert payload["notify_on_complete"] is False


# ---------------------------------------------------------------------------
# 2. PATCH — enable persists
# ---------------------------------------------------------------------------


def test_patch_notify_on_complete_true(app_client: TestClient) -> None:
    response = app_client.patch(
        "/api/preferences",
        json={"notify_on_complete": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["notify_on_complete"] is True

    # Round-trip via GET confirms persistence.
    get_response = app_client.get("/api/preferences")
    assert get_response.json()["notify_on_complete"] is True


# ---------------------------------------------------------------------------
# 3. PATCH — disable clears
# ---------------------------------------------------------------------------


def test_patch_notify_on_complete_false(app_client: TestClient) -> None:
    # First enable.
    app_client.patch("/api/preferences", json={"notify_on_complete": True})
    # Now disable.
    response = app_client.patch(
        "/api/preferences",
        json={"notify_on_complete": False},
    )
    assert response.status_code == 200
    assert response.json()["notify_on_complete"] is False

    get_response = app_client.get("/api/preferences")
    assert get_response.json()["notify_on_complete"] is False


# ---------------------------------------------------------------------------
# 4. PATCH — omitting the field leaves it unchanged
# ---------------------------------------------------------------------------


def test_patch_omit_notify_leaves_unchanged(app_client: TestClient) -> None:
    # Enable first.
    app_client.patch("/api/preferences", json={"notify_on_complete": True})
    # Patch only theme — notify_on_complete should remain True.
    response = app_client.patch("/api/preferences", json={"theme": "default"})
    assert response.status_code == 200
    assert response.json()["notify_on_complete"] is True


# ---------------------------------------------------------------------------
# 5. Existing fields are not broken
# ---------------------------------------------------------------------------


def test_existing_fields_present_alongside_notify(app_client: TestClient) -> None:
    response = app_client.get("/api/preferences")
    assert response.status_code == 200
    payload = response.json()
    for field in (
        "theme",
        "default_model",
        "default_permission_mode",
        "default_working_dir",
        "display_name",
        "avatar_url",
        "updated_at",
        "notify_on_complete",
    ):
        assert field in payload, f"missing field: {field}"


# ---------------------------------------------------------------------------
# CCW-2 / feature-8-003 — null rejected; column is NOT NULL DEFAULT 0
# ---------------------------------------------------------------------------


def test_patch_notify_on_complete_null_returns_422(app_client: TestClient) -> None:
    """PATCH with explicit null for notify_on_complete must return 422.

    The column is NOT NULL; the Pydantic type is now ``bool`` (no None),
    so Pydantic rejects the null at the wire boundary before the DB layer
    is reached.
    """
    response = app_client.patch("/api/preferences", json={"notify_on_complete": None})
    assert response.status_code == 422
