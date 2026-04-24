"""Tests for the `/api/artifacts/*` outbound file-display surface.

Mirrors the shape of `test_routes_uploads.py` but for the opposite
direction: uploads carry browser bytes *to* the agent; artifacts carry
agent-authored files *back* to the browser so the Conversation view can
render them inline. These tests exercise:

  * register (POST /sessions/{sid}/artifacts) — happy path, path must
    be absolute, path must live under `serve_roots`, the file must
    exist, size cap.
  * serve (GET /artifacts/{id}) — inline Content-Disposition, correct
    Content-Type, bytes round-trip, 404 on missing row, 404 when the
    configured serve roots no longer cover the stored path.
  * list (GET /sessions/{sid}/artifacts) — newest first, scoped to
    session.
  * delete (DELETE /sessions/{sid}/artifacts/{aid}) — row removed,
    bytes left alone, cross-session delete is 404.
  * download mode (?download=1) — attachment disposition instead of
    inline.

The `tmp_settings` fixture in conftest points `artifacts.serve_roots`
at tmp_path, so a registered path has to come from there. This mirrors
how the real config steers artifacts at `$XDG_DATA_HOME/bearings/`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from bearings.config import Settings


def _default_tag(client: TestClient) -> int:
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


def _create_session(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    tag_ids = kwargs.pop("tag_ids", None) or [_default_tag(client)]
    body = {
        "working_dir": "/tmp",
        "model": "claude-sonnet-4-6",
        "title": kwargs.pop("title", None),
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    out: dict[str, Any] = resp.json()
    return out


def _write_artifact_file(settings: Settings, name: str, content: bytes) -> Path:
    """Drop `content` into the configured artifacts dir under `name`.
    Returns the absolute path, matching what Claude would pass as
    `ArtifactRegister.path`."""
    root = Path(settings.artifacts.artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    target.write_bytes(content)
    return target


def test_register_artifact_happy_path(client: TestClient, tmp_settings: Settings) -> None:
    """Agent writes a file under the artifacts dir and registers it.
    The response carries the DB row plus a serve URL; the URL points
    at `/api/artifacts/{id}`. Hash + size match the bytes on disk."""
    body = b"\x89PNG\r\n\x1a\n fake png payload"
    path = _write_artifact_file(tmp_settings, "chart.png", body)
    session = _create_session(client, title="artifact-smoke")

    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["session_id"] == session["id"]
    assert payload["filename"] == "chart.png"
    assert payload["mime_type"] == "image/png"
    assert payload["size_bytes"] == len(body)
    assert payload["sha256"] == hashlib.sha256(body).hexdigest()
    assert payload["url"] == f"/api/artifacts/{payload['id']}"


def test_register_rejects_relative_path(client: TestClient) -> None:
    """Relative paths can't name a specific on-disk file — 400 rather
    than guessing what the CWD should be."""
    session = _create_session(client, title="relative")
    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": "chart.png"},
    )
    assert resp.status_code == 400
    assert "absolute" in resp.json()["detail"].lower()


def test_register_rejects_path_outside_serve_roots(client: TestClient, tmp_path: Path) -> None:
    """A path outside the configured `serve_roots` is refused. This is
    the primary security gate; /etc/passwd (or anything else the agent
    shouldn't be serving) never lands in the table."""
    outside = tmp_path / "outside-the-allowlist"
    outside.mkdir(parents=True)
    target = outside / "leak.txt"
    target.write_bytes(b"secrets")
    session = _create_session(client, title="allowlist-reject")
    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(target)},
    )
    assert resp.status_code == 400
    assert "serve root" in resp.json()["detail"]


def test_register_rejects_missing_file(client: TestClient, tmp_settings: Settings) -> None:
    """The path is under `serve_roots` but doesn't exist on disk.
    Hashing would raise downstream; the endpoint catches it and surfaces
    404 so Claude sees a clear error."""
    missing = Path(tmp_settings.artifacts.artifacts_dir) / "never-written.bin"
    session = _create_session(client, title="missing")
    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(missing)},
    )
    assert resp.status_code == 404


