from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def populated_vault(tmp_path: Path) -> Path:
    """Seed the conftest-configured vault layout with a handful of
    docs. The conftest fixture points `vault.plan_roots` at
    `tmp_path/plans` and `vault.todo_globs` at
    `tmp_path/todos/**/TODO.md`; creating files there is enough to
    drive every vault route."""
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "alpha.md").write_text("# Alpha Plan\n\nRed fish body.\n")
    (plans / "beta.md").write_text("# Beta Plan\n\nBlue fish body.\n")
    # Non-markdown file — must be ignored by the index scan.
    (plans / "README.txt").write_text("not markdown")

    todo_root = tmp_path / "todos"
    (todo_root / "ProjectA").mkdir(parents=True)
    (todo_root / "ProjectA" / "TODO.md").write_text("# ProjectA TODO\n- red fish\n")
    (todo_root / "ProjectB" / "nested").mkdir(parents=True)
    (todo_root / "ProjectB" / "nested" / "TODO.md").write_text("# ProjectB Nested\n- green fish\n")
    return tmp_path


def test_index_lists_plans_and_todos(client: TestClient, populated_vault: Path) -> None:
    resp = client.get("/api/vault/index")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    plan_slugs = {p["slug"] for p in body["plans"]}
    todo_paths = {t["path"] for t in body["todos"]}
    assert plan_slugs == {"alpha", "beta"}
    # Non-markdown file is excluded; both TODO.md files are picked up
    # through the recursive glob.
    assert all(p["kind"] == "plan" for p in body["plans"])
    assert all(t["kind"] == "todo" for t in body["todos"])
    assert len(todo_paths) == 2


def test_index_extracts_titles_from_first_heading(
    client: TestClient, populated_vault: Path
) -> None:
    resp = client.get("/api/vault/index")
    plans = {p["slug"]: p for p in resp.json()["plans"]}
    assert plans["alpha"]["title"] == "Alpha Plan"
    assert plans["beta"]["title"] == "Beta Plan"


def test_index_sorts_newest_first(client: TestClient, populated_vault: Path) -> None:
    # Bump beta's mtime so it should sort ahead of alpha.
    import os
    import time

    beta = populated_vault / "plans" / "beta.md"
    future = time.time() + 10
    os.utime(beta, (future, future))
    resp = client.get("/api/vault/index")
    slugs = [p["slug"] for p in resp.json()["plans"]]
    assert slugs == ["beta", "alpha"]


def test_index_returns_empty_when_no_roots_exist(client: TestClient, tmp_path: Path) -> None:
    """No plans directory and no matching TODO globs means empty
    index, not 500. Tests the "fresh user" path."""
    # conftest points vault at `tmp_path/plans` and `tmp_path/todos`
    # but `populated_vault` hasn't been invoked, so neither exists.
    resp = client.get("/api/vault/index")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plans"] == []
    assert body["todos"] == []


def test_doc_returns_body_for_indexed_plan(client: TestClient, populated_vault: Path) -> None:
    path = populated_vault / "plans" / "alpha.md"
    resp = client.get("/api/vault/doc", params={"path": str(path)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "alpha"
    assert body["kind"] == "plan"
    assert body["title"] == "Alpha Plan"
    assert "Red fish body." in body["body"]


def test_doc_returns_body_for_indexed_todo(client: TestClient, populated_vault: Path) -> None:
    path = populated_vault / "todos" / "ProjectA" / "TODO.md"
    resp = client.get("/api/vault/doc", params={"path": str(path)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "todo"
    assert "red fish" in body["body"]


def test_doc_rejects_relative_path(client: TestClient) -> None:
    resp = client.get("/api/vault/doc", params={"path": "relative/file.md"})
    assert resp.status_code == 400


def test_doc_404s_on_missing_path(client: TestClient, populated_vault: Path) -> None:
    ghost = populated_vault / "plans" / "nope.md"
    resp = client.get("/api/vault/doc", params={"path": str(ghost)})
    assert resp.status_code == 404


def test_doc_403s_on_path_outside_vault(
    client: TestClient, populated_vault: Path, tmp_path: Path
) -> None:
    """A real file readable by the server but outside the configured
    plan_roots / todo_globs must 403, not leak its contents."""
    outside = tmp_path / "secret.md"
    outside.write_text("# Secret\nshould not be returned\n")
    resp = client.get("/api/vault/doc", params={"path": str(outside)})
    assert resp.status_code == 403


def test_doc_403s_on_traversal_attempt(
    client: TestClient, populated_vault: Path, tmp_path: Path
) -> None:
    """`..`-traversal from inside the plan root out to a sibling file
    must resolve-then-refuse. Proves the check compares real paths,
    not the raw param."""
    outside = tmp_path / "escape.md"
    outside.write_text("# Escape\n")
    crafted = populated_vault / "plans" / ".." / "escape.md"
    resp = client.get("/api/vault/doc", params={"path": str(crafted)})
    assert resp.status_code == 403


def test_search_finds_matches_across_kinds(client: TestClient, populated_vault: Path) -> None:
    resp = client.get("/api/vault/search", params={"q": "fish"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "fish"
    paths = {h["path"] for h in body["hits"]}
    # Every file in the fixture contains "fish" on at least one line.
    assert len(paths) == 4
    assert body["truncated"] is False


def test_search_is_case_insensitive(client: TestClient, populated_vault: Path) -> None:
    resp = client.get("/api/vault/search", params={"q": "FISH"})
    assert resp.status_code == 200
    assert len(resp.json()["hits"]) >= 4


def test_search_escapes_regex_metachars(client: TestClient, populated_vault: Path) -> None:
    """User query is treated as a literal substring — `r.d` must not
    match `red`. The router escapes the query before compiling."""
    resp = client.get("/api/vault/search", params={"q": "r.d"})
    assert resp.status_code == 200
    assert resp.json()["hits"] == []


def test_search_rejects_empty_query(client: TestClient, populated_vault: Path) -> None:
    resp = client.get("/api/vault/search", params={"q": ""})
    assert resp.status_code == 422
