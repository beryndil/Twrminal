"""Integration tests for ``bearings.web.routes.fs`` (item 1.10).

Exercises happy-path list/read plus the security boundary: relative
paths, paths outside allow-roots, ``..`` traversal, and symlink
escape.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from fastapi.testclient import TestClient

from bearings.config.settings import FsCfg
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0


@pytest.fixture
def fs_root(tmp_path: Path) -> Path:
    """A small allow-root tree with a file + a subdirectory."""
    root = tmp_path / "fs-root"
    root.mkdir()
    (root / "hello.txt").write_text("greetings\n", encoding="utf-8")
    (root / "subdir").mkdir()
    (root / "subdir" / "nested.txt").write_text("nested-body\n", encoding="utf-8")
    return root


@pytest.fixture
def app_client(fs_root: Path) -> Iterator[TestClient]:
    """Boot the app with ``fs_root`` as the sole allow-root."""
    cfg = FsCfg(allow_roots=(fs_root,))
    app = create_app(heartbeat_interval_s=_HEARTBEAT_S, fs_cfg=cfg)
    with TestClient(app) as client:
        yield client


def test_get_list_returns_entries(app_client: TestClient, fs_root: Path) -> None:
    response = app_client.get("/api/fs/list", params={"path": str(fs_root)})
    assert response.status_code == 200
    body = response.json()
    names = {e["name"] for e in body["entries"]}
    assert names == {"hello.txt", "subdir"}
    assert body["capped"] is False
    kinds = {e["name"]: e["kind"] for e in body["entries"]}
    assert kinds["hello.txt"] == "file"
    assert kinds["subdir"] == "dir"


def test_get_read_returns_content(app_client: TestClient, fs_root: Path) -> None:
    target = fs_root / "hello.txt"
    response = app_client.get("/api/fs/read", params={"path": str(target)})
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "greetings\n"
    assert body["size"] == len("greetings\n")
    assert body["truncated"] is False


def test_get_list_403_outside_allow_root(app_client: TestClient, tmp_path: Path) -> None:
    # ``tmp_path`` itself is the parent of ``fs-root`` and is NOT in
    # the allow-root set.
    response = app_client.get("/api/fs/list", params={"path": str(tmp_path)})
    assert response.status_code == 403


def test_get_list_403_on_dotdot_traversal(app_client: TestClient, fs_root: Path) -> None:
    escape = str(fs_root / "subdir" / ".." / "..")
    response = app_client.get("/api/fs/list", params={"path": escape})
    assert response.status_code == 403


def test_get_read_400_on_relative_path(app_client: TestClient) -> None:
    response = app_client.get("/api/fs/read", params={"path": "relative/path"})
    assert response.status_code == 400


def test_get_read_404_when_missing(app_client: TestClient, fs_root: Path) -> None:
    response = app_client.get(
        "/api/fs/read",
        params={"path": str(fs_root / "does-not-exist.txt")},
    )
    assert response.status_code == 404


def test_get_read_422_when_path_is_directory(app_client: TestClient, fs_root: Path) -> None:
    response = app_client.get(
        "/api/fs/read",
        params={"path": str(fs_root / "subdir")},
    )
    assert response.status_code == 422


def test_get_list_403_on_symlink_escape(
    app_client: TestClient, fs_root: Path, tmp_path: Path
) -> None:
    # Plant a symlink INSIDE the allow-root that points OUTSIDE.
    outside = tmp_path / "outside-vault"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    link = fs_root / "evil-link"
    os.symlink(outside, link)
    # Reading via the symlink path should resolve to outside the root
    # and 403.
    response = app_client.get(
        "/api/fs/list",
        params={"path": str(link)},
    )
    assert response.status_code == 403


def test_get_list_no_allow_roots_403() -> None:
    """A fresh ``FsCfg()`` has empty ``allow_roots`` → every request 403s."""
    app = create_app(heartbeat_interval_s=_HEARTBEAT_S, fs_cfg=FsCfg())
    with TestClient(app) as client:
        response = client.get("/api/fs/list", params={"path": "/tmp"})
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/fs/pick  (item 3.1 — folder picker)
# ---------------------------------------------------------------------------


def test_post_pick_returns_listing(app_client: TestClient, fs_root: Path) -> None:
    """Happy-path: list a configured allow-root via the pick endpoint."""
    response = app_client.post("/api/fs/pick", json={"root": str(fs_root)})
    assert response.status_code == 200
    body = response.json()
    assert "token" in body and len(body["token"]) > 0
    assert body["path"] == str(fs_root)
    names = {e["name"] for e in body["entries"]}
    assert names == {"hello.txt", "subdir"}
    assert body["capped"] is False


def test_post_pick_token_is_unique_per_call(app_client: TestClient, fs_root: Path) -> None:
    """Each POST /api/fs/pick call issues a fresh token UUID."""
    r1 = app_client.post("/api/fs/pick", json={"root": str(fs_root)})
    r2 = app_client.post("/api/fs/pick", json={"root": str(fs_root)})
    assert r1.json()["token"] != r2.json()["token"]


def test_post_pick_403_outside_configured_roots(app_client: TestClient, tmp_path: Path) -> None:
    """A path outside the configured allow-roots is rejected."""
    # ``tmp_path`` is the parent of ``fs-root`` and not itself in the roots.
    response = app_client.post("/api/fs/pick", json={"root": str(tmp_path)})
    assert response.status_code == 403


def test_post_pick_empty_root_defaults_to_home() -> None:
    """With empty allow_roots, omitting root falls back to ``$HOME``.

    The picker accepts any absolute path under filesystem root in this
    mode (see :func:`bearings.web.routes.fs._pick_roots`), but the
    *default* opening directory when the caller omits ``root`` is still
    ``$HOME`` — that's where work-in-progress projects typically live
    and what the user most often wants as the picker's starting point.
    """
    app = create_app(heartbeat_interval_s=_HEARTBEAT_S, fs_cfg=FsCfg())
    with TestClient(app) as client:
        response = client.post("/api/fs/pick", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["path"] == os.path.expanduser("~")


def test_post_pick_empty_allow_roots_accepts_any_absolute_path(tmp_path: Path) -> None:
    """With empty ``allow_roots``, the picker can navigate anywhere.

    Regression: before this fix, ``_pick_roots`` fell back to
    ``(Path.home(),)`` so any picker navigation outside ``$HOME``
    (``/tmp``, ``/srv``, another user's project tree) returned 403
    "path '...' is outside the configured fs allow-roots". Single-user
    localhost defaults must let the operator browse any directory they
    have read access to.
    """
    target = tmp_path / "outside-home"
    target.mkdir()
    app = create_app(heartbeat_interval_s=_HEARTBEAT_S, fs_cfg=FsCfg())
    with TestClient(app) as client:
        response = client.post("/api/fs/pick", json={"root": str(target)})
        assert response.status_code == 200
        body = response.json()
        assert body["path"] == str(target)


def test_post_pick_navigates_subdirectory(app_client: TestClient, fs_root: Path) -> None:
    """Navigating into a subdir returns its listing."""
    subdir = fs_root / "subdir"
    response = app_client.post("/api/fs/pick", json={"root": str(subdir)})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(subdir)
    names = {e["name"] for e in body["entries"]}
    assert "nested.txt" in names
