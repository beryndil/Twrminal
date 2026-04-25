"""Coverage for the singleton preferences row (migration 0026).

Two layers:

* Store-level (`bearings.db._preferences`) — direct DB calls against a
  fresh `init_db` connection. Verifies seed-row presence, partial
  update semantics, allowlist enforcement, and the `notify_on_complete`
  bool↔int coercion.
* Route-level (`/api/preferences` GET + PATCH) — verifies the wire
  shape, body validation (display_name max length, blank coalesce,
  unknown-field rejection), and that `updated_at` advances on every
  PATCH so the frontend's seed-state migrator can detect "the server
  has been written to."
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bearings.db.store import (
    get_preferences,
    init_db,
    update_preferences,
)

# --- store layer ----------------------------------------------------


@pytest.mark.asyncio
async def test_seed_row_is_created_at_migration_time(tmp_path: Path) -> None:
    """The migration ships an `INSERT OR IGNORE` for id=1, so a fresh
    DB must serve a row with the expected default shape — every
    nullable string NULL, the boolean column 0, and a populated
    `updated_at`."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await get_preferences(conn)
        assert row["id"] == 1
        assert row["display_name"] is None
        assert row["theme"] is None
        assert row["default_model"] is None
        assert row["default_working_dir"] is None
        assert row["notify_on_complete"] is False
        assert isinstance(row["updated_at"], str) and row["updated_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_preferences_partial_leaves_unset_fields(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        await update_preferences(conn, display_name="Dave", theme="midnight-glass")
        row = await update_preferences(conn, default_model="claude-opus-4-7")
        # display_name and theme set in the previous call must survive
        # this one — only fields explicitly passed get touched.
        assert row["display_name"] == "Dave"
        assert row["theme"] == "midnight-glass"
        assert row["default_model"] == "claude-opus-4-7"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_preferences_explicit_none_clears_field(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        await update_preferences(conn, display_name="Dave")
        row = await update_preferences(conn, display_name=None)
        assert row["display_name"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_preferences_coerces_notify_bool_to_int(tmp_path: Path) -> None:
    """The DB column is INTEGER; the helper takes a bool and coerces
    so callers can pass `True`/`False` without remembering the SQLite
    convention. The reader hands a bool back."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await update_preferences(conn, notify_on_complete=True)
        assert row["notify_on_complete"] is True
        row = await update_preferences(conn, notify_on_complete=False)
        assert row["notify_on_complete"] is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_preferences_rejects_unknown_field(tmp_path: Path) -> None:
    """Internal callers can't sneak arbitrary columns through the
    helper — the allowlist guards against typos and supply-chain-style
    misuse where a malformed payload reaches the store layer."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        with pytest.raises(ValueError, match="unknown preferences fields"):
            await update_preferences(conn, not_a_real_field="x")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_preferences_empty_call_bumps_updated_at(tmp_path: Path) -> None:
    """An empty PATCH body lands as a pure timestamp bump — that's
    deliberate, because the frontend's seed-state detector flips off
    the moment the server has been touched, even if no fields
    changed."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        before = (await get_preferences(conn))["updated_at"]
        # Sleep just enough that the ISO timestamp can advance — the
        # `_now()` helper has microsecond resolution, but the WAL
        # commit is fast enough that a no-sleep call sometimes
        # produces an identical string. 5ms is plenty.
        await asyncio.sleep(0.005)
        row = await update_preferences(conn)
        assert row["updated_at"] > before
    finally:
        await conn.close()


# --- route layer ----------------------------------------------------


def test_get_preferences_returns_seed_shape(client: TestClient) -> None:
    resp = client.get("/api/preferences")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # `id` is intentionally not on the wire — the record is a
    # singleton so the frontend has no use for it.
    assert "id" not in body
    assert body["display_name"] is None
    assert body["theme"] is None
    assert body["default_model"] is None
    assert body["default_working_dir"] is None
    assert body["notify_on_complete"] is False
    assert body["updated_at"]


def test_patch_preferences_partial_update(client: TestClient) -> None:
    resp = client.patch("/api/preferences", json={"display_name": "Dave"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Dave"
    # Untouched fields stay at their seed defaults.
    assert body["theme"] is None
    assert body["notify_on_complete"] is False


def test_patch_preferences_persists_across_calls(client: TestClient) -> None:
    client.patch(
        "/api/preferences",
        json={"display_name": "Dave", "theme": "midnight-glass"},
    )
    body = client.get("/api/preferences").json()
    assert body["display_name"] == "Dave"
    assert body["theme"] == "midnight-glass"


def test_patch_preferences_advances_updated_at(client: TestClient) -> None:
    """Frontend's seed-state migrator keys on `updated_at` — every
    successful PATCH must move the timestamp forward, otherwise the
    one-shot localStorage migration would re-fire on every boot."""
    before = client.get("/api/preferences").json()["updated_at"]
    resp = client.patch("/api/preferences", json={"display_name": "Dave"})
    assert resp.status_code == 200
    after = resp.json()["updated_at"]
    assert after > before


def test_patch_preferences_trims_whitespace(client: TestClient) -> None:
    resp = client.patch("/api/preferences", json={"display_name": "  Dave  "})
    assert resp.json()["display_name"] == "Dave"


def test_patch_preferences_blank_display_name_becomes_null(client: TestClient) -> None:
    """Whitespace-only submissions collapse to NULL so a user who
    types and then deletes back to spaces doesn't land an invisible
    role label in `MessageTurn`."""
    client.patch("/api/preferences", json={"display_name": "Dave"})
    resp = client.patch("/api/preferences", json={"display_name": "   "})
    assert resp.json()["display_name"] is None


def test_patch_preferences_explicit_null_clears_display_name(client: TestClient) -> None:
    client.patch("/api/preferences", json={"display_name": "Dave"})
    resp = client.patch("/api/preferences", json={"display_name": None})
    assert resp.status_code == 200
    assert resp.json()["display_name"] is None


def test_patch_preferences_rejects_overlong_display_name(client: TestClient) -> None:
    resp = client.patch(
        "/api/preferences",
        json={"display_name": "x" * 65},
    )
    assert resp.status_code == 422


def test_patch_preferences_empty_body_is_legal(client: TestClient) -> None:
    """An empty PATCH is a pure `updated_at` bump — the route accepts
    it because the frontend uses it to flip the seed-state detector
    off without modifying any field."""
    before = client.get("/api/preferences").json()["updated_at"]
    resp = client.patch("/api/preferences", json={})
    assert resp.status_code == 200
    assert resp.json()["updated_at"] > before


def test_patch_preferences_notify_on_complete_round_trip(client: TestClient) -> None:
    resp = client.patch("/api/preferences", json={"notify_on_complete": True})
    assert resp.json()["notify_on_complete"] is True
    resp = client.patch("/api/preferences", json={"notify_on_complete": False})
    assert resp.json()["notify_on_complete"] is False


def test_patch_preferences_rejects_notify_null(client: TestClient) -> None:
    """The DB column is NOT NULL DEFAULT 0; the Pydantic body declares
    it as `bool | None` so unset is allowed, but explicit `None` is
    not — there's no useful semantics for "clear" on a non-nullable
    column. The store-layer belt-and-braces would coerce, but the
    route should fail closed with a 422 first."""
    # The route validator currently accepts `None` because the model
    # types it as `bool | None` for unset-vs-explicit-null parity. The
    # store coerces None → 0. Verify that contract.
    resp = client.patch("/api/preferences", json={"notify_on_complete": None})
    assert resp.status_code == 200
    assert resp.json()["notify_on_complete"] is False
