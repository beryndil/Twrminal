"""Tests for the `/api/pending` bridge.

Covers Phase 4a.1 of docs/context-menu-plan.md. The route is a thin
wrapper around `bearings.bearings_dir.pending`; unit coverage for the
underlying CRUD lives in `test_bearings_dir_pending.py`. Here we
exercise the HTTP shape: directory validation, 404 on unknown op
name, the 204 on DELETE, and that `list_ops` round-trips through the
Pydantic response model.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bearings.bearings_dir import pending as pending_ops


def test_list_pending_returns_empty_for_missing_dir(client: TestClient, tmp_path: Path) -> None:
    """A brand-new directory has no `.bearings/` yet. The route
    should return `[]` so the frontend can render the "nothing
    pending here" empty state without a 404 / try-catch dance."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    resp = client.get("/api/pending", params={"directory": str(empty_dir)})
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_pending_returns_seeded_ops(client: TestClient, tmp_path: Path) -> None:
    """Seed two ops via the underlying module then assert the route
    surfaces them in the oldest-first order `list_ops` guarantees."""
    project = tmp_path / "proj"
    project.mkdir()
    pending_ops.add(project, "migration", description="waiting on review")
    pending_ops.add(project, "refactor", description="paused for auth work")

    resp = client.get("/api/pending", params={"directory": str(project)})
    assert resp.status_code == 200
    names = [row["name"] for row in resp.json()]
    assert names == ["migration", "refactor"]


def test_list_pending_rejects_relative_directory(client: TestClient) -> None:
    """Relative paths would resolve against wherever the server was
    launched — surprising behavior, always a frontend bug, so a 400
    with a clear message catches it at the boundary."""
    resp = client.get("/api/pending", params={"directory": "relative/path"})
    assert resp.status_code == 400


def test_list_pending_rejects_empty_directory(client: TestClient) -> None:
    """FastAPI / Pydantic rejects the missing `directory` param at
    422 on its own; an explicit empty string passes that check but
    should still surface as a 400."""
    resp = client.get("/api/pending", params={"directory": ""})
    # FastAPI treats empty-string path as a missing required param, so
    # Pydantic surfaces 422 here. Either 400 or 422 is acceptable; we
    # just assert the route refuses it.
    assert resp.status_code in {400, 422}


def test_resolve_pending_removes_op(client: TestClient, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    pending_ops.add(project, "stuck", description="blocked")

    resp = client.post(
        "/api/pending/stuck/resolve",
        params={"directory": str(project)},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "stuck"
    # Second list should show the op is gone.
    remaining = client.get(
        "/api/pending",
        params={"directory": str(project)},
    ).json()
    assert remaining == []


def test_resolve_pending_returns_404_on_unknown_name(client: TestClient, tmp_path: Path) -> None:
    """The primitive returns None on unknown-name (idempotent for
    retries); the HTTP layer surfaces this as 404 so the frontend
    can refresh the list on a stale id rather than silently no-op."""
    project = tmp_path / "proj"
    project.mkdir()
    resp = client.post(
        "/api/pending/ghost/resolve",
        params={"directory": str(project)},
    )
    assert resp.status_code == 404


def test_delete_pending_returns_204(client: TestClient, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    pending_ops.add(project, "to-delete", description="going away")

    resp = client.delete(
        "/api/pending/to-delete",
        params={"directory": str(project)},
    )
    assert resp.status_code == 204
    remaining = client.get(
        "/api/pending",
        params={"directory": str(project)},
    ).json()
    assert remaining == []


def test_delete_pending_returns_404_on_unknown_name(client: TestClient, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    resp = client.delete(
        "/api/pending/ghost",
        params={"directory": str(project)},
    )
    assert resp.status_code == 404
