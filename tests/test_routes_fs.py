from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


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
    # Case-insensitive alphabetical; files excluded by default so the
    # folder picker keeps its old contract.
    assert [e["name"] for e in body["entries"]] == ["alpha", "mike", "Zeta"]
    assert all(e["is_dir"] is True for e in body["entries"])
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


def test_list_include_files_returns_both_with_is_dir_flag(
    client: TestClient, tmp_path: Path
) -> None:
    """FilePickerModal calls with include_files=true so users can pick
    a file. Entries carry is_dir so the UI can render distinct affordances
    (descend vs select) without inspecting each path.

    Uses a fresh subdir because `tmp_path` is shared with the tmp_settings
    fixture's sqlite db — listing it directly would pick up db.sqlite*
    files and make the assertion flaky.
    """
    root = tmp_path / "fsroot"
    root.mkdir()
    (root / "src").mkdir()
    (root / "notes.md").write_text("body")
    (root / "data.csv").write_text("a,b")

    resp = client.get("/api/fs/list", params={"path": str(root), "include_files": "true"})
    assert resp.status_code == 200
    by_name = {e["name"]: e for e in resp.json()["entries"]}
    assert set(by_name) == {"src", "notes.md", "data.csv"}
    assert by_name["src"]["is_dir"] is True
    assert by_name["notes.md"]["is_dir"] is False
    assert by_name["data.csv"]["is_dir"] is False


def test_list_include_files_skips_special_entries(client: TestClient, tmp_path: Path) -> None:
    """Sockets / fifos / broken symlinks are not useful to hand Claude
    and shouldn't trip the listing. We create a fifo and a dangling
    symlink in an isolated subdir and assert they're silently excluded."""
    import os

    root = tmp_path / "fsroot"
    root.mkdir()
    (root / "real.txt").write_text("ok")
    os.mkfifo(root / "pipe")
    (root / "dangling").symlink_to(root / "nope")

    resp = client.get("/api/fs/list", params={"path": str(root), "include_files": "true"})
    assert resp.status_code == 200
    names = sorted(e["name"] for e in resp.json()["entries"])
    assert names == ["real.txt"]


# ---------------------------------------------------------------------------
# POST /api/fs/pick — native picker bridge
#
# Tests mock both `shutil.which` (to force one specific picker onto the
# PATH) and `asyncio.create_subprocess_exec` (so no actual zenity/kdialog
# dialog pops during CI). `_FakeProc` mirrors the subset of the asyncio
# subprocess API the route touches — enough to drive the happy paths, the
# cancel branch, the multi-select NUL-split branch, and the timeout.


class _FakeProc:
    """Stands in for `asyncio.subprocess.Process`. Supplies a coroutine
    `communicate()` that returns the stdout bytes the test wants, and a
    `returncode` attribute the route reads after `communicate()`
    resolves. `kill`/`wait` are defined so the timeout branch can tear
    the fake process down without blowing up.
    """

    def __init__(
        self,
        stdout: bytes,
        returncode: int,
        *,
        hang: bool = False,
    ) -> None:
        self._stdout = stdout
        self.returncode = returncode
        self._hang = hang

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            # Longer than the route's timeout; `asyncio.wait_for` will
            # cancel this before it ever resolves.
            await asyncio.sleep(60)
        return self._stdout, b""

    def kill(self) -> None:
        pass

    async def wait(self) -> int:
        return self.returncode


