"""Integration tests for ``bearings.web.routes.commands`` — gap-cycle-13-005.

Covers the acceptance criteria:

* ``GET /api/commands?cwd=<path>`` scopes project-level commands to the
  supplied path.
* ``GET /api/commands`` without ``cwd`` returns commands scoped to the
  server's launch directory (backward compat).
* A ``cwd`` that points at a directory with no ``.claude/commands/``
  sub-tree returns only user-level commands (no project commands).
* Project commands from different ``cwd`` values are distinct.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bearings.web.app import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """App client with no DB required — commands route is DB-free."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _make_project_command(root: Path, name: str, body: str = "") -> Path:
    """Write ``.claude/commands/<name>.md`` under *root*."""
    cmd_dir = root / ".claude" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    path = cmd_dir / f"{name}.md"
    path.write_text(body or f"# {name}\nDoes {name}.\n", encoding="utf-8")
    return path


class TestListCommandsWithCwd:
    """``GET /api/commands?cwd=<path>`` returns project commands for that path."""

    def test_project_command_present_when_cwd_matches(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        _make_project_command(tmp_path, "myproj_cmd")
        response = client.get("/api/commands", params={"cwd": str(tmp_path)})
        assert response.status_code == 200
        names = [c["name"] for c in response.json()]
        assert "myproj_cmd" in names

    def test_project_command_source_label(self, client: TestClient, tmp_path: Path) -> None:
        """Project commands carry ``source="project_commands"``."""
        _make_project_command(tmp_path, "proj_src_test")
        response = client.get("/api/commands", params={"cwd": str(tmp_path)})
        assert response.status_code == 200
        proj = [c for c in response.json() if c["name"] == "proj_src_test"]
        assert len(proj) == 1
        assert proj[0]["source"] == "project_commands"

    def test_different_cwd_returns_different_project_commands(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        dir_a = tmp_path / "session_a"
        dir_b = tmp_path / "session_b"
        dir_a.mkdir()
        dir_b.mkdir()
        _make_project_command(dir_a, "cmd_for_a")
        _make_project_command(dir_b, "cmd_for_b")

        resp_a = client.get("/api/commands", params={"cwd": str(dir_a)})
        resp_b = client.get("/api/commands", params={"cwd": str(dir_b)})
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

        names_a = {c["name"] for c in resp_a.json()}
        names_b = {c["name"] for c in resp_b.json()}

        assert "cmd_for_a" in names_a
        assert "cmd_for_a" not in names_b
        assert "cmd_for_b" in names_b
        assert "cmd_for_b" not in names_a

    def test_empty_project_dir_returns_no_project_commands(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """``cwd`` with no ``.claude/commands/`` subtree has no project entries."""
        empty_dir = tmp_path / "empty_session"
        empty_dir.mkdir()
        response = client.get("/api/commands", params={"cwd": str(empty_dir)})
        assert response.status_code == 200
        project_cmds = [c for c in response.json() if c["source"] == "project_commands"]
        assert project_cmds == []


class TestListCommandsWithoutCwd:
    """``GET /api/commands`` without ``cwd`` uses the server's launch directory."""

    def test_omitting_cwd_returns_200_list(self, client: TestClient) -> None:
        """No ``cwd`` → backward-compat: uses server cwd, always 200 + list."""
        response = client.get("/api/commands")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_empty_cwd_param_treated_as_omit(self, client: TestClient) -> None:
        """An explicit ``?cwd=`` (empty string) must not crash the endpoint."""
        response = client.get("/api/commands", params={"cwd": ""})
        # Empty string → None handling in route; should still return 200.
        # The route converts falsy string to None, so server cwd is used.
        assert response.status_code == 200
        assert isinstance(response.json(), list)
