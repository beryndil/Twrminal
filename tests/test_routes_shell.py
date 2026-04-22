"""Tests for `/api/shell/open` and the argv builder that backs it.

Covers Phase 4a.1 of docs/context-menu-plan.md. The dispatcher uses
`subprocess.Popen` with an argv list, so we monkeypatch Popen to
record the argv without actually spawning anything — the tests assert
the placeholder-substitution contract and the "400 when unconfigured"
failure mode without ever launching an editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bearings.api.routes_shell import _build_argv
from bearings.config import Settings, ShellCfg, StorageCfg, UploadsCfg
from bearings.server import create_app

# ---- pure argv builder ------------------------------------------------


def test_build_argv_appends_path_when_no_placeholder() -> None:
    """The common case — `code` or `xdg-open` or similar — just wants
    the path appended. No placeholder, no substitution, path lands as
    the last positional."""
    argv = _build_argv(["code"], "/home/dave/Projects/Bearings")
    assert argv == ["code", "/home/dave/Projects/Bearings"]


def test_build_argv_substitutes_placeholder() -> None:
    """Power users with flags need `{path}` mid-argv. Template
    substitution preserves surrounding args exactly."""
    argv = _build_argv(
        ["alacritty", "--working-directory", "{path}"],
        "/tmp/project",
    )
    assert argv == ["alacritty", "--working-directory", "/tmp/project"]


def test_build_argv_substitutes_multiple_placeholders() -> None:
    """Pathological but well-defined: if the user wires `{path}` into
    two args (e.g. `-C {path} status {path}`), both get replaced."""
    argv = _build_argv(["wrap", "{path}", "--also", "{path}"], "/a")
    assert argv == ["wrap", "/a", "--also", "/a"]


def test_build_argv_preserves_path_with_spaces() -> None:
    """Argv-list form is exactly the defense against quoting bugs —
    a path containing whitespace lands as a single arg untouched."""
    argv = _build_argv(["code"], "/home/dave/My Projects/Foo")
    assert argv == ["code", "/home/dave/My Projects/Foo"]


def test_build_argv_handles_curly_braces_in_path() -> None:
    """Paths with literal `{...}` segments don't trip the
    placeholder — we use `str.replace` on the exact token `{path}`, so
    `{other}` stays as-is."""
    argv = _build_argv(["editor"], "/tmp/{weird}/file")
    assert argv == ["editor", "/tmp/{weird}/file"]


# ---- route wiring -----------------------------------------------------


class _RecordedPopen:
    """Drop-in Popen replacement that records argv+kwargs instead of
    spawning. The tests assert against these recordings rather than
    observing real-world side effects."""

    calls: list[tuple[list[str], dict[str, Any]]] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.calls.append((list(argv), kwargs))


@pytest.fixture(autouse=True)
def _reset_popen_recorder() -> None:
    _RecordedPopen.calls.clear()


def _client_with_shell(tmp_path: Path, **shell_fields: Any) -> TestClient:
    """Build a TestClient wired to a Settings whose `[shell]` block is
    pre-filled with the test's commands. Each test configures only the
    fields it exercises so the others stay at their `None` default and
    exercise the "unconfigured" branch."""
    cfg = Settings(
        storage=StorageCfg(db_path=tmp_path / "db.sqlite"),
        uploads=UploadsCfg(upload_dir=tmp_path / "uploads"),
        shell=ShellCfg(**shell_fields),
    )
    cfg.config_file = tmp_path / "config.toml"
    app = create_app(cfg)
    return TestClient(app)


def test_open_editor_spawns_configured_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bearings.api.routes_shell.subprocess.Popen", _RecordedPopen)
    with _client_with_shell(tmp_path, editor_command=["code"]) as client:
        resp = client.post(
            "/api/shell/open",
            json={"kind": "editor", "path": "/tmp/proj"},
        )
    assert resp.status_code == 204
    assert len(_RecordedPopen.calls) == 1
    argv, kwargs = _RecordedPopen.calls[0]
    assert argv == ["code", "/tmp/proj"]
    # Detach + discard streams so the GUI app outlives the request.
    assert kwargs.get("start_new_session") is True


def test_open_terminal_with_placeholder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bearings.api.routes_shell.subprocess.Popen", _RecordedPopen)
    with _client_with_shell(
        tmp_path,
        terminal_command=["alacritty", "--working-directory", "{path}"],
    ) as client:
        resp = client.post(
            "/api/shell/open",
            json={"kind": "terminal", "path": "/home/dave"},
        )
    assert resp.status_code == 204
    argv, _ = _RecordedPopen.calls[0]
    assert argv == ["alacritty", "--working-directory", "/home/dave"]


def test_open_returns_400_when_kind_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bearings.api.routes_shell.subprocess.Popen", _RecordedPopen)
    with _client_with_shell(tmp_path, editor_command=["code"]) as client:
        # `terminal_command` is still None — kind='terminal' hits the
        # unconfigured branch and the body names the exact config key.
        resp = client.post(
            "/api/shell/open",
            json={"kind": "terminal", "path": "/tmp"},
        )
    assert resp.status_code == 400
    assert "shell.terminal_command" in resp.json()["detail"]
    assert _RecordedPopen.calls == []


def test_open_returns_422_on_unknown_kind(tmp_path: Path) -> None:
    """Literal type on the Pydantic model rejects unknown kinds before
    they reach the dispatcher."""
    with _client_with_shell(tmp_path, editor_command=["code"]) as client:
        resp = client.post(
            "/api/shell/open",
            json={"kind": "bogus", "path": "/tmp"},
        )
    assert resp.status_code == 422


def test_open_returns_422_on_empty_path(tmp_path: Path) -> None:
    with _client_with_shell(tmp_path, editor_command=["code"]) as client:
        resp = client.post(
            "/api/shell/open",
            json={"kind": "editor", "path": ""},
        )
    assert resp.status_code == 422


def test_open_translates_file_not_found_to_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Misconfigured binary (e.g. typo'd `cdoe` for `code`) surfaces
    as 400 so the frontend tooltip can nudge the user to fix
    config.toml, rather than 500 which reads as server bug."""

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise FileNotFoundError(2, "No such file or directory: 'missing-bin'")

    monkeypatch.setattr("bearings.api.routes_shell.subprocess.Popen", _boom)
    with _client_with_shell(tmp_path, editor_command=["missing-bin"]) as client:
        resp = client.post(
            "/api/shell/open",
            json={"kind": "editor", "path": "/tmp"},
        )
    assert resp.status_code == 400
    assert "missing-bin" in resp.json()["detail"]


def test_open_all_five_kinds_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every advertised kind in the plan's contract lands on its
    configured command — regression guard against the `_KIND_TO_FIELD`
    map drifting out of sync with `ShellKind`."""
    monkeypatch.setattr("bearings.api.routes_shell.subprocess.Popen", _RecordedPopen)
    with _client_with_shell(
        tmp_path,
        editor_command=["e"],
        terminal_command=["t"],
        file_explorer_command=["f"],
        git_gui_command=["g"],
        claude_cli_command=["c"],
    ) as client:
        for kind in ["editor", "terminal", "file_explorer", "git_gui", "claude_cli"]:
            resp = client.post(
                "/api/shell/open",
                json={"kind": kind, "path": "/p"},
            )
            assert resp.status_code == 204, (kind, resp.text)
    # Binaries land in the same order the loop dispatched — one per kind.
    assert [call[0][0] for call in _RecordedPopen.calls] == ["e", "t", "f", "g", "c"]
