"""Integration tests for POST /api/pending/{name}/resolve and
DELETE /api/pending/{name} (gap-cycle-03-010).

Acceptance-criteria coverage:

* AC-1  POST resolve removes the named entry and returns 204.
* AC-2  DELETE dismiss removes the named entry and returns 204.
* AC-3  Both endpoints persist: re-reading the file shows the entry gone.
* AC-4  Unknown name → 404 for both endpoints.
* AC-5  File absent / empty ops → 404 (no op to remove).
* AC-6  Round-trip: multi-op file leaves remaining ops intact.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from bearings.web.app import create_app

_TOML_TWO_OPS = """\
[ops.deploy]
description = "Deploy to prod"
started_at = "2024-01-01T00:00:00Z"

[ops.review]
description = "Code review"
started_at = "2024-01-02T00:00:00Z"
"""

_TOML_ONE_OP = """\
[ops.deploy]
description = "Deploy to prod"
started_at = "2024-01-01T00:00:00Z"
"""


def _pending_path(project_root: Path) -> Path:
    p = project_root / ".bearings" / "pending.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# AC-1  POST /resolve → 204, entry removed
# ---------------------------------------------------------------------------


def test_resolve_returns_204_and_removes_entry(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_ONE_OP)
    client = TestClient(create_app())
    resp = client.post(
        "/api/pending/deploy/resolve",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 204
    with open(_pending_path(tmp_path), "rb") as fh:
        data = tomllib.load(fh)
    assert "deploy" not in data.get("ops", {})


# ---------------------------------------------------------------------------
# AC-2  DELETE /dismiss → 204, entry removed
# ---------------------------------------------------------------------------


def test_dismiss_returns_204_and_removes_entry(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_ONE_OP)
    client = TestClient(create_app())
    resp = client.delete(
        "/api/pending/deploy",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 204
    with open(_pending_path(tmp_path), "rb") as fh:
        data = tomllib.load(fh)
    assert "deploy" not in data.get("ops", {})


# ---------------------------------------------------------------------------
# AC-3  Persist: re-reading the file shows the entry gone
# ---------------------------------------------------------------------------


def test_resolve_persists_to_disk(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_TWO_OPS)
    client = TestClient(create_app())
    client.post("/api/pending/deploy/resolve", params={"directory": str(tmp_path)})
    # Re-read the file in a separate Python call — no in-memory cache.
    with open(_pending_path(tmp_path), "rb") as fh:
        data = tomllib.load(fh)
    ops = data.get("ops", {})
    assert "deploy" not in ops
    assert "review" in ops


# ---------------------------------------------------------------------------
# AC-4  Unknown name → 404
# ---------------------------------------------------------------------------


def test_resolve_unknown_name_returns_404(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_ONE_OP)
    client = TestClient(create_app())
    resp = client.post(
        "/api/pending/nonexistent/resolve",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 404
    assert "nonexistent" in resp.json()["detail"]


def test_dismiss_unknown_name_returns_404(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_ONE_OP)
    client = TestClient(create_app())
    resp = client.delete(
        "/api/pending/nonexistent",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 404
    assert "nonexistent" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# AC-5  File absent → 404
# ---------------------------------------------------------------------------


def test_resolve_missing_file_returns_404(tmp_path: Path) -> None:
    # No pending.toml created.
    client = TestClient(create_app())
    resp = client.post(
        "/api/pending/deploy/resolve",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 404


def test_dismiss_missing_file_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app())
    resp = client.delete(
        "/api/pending/deploy",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-6  Round-trip: multi-op file — removing one leaves the other intact
# ---------------------------------------------------------------------------


def test_resolve_leaves_remaining_ops_intact(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_TWO_OPS)
    client = TestClient(create_app())
    resp = client.post(
        "/api/pending/deploy/resolve",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 204
    with open(_pending_path(tmp_path), "rb") as fh:
        data = tomllib.load(fh)
    ops = data.get("ops", {})
    assert "deploy" not in ops
    assert ops.get("review", {}).get("description") == "Code review"


def test_dismiss_leaves_remaining_ops_intact(tmp_path: Path) -> None:
    _pending_path(tmp_path).write_text(_TOML_TWO_OPS)
    client = TestClient(create_app())
    resp = client.delete(
        "/api/pending/review",
        params={"directory": str(tmp_path)},
    )
    assert resp.status_code == 204
    with open(_pending_path(tmp_path), "rb") as fh:
        data = tomllib.load(fh)
    ops = data.get("ops", {})
    assert "review" not in ops
    assert ops.get("deploy", {}).get("description") == "Deploy to prod"
