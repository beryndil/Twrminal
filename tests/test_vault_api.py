"""Integration tests for ``bearings.web.routes.vault`` via FastAPI.

Boots the real ASGI app via :class:`fastapi.testclient.TestClient`
with a freshly-bootstrapped DB on ``app.state.db_connection`` and a
:class:`VaultCfg` whose plan-roots / todo-globs target a ``tmp_path``;
exercises the full HTTP surface — list, search, by-path, get-by-id,
plus the safety / error paths.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.config.settings import VaultCfg
from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    """Materialise a small vault layout under ``tmp_path``.

    Layout:
        plans/alpha.md           — plan with title "Alpha"
        plans/beta.md            — plan, no title (slug-fallback row)
        projects/proj1/TODO.md   — todo with title "Proj1 todos"
    """
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "alpha.md").write_text(
        "# Alpha\n\nbody alpha with token = realsecretvalueXYZ\n",
        encoding="utf-8",
    )
    (plans / "beta.md").write_text(
        "no title here\nbeta line two\nbeta line three needle\n",
        encoding="utf-8",
    )
    proj = tmp_path / "projects" / "proj1"
    proj.mkdir(parents=True)
    (proj / "TODO.md").write_text(
        "# Proj1 todos\n\n- item one\n- needle item two\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def app_client(vault_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """Boot the app with a fresh DB connection + vault cfg."""
    db_dir = tmp_path_factory.mktemp("dbdir")
    db_path = db_dir / "vault_routes.db"
    cfg = VaultCfg(
        plan_roots=(vault_root / "plans",),
        todo_globs=(str(vault_root / "projects" / "**" / "TODO.md"),),
    )

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
            vault_cfg=cfg,
        )
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_get_vault_returns_buckets(app_client: TestClient) -> None:
    response = app_client.get("/api/vault")
    assert response.status_code == 200
    body = response.json()
    plan_titles = sorted(p["title"] or p["slug"] for p in body["plans"])
    assert plan_titles == ["Alpha", "beta"]
    assert len(body["todos"]) == 1
    assert body["todos"][0]["title"] == "Proj1 todos"
    assert body["plan_roots"]
    assert body["todo_globs"]


def test_get_vault_includes_markdown_link(app_client: TestClient) -> None:
    """Paste-into-message — server-computed link comes back on each row."""
    body = app_client.get("/api/vault").json()
    alpha = next(p for p in body["plans"] if p["slug"] == "alpha")
    assert alpha["markdown_link"].startswith("[Alpha](file://")
    assert alpha["markdown_link"].endswith("/alpha.md)")


def test_get_vault_doc_returns_body_and_redactions(app_client: TestClient) -> None:
    listed = app_client.get("/api/vault").json()
    alpha_id = next(p["id"] for p in listed["plans"] if p["slug"] == "alpha")
    response = app_client.get(f"/api/vault/{alpha_id}")
    assert response.status_code == 200
    body = response.json()
    assert "body alpha" in body["body"]
    assert body["truncated"] is False
    assert body["entry"]["slug"] == "alpha"
    # The "token = realsecretvalueXYZ" pattern triggers a redaction.
    assert len(body["redactions"]) == 1
    assert body["redactions"][0]["pattern"] == "token"


def test_get_vault_doc_404_on_unknown_id(app_client: TestClient) -> None:
    response = app_client.get("/api/vault/99999")
    assert response.status_code == 404


def test_get_vault_doc_by_path_round_trip(app_client: TestClient, vault_root: Path) -> None:
    target = str((vault_root / "plans" / "alpha.md").resolve(strict=True))
    response = app_client.get("/api/vault/by-path", params={"path": target})
    assert response.status_code == 200
    body = response.json()
    assert body["entry"]["slug"] == "alpha"


def test_get_vault_doc_by_path_refuses_outside(
    app_client: TestClient, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Per vault.md — paths outside the vault are refused."""
    outsider_dir = tmp_path_factory.mktemp("outside")
    outsider = outsider_dir / "rogue.md"
    outsider.write_text("# rogue\n", encoding="utf-8")
    response = app_client.get(
        "/api/vault/by-path", params={"path": str(outsider.resolve(strict=True))}
    )
    assert response.status_code == 404


def test_get_vault_doc_by_path_refuses_nonexistent(app_client: TestClient) -> None:
    response = app_client.get("/api/vault/by-path", params={"path": "/nonexistent/path/foo.md"})
    assert response.status_code == 404


def test_search_vault_returns_hits(app_client: TestClient) -> None:
    response = app_client.get("/api/vault/search", params={"q": "needle"})
    assert response.status_code == 200
    body = response.json()
    snippets = [h["snippet"] for h in body["hits"]]
    assert any("needle" in s for s in snippets)
    # Two hits expected: beta line three + proj1 TODO line "needle item two".
    assert len(body["hits"]) == 2
    assert body["capped"] is False


def test_search_vault_blank_query_returns_empty(app_client: TestClient) -> None:
    response = app_client.get("/api/vault/search", params={"q": "  "})
    assert response.status_code == 200
    body = response.json()
    assert body["hits"] == []


def test_search_vault_missing_query_param_422(app_client: TestClient) -> None:
    """FastAPI auto-emits 422 when the required query param is absent."""
    response = app_client.get("/api/vault/search")
    assert response.status_code == 422


def test_get_vault_503_when_db_not_wired(vault_root: Path) -> None:
    """Per the streaming-only contract, no DB → every vault handler returns 503."""
    cfg = VaultCfg(plan_roots=(vault_root / "plans",), todo_globs=())
    app = create_app(heartbeat_interval_s=_HEARTBEAT_S, vault_cfg=cfg)
    with TestClient(app) as client:
        response = client.get("/api/vault")
        assert response.status_code == 503


def test_get_vault_503_when_vault_cfg_not_wired(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """_cfg() raises 503 when vault_cfg is missing from app.state.

    Regression guard for feature-7-003: the silent ``return VaultCfg()``
    fallback has been replaced with a fail-fast 503 that mirrors ``_db()``.
    ``create_app`` always sets ``app.state.vault_cfg``; this test simulates
    an external clearing of the slot after startup to confirm the guard fires.
    """
    db_path = tmp_path_factory.mktemp("cfg503") / "test.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        # Forcibly clear vault_cfg to trigger the _cfg() 503 guard.
        # create_app always sets this slot; clearing it simulates
        # the inconsistent-state the finding describes.
        app.state.vault_cfg = None
        with TestClient(app) as client:
            for path in ["/api/vault", "/api/vault/search?q=hello"]:
                resp = client.get(path)
                assert resp.status_code == 503, f"{path} should 503 when vault_cfg is None"
                assert resp.json()["detail"] == "vault_cfg not configured on app.state"
    finally:
        loop.run_until_complete(conn.close())
        loop.close()