class _PickerPatch:
    """Wire `shutil.which` and `create_subprocess_exec` so the route
    thinks `which_binary` is on PATH and subprocess spawn returns
    `proc`. `which_binary=None` simulates "no picker installed" — the
    route should 501 without ever reaching subprocess.
    """

    def __init__(self, *, which_binary: str | None, proc: _FakeProc | None) -> None:
        self._which_binary = which_binary
        self._proc = proc
        self._ctxs: list[Any] = []

    def __enter__(self) -> _PickerPatch:
        which_binary = self._which_binary
        proc = self._proc

        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name == which_binary else None

        async def fake_exec(*_args: Any, **_kwargs: Any) -> _FakeProc:
            assert proc is not None, "route should not spawn when no picker"
            return proc

        self._ctxs = [
            patch("bearings.api.routes_fs.shutil.which", side_effect=fake_which),
            patch(
                "bearings.api.routes_fs.asyncio.create_subprocess_exec",
                side_effect=fake_exec,
            ),
        ]
        for c in self._ctxs:
            c.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        for c in reversed(self._ctxs):
            c.__exit__(*exc)


def test_pick_file_success_zenity(client: TestClient) -> None:
    """zenity single-pick emits one trailing-newline path; the route
    strips the newline and returns it in both `path` and `paths`.
    """
    proc = _FakeProc(b"/home/dave/notes.md\n", 0)
    with _PickerPatch(which_binary="zenity", proc=proc):
        resp = client.post("/api/fs/pick", params={"mode": "file"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cancelled"] is False
    assert body["path"] == "/home/dave/notes.md"
    assert body["paths"] == ["/home/dave/notes.md"]


def test_pick_file_cancelled_nonzero_exit(client: TestClient) -> None:
    """Both zenity and kdialog exit non-zero on user cancel. The route
    must NOT surface an error — it's a normal UX outcome and the UI
    no-ops on `cancelled: true`.
    """
    proc = _FakeProc(b"", 1)
    with _PickerPatch(which_binary="zenity", proc=proc):
        resp = client.post("/api/fs/pick", params={"mode": "file"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"path": None, "paths": [], "cancelled": True}


def test_pick_file_multiple_nul_separated(client: TestClient) -> None:
    """zenity --multiple with `--separator=\\0` returns NUL-delimited
    paths. The route detects the NUL and splits on it so paths
    containing newlines parse cleanly.
    """
    stdout = b"/a/one.txt\x00/a/two.txt\x00/a/three.txt\n"
    proc = _FakeProc(stdout, 0)
    with _PickerPatch(which_binary="zenity", proc=proc):
        resp = client.post(
            "/api/fs/pick",
            params={"mode": "file", "multiple": "true"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cancelled"] is False
    assert body["paths"] == ["/a/one.txt", "/a/two.txt", "/a/three.txt"]
    # `path` mirrors the first pick for single-select consumers.
    assert body["path"] == "/a/one.txt"


def test_pick_directory_kdialog(client: TestClient) -> None:
    """`mode=directory` switches kdialog into `--getexistingdirectory`.
    We verify the route accepts the mode and returns the single path
    kdialog emits; multi-select is silently ignored for directories.
    """
    proc = _FakeProc(b"/home/dave/Projects\n", 0)
    with _PickerPatch(which_binary="kdialog", proc=proc):
        resp = client.post(
            "/api/fs/pick",
            params={"mode": "directory", "multiple": "true"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cancelled"] is False
    assert body["paths"] == ["/home/dave/Projects"]


def test_pick_501_when_no_picker_installed(client: TestClient) -> None:
    """Neither zenity nor kdialog on PATH → 501 with an actionable
    message so the UI can tell the user what to install rather than
    silently failing.
    """
    with _PickerPatch(which_binary=None, proc=None):
        resp = client.post("/api/fs/pick", params={"mode": "file"})
    assert resp.status_code == 501
    assert "zenity" in resp.json()["detail"] or "kdialog" in resp.json()["detail"]


def test_pick_504_on_timeout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An abandoned dialog can't hold a request handler forever. We
    stub the timeout down to a fraction of a second and use a hanging
    fake process so `wait_for` raises.
    """
    monkeypatch.setattr("bearings.api.routes_fs._PICK_TIMEOUT_SECONDS", 0.05)
    proc = _FakeProc(b"", 0, hang=True)
    with _PickerPatch(which_binary="zenity", proc=proc):
        resp = client.post("/api/fs/pick", params={"mode": "file"})
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"]
