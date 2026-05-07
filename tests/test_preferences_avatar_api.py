"""Integration tests for the avatar / profile endpoints (gap-cycle-03-011).

Covers acceptance criteria:

1. ``PreferencesOut`` gains ``display_name`` + ``avatar_url`` fields.
2. ``POST /api/preferences/avatar`` (multipart) stores file, returns updated row.
3. ``GET  /api/preferences/avatar`` serves the stored bytes back.
4. ``DELETE /api/preferences/avatar`` removes file + clears DB fields.
5. ``POST /api/preferences/sync_from_system`` with fixture HOME.
6. Upload rejects unsupported MIME (415) and oversized body (413).
7. ``GET /api/preferences/avatar`` returns 404 when no avatar is set.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Iterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: float = 5.0

# Minimal 1x1 JPEG (valid magic bytes for mime sniffing).
_JPEG_1X1 = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04"
    b"\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"
    b'"2\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br'
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4\x9e\xf3\xff\xd9"
)

# Minimal 1x1 PNG.
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    """Boot the app with a sandboxed DB and avatars root."""
    db_path = tmp_path / "prefs.db"
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
            yield client, avatars_root
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1. PreferencesOut shape — new fields present
# ---------------------------------------------------------------------------


def test_get_preferences_includes_profile_fields(
    app_client: tuple[TestClient, Path],
) -> None:
    client, _ = app_client
    response = client.get("/api/preferences")
    assert response.status_code == 200
    payload = response.json()
    assert "display_name" in payload
    assert "avatar_url" in payload
    assert payload["display_name"] is None
    assert payload["avatar_url"] is None


# ---------------------------------------------------------------------------
# 2. POST /api/preferences/avatar — upload round-trip
# ---------------------------------------------------------------------------


def test_upload_avatar_returns_updated_prefs(
    app_client: tuple[TestClient, Path],
) -> None:
    client, avatars_root = app_client
    response = client.post(
        "/api/preferences/avatar",
        files={"file": ("photo.jpg", io.BytesIO(_JPEG_1X1), "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["avatar_url"] == "/api/preferences/avatar"
    # File should be on disk.
    assert (avatars_root / "current").exists()
    assert (avatars_root / "current").read_bytes() == _JPEG_1X1


def test_upload_avatar_replaces_previous(
    app_client: tuple[TestClient, Path],
) -> None:
    client, avatars_root = app_client
    client.post(
        "/api/preferences/avatar",
        files={"file": ("old.jpg", io.BytesIO(_JPEG_1X1), "image/jpeg")},
    )
    client.post(
        "/api/preferences/avatar",
        files={"file": ("new.png", io.BytesIO(_PNG_1X1), "image/png")},
    )
    assert (avatars_root / "current").read_bytes() == _PNG_1X1
    prefs = client.get("/api/preferences").json()
    assert prefs["avatar_url"] == "/api/preferences/avatar"


# ---------------------------------------------------------------------------
# 3. GET /api/preferences/avatar — bytes served back
# ---------------------------------------------------------------------------


def test_get_avatar_serves_bytes(
    app_client: tuple[TestClient, Path],
) -> None:
    client, _ = app_client
    client.post(
        "/api/preferences/avatar",
        files={"file": ("photo.jpg", io.BytesIO(_JPEG_1X1), "image/jpeg")},
    )
    response = client.get("/api/preferences/avatar")
    assert response.status_code == 200
    assert response.content == _JPEG_1X1
    assert response.headers["content-type"].startswith("image/jpeg")


def test_get_avatar_404_when_not_set(
    app_client: tuple[TestClient, Path],
) -> None:
    client, _ = app_client
    assert client.get("/api/preferences/avatar").status_code == 404


# ---------------------------------------------------------------------------
# 4. DELETE /api/preferences/avatar
# ---------------------------------------------------------------------------


def test_delete_avatar_clears_db_and_disk(
    app_client: tuple[TestClient, Path],
) -> None:
    client, avatars_root = app_client
    client.post(
        "/api/preferences/avatar",
        files={"file": ("photo.jpg", io.BytesIO(_JPEG_1X1), "image/jpeg")},
    )
    assert (avatars_root / "current").exists()

    response = client.delete("/api/preferences/avatar")
    assert response.status_code == 200
    payload = response.json()
    assert payload["avatar_url"] is None
    assert not (avatars_root / "current").exists()


def test_delete_avatar_idempotent(
    app_client: tuple[TestClient, Path],
) -> None:
    """DELETE with no avatar set should succeed (200)."""
    client, _ = app_client
    response = client.delete("/api/preferences/avatar")
    assert response.status_code == 200
    assert response.json()["avatar_url"] is None


# ---------------------------------------------------------------------------
# 5. POST /api/preferences/sync_from_system — fixture HOME
# ---------------------------------------------------------------------------


def test_sync_from_system_sets_display_name(
    app_client: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _avatars_root = app_client
    monkeypatch.setenv("USER", "testuser")
    # No ~/.face in this HOME.
    monkeypatch.setenv("HOME", str(tmp_path))

    response = client.post("/api/preferences/sync_from_system")
    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "testuser"
    # No .face file → no avatar.
    assert payload["avatar_url"] is None


def test_sync_from_system_copies_face_file(
    app_client: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _avatars_root = app_client
    monkeypatch.setenv("USER", "faceuser")
    # Create a fake ~/.face as a PNG.
    fake_home = tmp_path / "homedir"
    fake_home.mkdir()
    (fake_home / ".face").write_bytes(_PNG_1X1)
    monkeypatch.setenv("HOME", str(fake_home))

    response = client.post("/api/preferences/sync_from_system")
    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "faceuser"
    assert payload["avatar_url"] == "/api/preferences/avatar"

    # Bytes served back match the .face file.
    avatar_response = client.get("/api/preferences/avatar")
    assert avatar_response.status_code == 200
    assert avatar_response.content == _PNG_1X1


def test_sync_from_system_fallback_logname(
    app_client: tuple[TestClient, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """$USER absent — should fall back to $LOGNAME."""
    client, _ = app_client
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.setenv("LOGNAME", "loguser")
    monkeypatch.setenv("HOME", str(tmp_path))

    response = client.post("/api/preferences/sync_from_system")
    assert response.status_code == 200
    assert response.json()["display_name"] == "loguser"


# ---------------------------------------------------------------------------
# 6. Upload validation — 415 and 413
# ---------------------------------------------------------------------------


def test_upload_avatar_415_on_unsupported_mime(
    app_client: tuple[TestClient, Path],
) -> None:
    client, _ = app_client
    response = client.post(
        "/api/preferences/avatar",
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
    )
    assert response.status_code == 415


def test_upload_avatar_413_on_oversized_body(
    app_client: tuple[TestClient, Path],
) -> None:
    """Body > 2 MiB should be rejected."""
    client, _ = app_client
    big_body = b"\xff\xd8" + b"x" * (2 * 1024 * 1024 + 1)
    response = client.post(
        "/api/preferences/avatar",
        files={"file": ("huge.jpg", io.BytesIO(big_body), "image/jpeg")},
    )
    assert response.status_code == 413


def test_upload_avatar_400_on_empty_body(
    app_client: tuple[TestClient, Path],
) -> None:
    client, _ = app_client
    response = client.post(
        "/api/preferences/avatar",
        files={"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# display_name patchable via PATCH /api/preferences
# ---------------------------------------------------------------------------


def test_patch_preferences_sets_display_name(
    app_client: tuple[TestClient, Path],
) -> None:
    client, _ = app_client
    response = client.patch(
        "/api/preferences",
        json={"display_name": "Alice"},
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Alice"


def test_patch_preferences_clears_display_name(
    app_client: tuple[TestClient, Path],
) -> None:
    client, _ = app_client
    client.patch("/api/preferences", json={"display_name": "Alice"})
    response = client.patch("/api/preferences", json={"display_name": None})
    assert response.status_code == 200
    assert response.json()["display_name"] is None
