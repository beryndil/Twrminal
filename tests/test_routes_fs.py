from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bearings.api import routes_fs


def test_list_returns_subdirs_sorted(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "Zeta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "mike").mkdir()
    (tmp_path / "a-file.txt").write_text("not a dir")

    resp = client.get("/api/fs/list", params={"path": str(tmp_path)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == str(tmp_path)
    assert body["parent"] == str(tmp_path.parent)
    # Case-insensitive alphabetical; files excluded.
    assert [e["name"] for e in body["entries"]] == ["alpha", "mike", "Zeta"]
    assert all(e["path"].startswith(str(tmp_path)) for e in body["entries"])


def test_list_omits_hidden_by_default(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    resp = client.get("/api/fs/list", params={"path": str(tmp_path)})
    names = [e["name"] for e in resp.json()["entries"]]
    assert names == ["src"]


def test_list_includes_hidden_when_requested(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    resp = client.get("/api/fs/list", params={"path": str(tmp_path), "hidden": "true"})
    names = [e["name"] for e in resp.json()["entries"]]
    assert names == [".git", "src"]


def test_list_rejects_relative_path(client: TestClient) -> None:
    resp = client.get("/api/fs/list", params={"path": "./relative"})
    assert resp.status_code == 400
    assert "absolute" in resp.json()["detail"]


def test_list_404s_on_missing_path(client: TestClient, tmp_path: Path) -> None:
    resp = client.get("/api/fs/list", params={"path": str(tmp_path / "nope")})
    assert resp.status_code == 404


def test_list_404s_on_file_path(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("")
    resp = client.get("/api/fs/list", params={"path": str(target)})
    assert resp.status_code == 404


def test_list_defaults_to_home(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no `path` query param, lists `$HOME`. Uses tmp_path as a
    fake home so tests don't depend on the developer's real home
    contents."""
    (tmp_path / "ProjectA").mkdir()
    monkeypatch.setattr("bearings.api.routes_fs.Path.home", lambda: tmp_path)
    resp = client.get("/api/fs/list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == str(tmp_path)
    assert "ProjectA" in [e["name"] for e in body["entries"]]


def test_list_root_parent_is_null(client: TestClient) -> None:
    """`/` has no parent — the UI uses this to hide the ⬆ button."""
    resp = client.get("/api/fs/list", params={"path": "/"})
    assert resp.status_code == 200
    assert resp.json()["parent"] is None


def _fake_picker(stdout: str, returncode: int = 0):
    """Build an async stub that mimics `_run_picker` without spawning
    zenity. Tests inject it via monkeypatch so the assertions never
    depend on a desktop being available."""

    async def run(argv: list[str]) -> tuple[int, str]:
        return returncode, stdout

    return run


def test_pick_returns_selected_path(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes_fs,
        "_pick_command",
        lambda *, start, multiple, title: ["zenity", "--file-selection"],
    )
    monkeypatch.setattr(routes_fs, "_run_picker", _fake_picker("/tmp/notes.md\n"))

    resp = client.post("/api/fs/pick")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "path": "/tmp/notes.md",
        "paths": ["/tmp/notes.md"],
        "cancelled": False,
    }


def test_pick_returns_cancelled_on_nonzero_exit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        routes_fs,
        "_pick_command",
        lambda *, start, multiple, title: ["zenity", "--file-selection"],
    )
    monkeypatch.setattr(routes_fs, "_run_picker", _fake_picker("", returncode=1))

    resp = client.post("/api/fs/pick")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cancelled"] is True
    assert body["path"] is None
    assert body["paths"] == []


def test_pick_handles_multiple_selection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # zenity --multiple with --separator=\0 gives us NUL-separated
    # paths; the route splits on NUL when any are present.
    stdout = "/tmp/a.txt\0/tmp/b.txt\0"
    monkeypatch.setattr(
        routes_fs,
        "_pick_command",
        lambda *, start, multiple, title: ["zenity", "--file-selection", "--multiple"],
    )
    monkeypatch.setattr(routes_fs, "_run_picker", _fake_picker(stdout))

    resp = client.post("/api/fs/pick", params={"multiple": "true"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "/tmp/a.txt"
    assert body["paths"] == ["/tmp/a.txt", "/tmp/b.txt"]
    assert body["cancelled"] is False


def test_pick_501s_when_no_backend_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        routes_fs,
        "_pick_command",
        lambda *, start, multiple, title: None,
    )
    resp = client.post("/api/fs/pick")
    assert resp.status_code == 501
    assert "zenity" in resp.json()["detail"]