def test_register_rejects_over_size_limit(client: TestClient, tmp_settings: Settings) -> None:
    """`max_register_size_mb` caps what can be registered. A 2 MiB
    file against a 1 MB cap yields 413 and nothing lands in the DB."""
    # Shrink the cap via in-place mutation of the settings attached to
    # the running app — same trick `test_upload_rejects_over_size_limit`
    # uses. The handler reads cfg fresh on every call.
    app = client.app
    app.state.settings.artifacts.max_register_size_mb = 1  # type: ignore[attr-defined]

    payload = b"x" * (2 * 1024 * 1024)  # 2 MiB, over the 1 MB cap
    path = _write_artifact_file(tmp_settings, "big.bin", payload)
    session = _create_session(client, title="over-size")
    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    )
    assert resp.status_code == 413
    assert "1 MB" in resp.json()["detail"]


def test_register_unknown_session_404(client: TestClient, tmp_settings: Settings) -> None:
    """Session must exist. Otherwise a caller could walk session ids
    and populate artifact rows pointing at future sessions."""
    path = _write_artifact_file(tmp_settings, "orphan.png", b"ok")
    resp = client.post(
        "/api/sessions/does-not-exist/artifacts",
        json={"path": str(path)},
    )
    assert resp.status_code == 404


def test_register_uses_caller_filename_when_provided(
    client: TestClient, tmp_settings: Settings
) -> None:
    """The on-disk basename is a UUID or temp name; the caller supplies
    a readable `filename` for UI display. Stored verbatim."""
    path = _write_artifact_file(tmp_settings, "deadbeef.bin", b"bytes")
    session = _create_session(client, title="filename-override")
    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path), "filename": "q3-report.pdf"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "q3-report.pdf"


def test_serve_returns_bytes_with_inline_disposition(
    client: TestClient, tmp_settings: Settings
) -> None:
    """GET /api/artifacts/{id} streams the bytes back with the right
    MIME and `Content-Disposition: inline` so a markdown `<img>` renders
    the preview instead of the browser forcing a download."""
    body = b"\x89PNG\r\n\x1a\n some bytes"
    path = _write_artifact_file(tmp_settings, "inline.png", body)
    session = _create_session(client, title="serve")
    created = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    ).json()

    resp = client.get(created["url"])
    assert resp.status_code == 200
    assert resp.content == body
    assert resp.headers["content-type"].startswith("image/png")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("inline")
    assert 'filename="inline.png"' in disposition


def test_serve_download_flag_flips_to_attachment(
    client: TestClient, tmp_settings: Settings
) -> None:
    """`?download=1` flips the disposition so the same URL can serve
    either a preview or a real download link without duplicating the
    endpoint."""
    path = _write_artifact_file(tmp_settings, "report.txt", b"hi")
    session = _create_session(client, title="download")
    created = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    ).json()

    resp = client.get(created["url"] + "?download=1")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment")


def test_serve_unknown_id_404(client: TestClient) -> None:
    """Bogus artifact id — 404 rather than 500."""
    resp = client.get("/api/artifacts/nope-not-real")
    assert resp.status_code == 404


def test_serve_revokes_when_roots_narrow(
    client: TestClient, tmp_settings: Settings, tmp_path: Path
) -> None:
    """An artifact whose path is no longer under `serve_roots` reads
    back as 404. Narrowing config revokes access without needing a DB
    purge — exactly the behaviour `_resolve_serve_roots` documents."""
    path = _write_artifact_file(tmp_settings, "revoke.txt", b"soon-gone")
    session = _create_session(client, title="revoke")
    created = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    ).json()

    # Point serve_roots somewhere unrelated so the registered path no
    # longer qualifies. The row stays in the DB; only access changes.
    narrowed = tmp_path / "no-artifacts-here"
    narrowed.mkdir(parents=True)
    app = client.app
    app.state.settings.artifacts.serve_roots = [narrowed]  # type: ignore[attr-defined]

    resp = client.get(created["url"])
    assert resp.status_code == 404


def test_serve_404_when_bytes_removed_post_register(
    client: TestClient, tmp_settings: Settings
) -> None:
    """Registering captures a snapshot; the bytes can still vanish via
    external deletion (a GC sweep, a user rm). The serve path checks
    `is_file()` and surfaces 404 rather than 500-ing on the open."""
    path = _write_artifact_file(tmp_settings, "vanishing.png", b"bye")
    session = _create_session(client, title="vanishing")
    created = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    ).json()
    path.unlink()

    resp = client.get(created["url"])
    assert resp.status_code == 404


def test_list_session_artifacts_newest_first(client: TestClient, tmp_settings: Settings) -> None:
    """GET /sessions/{sid}/artifacts returns rows newest-first. Sanity-
    checks the composite index — uses two registered files with
    distinct content so ordering isn't ambiguous on a reordered UUID."""
    session = _create_session(client, title="list")
    first_path = _write_artifact_file(tmp_settings, "one.txt", b"A")
    first = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(first_path)},
    ).json()
    second_path = _write_artifact_file(tmp_settings, "two.txt", b"B")
    second = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(second_path)},
    ).json()

    resp = client.get(f"/api/sessions/{session['id']}/artifacts")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["id"] for r in rows] == [second["id"], first["id"]]


def test_list_scopes_to_session(client: TestClient, tmp_settings: Settings) -> None:
    """Artifacts registered against session A don't leak into session
    B's list. Cross-session isolation is what makes the per-session
    prefix in the URL meaningful."""
    s_a = _create_session(client, title="a")
    s_b = _create_session(client, title="b")
    path = _write_artifact_file(tmp_settings, "only-a.txt", b"A")
    client.post(
        f"/api/sessions/{s_a['id']}/artifacts",
        json={"path": str(path)},
    )
    b_list = client.get(f"/api/sessions/{s_b['id']}/artifacts").json()
    assert b_list == []


def test_delete_removes_row_but_not_bytes(client: TestClient, tmp_settings: Settings) -> None:
    """Delete drops the DB row; the on-disk file stays (retention GC
    is a separate sweep). Verifies both sides so a future GC change
    can't silently also delete bytes here without updating this
    contract."""
    path = _write_artifact_file(tmp_settings, "keep-bytes.txt", b"payload")
    session = _create_session(client, title="delete")
    created = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    ).json()

    resp = client.delete(f"/api/sessions/{session['id']}/artifacts/{created['id']}")
    assert resp.status_code == 204
    # Row gone — serve 404 proves it.
    follow = client.get(created["url"])
    assert follow.status_code == 404
    # Bytes still present — GC sweep is a different concern.
    assert path.read_bytes() == b"payload"


def test_delete_rejects_cross_session(client: TestClient, tmp_settings: Settings) -> None:
    """A delete against a session that doesn't own the artifact is a
    404 — prevents an API consumer from deleting another session's
    artifact by guessing its id under the wrong session prefix."""
    s_a = _create_session(client, title="owner")
    s_b = _create_session(client, title="stranger")
    path = _write_artifact_file(tmp_settings, "owned.txt", b"mine")
    created = client.post(
        f"/api/sessions/{s_a['id']}/artifacts",
        json={"path": str(path)},
    ).json()

    resp = client.delete(f"/api/sessions/{s_b['id']}/artifacts/{created['id']}")
    assert resp.status_code == 404
    # And confirm the artifact is still reachable through the owner.
    follow = client.get(created["url"])
    assert follow.status_code == 200


def test_register_detects_svg_as_image(client: TestClient, tmp_settings: Settings) -> None:
    """SVG detection hits the `_EXT_MIME_OVERRIDES` fallback path when
    the stdlib guesser under-reports. The override keeps inline-render
    working for svg, which is a common agent-authored format."""
    path = _write_artifact_file(
        tmp_settings,
        "diagram.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg"/>',
    )
    session = _create_session(client, title="svg")
    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["mime_type"] == "image/svg+xml"


def test_register_detects_markdown_mime(client: TestClient, tmp_settings: Settings) -> None:
    """`.md` maps to text/markdown via the override map so download
    links fetch with a sensible Content-Type instead of the stdlib's
    occasionally-empty guess."""
    path = _write_artifact_file(tmp_settings, "readme.md", b"# hello\n")
    session = _create_session(client, title="md")
    resp = client.post(
        f"/api/sessions/{session['id']}/artifacts",
        json={"path": str(path)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["mime_type"] == "text/markdown"
