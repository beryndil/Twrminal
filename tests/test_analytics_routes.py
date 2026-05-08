"""Integration tests for ``bearings.web.routes.analytics`` — Phase 4.

Covers ``BEARINGS_ANALYTICS_v1.md`` §9 (all 13 endpoints) per the Phase 4
acceptance criteria.

Test inventory
--------------
Logging (§9.1):
1.  POST /api/analytics/turns — happy path; 201 Created.
2.  POST /api/analytics/turns — duplicate (session_id, turn_index) is idempotent.
3.  POST /api/analytics/plug-blocks/batch — happy path; 201 Created.
4.  POST /api/analytics/plug-blocks/batch — unknown block_type → 422.

Reads (§9.2):
5.  GET /api/analytics/bucket/current — no snapshot → null windows, as_of set.
6.  GET /api/analytics/bucket/current — with snapshot → windows populated.
7.  GET /api/analytics/attribution — empty DB → empty list.
8.  GET /api/analytics/attribution — unknown window → 422.
9.  GET /api/analytics/attribution — group_by != 'tag' → 422.
10. GET /api/analytics/redundancy — empty DB → empty list.
11. GET /api/analytics/redundancy — last_n out of range → 422.
12. GET /api/analytics/redundancy — unknown tag → 404.
13. GET /api/analytics/redundancy — unknown block_types → 422.
14. GET /api/analytics/plug-blocks/{hash} — happy path.
15. GET /api/analytics/plug-blocks/{hash} — missing → 404.
16. GET /api/analytics/plug-blocks/{hash}/versions — single block (no source_path).
17. GET /api/analytics/plug-blocks/{hash}/versions — missing → 404.
18. GET /api/analytics/sessions/{id}/plug-summary — empty plug → green status.
19. GET /api/analytics/sessions/{id}/plug-summary — session missing → 404.

Actions (§9.3):
20. POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory — happy path.
21. POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory — bad hash → 404.
22. POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory — bad tag → 404.
23. POST /api/analytics/plug-blocks/{hash}/promote-to-on-open — happy path.
24. POST /api/analytics/plug-blocks/{hash}/promote-to-on-open — bad hash → 404.
25. POST /api/analytics/plug-blocks/{hash}/promote-to-on-open — bad dir → 422.
26. POST /api/analytics/draft-new-session — happy path.
27. POST /api/analytics/draft-new-session — missing source → 404.
28. POST /api/analytics/sessions/from-draft — happy path; 201.
29. POST /api/analytics/sessions/from-draft — unknown tag → 404.
30. POST /api/analytics/warnings/suppress — happy path; idempotent.
31. POST /api/analytics/warnings/suppress — bad warning_type → 422.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.db import get_connection_factory, load_schema
from bearings.db.analytics import insert_bucket_snapshot
from bearings.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SESS_ID = "ses_analytics_route_test_aaaa"
_MODEL = "claude-sonnet-4-6"
_HASH_A = "a" * 64
_HASH_B = "b" * 64


async def _bootstrapped(database_path: Path) -> aiosqlite.Connection:
    """Open a fresh DB, apply schema, and insert a seed session + tag."""
    factory = get_connection_factory(database_path)
    conn = await factory().__aenter__()
    await load_schema(conn)
    await conn.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, created_at, updated_at) "
        "VALUES (?, 'chat', 'Route test session', '/tmp', ?, "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (_SESS_ID, _MODEL),
    )
    await conn.execute(
        "INSERT INTO tags (name, class, created_at, updated_at) "
        "VALUES ('infra', 'general', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    await conn.commit()
    return conn


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "analytics_routes_test.db"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    """TestClient backed by a real bootstrapped SQLite DB."""

    async def _build() -> aiosqlite.Connection:
        return await _bootstrapped(db_path)

    import asyncio

    conn = asyncio.get_event_loop().run_until_complete(_build())
    app = create_app(db_connection=conn)
    with TestClient(app) as tc:
        yield tc


# ---------------------------------------------------------------------------
# §9.1 Logging endpoints
# ---------------------------------------------------------------------------


class TestLogTurn:
    """POST /api/analytics/turns."""

    def test_happy_path_201(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/turns",
            json={
                "session_id": _SESS_ID,
                "turn_index": 0,
                "model": _MODEL,
                "input_tokens": 100,
                "output_tokens": 50,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "ok"

    def test_duplicate_turn_is_idempotent(self, client: TestClient) -> None:
        payload = {
            "session_id": _SESS_ID,
            "turn_index": 1,
            "model": _MODEL,
            "input_tokens": 200,
            "output_tokens": 80,
        }
        r1 = client.post("/api/analytics/turns", json=payload)
        r2 = client.post("/api/analytics/turns", json=payload)
        assert r1.status_code == 201
        assert r2.status_code == 201

    def test_missing_required_field_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/turns",
            json={"session_id": _SESS_ID, "turn_index": 0},
        )
        assert resp.status_code == 422


class TestLogPlugBlocksBatch:
    """POST /api/analytics/plug-blocks/batch."""

    def test_happy_path_201(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/plug-blocks/batch",
            json={
                "session_id": _SESS_ID,
                "model": _MODEL,
                "blocks": [
                    {
                        "hash": _HASH_A,
                        "block_type": "claude_md",
                        "content": "# CLAUDE.md\nThis is a test.",
                        "source_path": "~/.claude/CLAUDE.md",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["inserted"] == 1

    def test_unknown_block_type_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/plug-blocks/batch",
            json={
                "session_id": _SESS_ID,
                "model": _MODEL,
                "blocks": [
                    {
                        "hash": _HASH_A,
                        "block_type": "not_a_real_type",
                        "content": "x",
                    }
                ],
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# §9.2 Read endpoints
# ---------------------------------------------------------------------------


class TestBucketCurrent:
    """GET /api/analytics/bucket/current."""

    def test_no_snapshot_returns_null_windows(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/bucket/current")
        assert resp.status_code == 200
        body = resp.json()
        assert body["five_hour"] is None
        assert body["weekly"] is None
        assert isinstance(body["as_of"], int)

    def test_with_snapshot_returns_windows(self, db_path: Path, client: TestClient) -> None:
        import asyncio

        async def _insert_snap() -> None:
            factory = get_connection_factory(db_path)
            conn = await factory().__aenter__()
            await load_schema(conn)
            await insert_bucket_snapshot(
                conn,
                five_hour_used=80_000,
                five_hour_limit=200_000,
                weekly_used=1_500_000,
                weekly_limit=5_000_000,
            )
            await conn.__aexit__(None, None, None)

        asyncio.get_event_loop().run_until_complete(_insert_snap())
        resp = client.get("/api/analytics/bucket/current")
        assert resp.status_code == 200
        body = resp.json()
        assert body["five_hour"]["used"] == 80_000
        assert body["five_hour"]["percent"] == pytest.approx(40.0, abs=0.1)
        assert body["weekly"]["used"] == 1_500_000


class TestAttribution:
    """GET /api/analytics/attribution."""

    def test_empty_db_returns_empty_list(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/attribution")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_unknown_window_422(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/attribution?window=fortnight")
        assert resp.status_code == 422

    def test_unknown_group_by_422(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/attribution?group_by=model")
        assert resp.status_code == 422


class TestRedundancy:
    """GET /api/analytics/redundancy."""

    def test_empty_db_returns_empty_list(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/redundancy")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_last_n_below_min_422(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/redundancy?last_n=3")
        assert resp.status_code == 422

    def test_last_n_above_max_422(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/redundancy?last_n=201")
        assert resp.status_code == 422

    def test_unknown_tag_404(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/redundancy?tag=nonexistent_tag")
        assert resp.status_code == 404

    def test_unknown_block_types_422(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/redundancy?block_types=not_a_type")
        assert resp.status_code == 422


class TestPlugBlockDetail:
    """GET /api/analytics/plug-blocks/{hash}."""

    def test_happy_path(self, client: TestClient) -> None:
        client.post(
            "/api/analytics/plug-blocks/batch",
            json={
                "session_id": _SESS_ID,
                "model": _MODEL,
                "blocks": [{"hash": _HASH_A, "block_type": "claude_md", "content": "# Hello"}],
            },
        )
        resp = client.get(f"/api/analytics/plug-blocks/{_HASH_A}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["hash"] == _HASH_A
        assert body["block_type"] == "claude_md"

    def test_missing_returns_404(self, client: TestClient) -> None:
        resp = client.get(f"/api/analytics/plug-blocks/{'z' * 64}")
        assert resp.status_code == 404


class TestPlugBlockVersions:
    """GET /api/analytics/plug-blocks/{hash}/versions."""

    def test_single_version_no_source_path(self, client: TestClient) -> None:
        client.post(
            "/api/analytics/plug-blocks/batch",
            json={
                "session_id": _SESS_ID,
                "model": _MODEL,
                "blocks": [{"hash": _HASH_A, "block_type": "claude_md", "content": "v1"}],
            },
        )
        resp = client.get(f"/api/analytics/plug-blocks/{_HASH_A}/versions")
        assert resp.status_code == 200
        versions = resp.json()
        assert len(versions) == 1
        assert versions[0]["hash"] == _HASH_A
        assert versions[0]["unified_diff"] is None

    def test_missing_returns_404(self, client: TestClient) -> None:
        resp = client.get(f"/api/analytics/plug-blocks/{'z' * 64}/versions")
        assert resp.status_code == 404


class TestSessionPlugSummary:
    """GET /api/analytics/sessions/{id}/plug-summary."""

    def test_empty_plug_returns_green(self, client: TestClient) -> None:
        resp = client.get(f"/api/analytics/sessions/{_SESS_ID}/plug-summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_tokens"] == 0
        assert body["status"] == "green"
        assert body["blocks"] == []

    def test_missing_session_404(self, client: TestClient) -> None:
        resp = client.get("/api/analytics/sessions/ses_does_not_exist/plug-summary")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# §9.3 Action endpoints
# ---------------------------------------------------------------------------


class TestPromoteToTagMemory:
    """POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory."""

    def _seed_block(self, client: TestClient) -> None:
        client.post(
            "/api/analytics/plug-blocks/batch",
            json={
                "session_id": _SESS_ID,
                "model": _MODEL,
                "blocks": [{"hash": _HASH_A, "block_type": "claude_md", "content": "x"}],
            },
        )

    def test_happy_path(self, client: TestClient) -> None:
        self._seed_block(client)
        resp = client.post(
            f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-tag-memory",
            json={"tag": "infra", "memory_content": "Remember this."},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tag"] == "infra"
        assert isinstance(body["memory_id"], int)

    def test_bad_hash_404(self, client: TestClient) -> None:
        resp = client.post(
            f"/api/analytics/plug-blocks/{'z' * 64}/promote-to-tag-memory",
            json={"tag": "infra", "memory_content": "x"},
        )
        assert resp.status_code == 404

    def test_bad_tag_404(self, client: TestClient) -> None:
        self._seed_block(client)
        resp = client.post(
            f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-tag-memory",
            json={"tag": "nonexistent_tag", "memory_content": "x"},
        )
        assert resp.status_code == 404

    def test_idempotent_double_promote(self, client: TestClient) -> None:
        """Re-promoting the same block to the same tag returns the same memory id."""
        self._seed_block(client)
        payload = {"tag": "infra", "memory_content": "Remember this."}
        r1 = client.post(
            f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-tag-memory", json=payload
        )
        r2 = client.post(
            f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-tag-memory", json=payload
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["memory_id"] == r2.json()["memory_id"]


class TestPromoteToOnOpen:
    """POST /api/analytics/plug-blocks/{hash}/promote-to-on-open."""

    def _seed_block(self, client: TestClient) -> None:
        client.post(
            "/api/analytics/plug-blocks/batch",
            json={
                "session_id": _SESS_ID,
                "model": _MODEL,
                "blocks": [{"hash": _HASH_A, "block_type": "claude_md", "content": "x"}],
            },
        )

    def test_happy_path(self, client: TestClient, tmp_path: Path) -> None:
        self._seed_block(client)
        work_dir = tmp_path / "myproject"
        work_dir.mkdir()
        resp = client.post(
            f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-on-open",
            json={"working_directory": str(work_dir), "snippet": "echo hello"},
        )
        assert resp.status_code == 200
        body = resp.json()
        on_open = Path(body["on_open_sh_path"])
        assert on_open.exists()
        assert "echo hello" in on_open.read_text()

    def test_bad_hash_404(self, client: TestClient, tmp_path: Path) -> None:
        resp = client.post(
            f"/api/analytics/plug-blocks/{'z' * 64}/promote-to-on-open",
            json={"working_directory": str(tmp_path), "snippet": "x"},
        )
        assert resp.status_code == 404

    def test_nonexistent_dir_422(self, client: TestClient) -> None:
        self._seed_block(client)
        resp = client.post(
            f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-on-open",
            json={"working_directory": "/no/such/directory/exists", "snippet": "x"},
        )
        assert resp.status_code == 422

    def test_idempotent_double_promote(self, client: TestClient, tmp_path: Path) -> None:
        """Re-promoting the same snippet must not duplicate the content."""
        self._seed_block(client)
        work_dir = tmp_path / "myproject"
        work_dir.mkdir()
        payload = {"working_directory": str(work_dir), "snippet": "echo idempotent"}
        client.post(f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-on-open", json=payload)
        client.post(f"/api/analytics/plug-blocks/{_HASH_A}/promote-to-on-open", json=payload)
        on_open = work_dir / ".bearings" / "on_open.sh"
        content = on_open.read_text()
        assert content.count("echo idempotent") == 1


class TestDraftNewSession:
    """POST /api/analytics/draft-new-session."""

    def test_happy_path(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/draft-new-session",
            json={"source_session_id": _SESS_ID, "carry_tags": ["infra"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["draft_plug"], str)
        assert len(body["draft_plug"]) > 0
        assert isinstance(body["estimated_tokens"], int)
        assert "input" in body["draft_cost_tokens"]

    def test_missing_source_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/draft-new-session",
            json={"source_session_id": "ses_does_not_exist"},
        )
        assert resp.status_code == 404


class TestSessionFromDraft:
    """POST /api/analytics/sessions/from-draft."""

    def test_happy_path_201(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/sessions/from-draft",
            json={
                "draft_plug": "# New session\nPick up here.",
                "tags": [],
                "working_directory": "/tmp",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["session_id"].startswith("ses_")

    def test_with_valid_tag(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/sessions/from-draft",
            json={
                "draft_plug": "# Session",
                "tags": ["infra"],
                "working_directory": "/tmp",
            },
        )
        assert resp.status_code == 201

    def test_unknown_tag_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/sessions/from-draft",
            json={
                "draft_plug": "# Session",
                "tags": ["nonexistent_tag"],
                "working_directory": "/tmp",
            },
        )
        assert resp.status_code == 404


class TestSuppressWarning:
    """POST /api/analytics/warnings/suppress."""

    def _seed_block(self, client: TestClient) -> None:
        """Insert _HASH_A into plug_blocks (required by the FK on suppressed_warnings)."""
        client.post(
            "/api/analytics/plug-blocks/batch",
            json={
                "session_id": _SESS_ID,
                "model": _MODEL,
                "blocks": [{"hash": _HASH_A, "block_type": "claude_md", "content": "x"}],
            },
        )

    def test_happy_path(self, client: TestClient) -> None:
        self._seed_block(client)
        resp = client.post(
            "/api/analytics/warnings/suppress",
            json={"block_hash": _HASH_A, "warning_type": "yellow_length"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_idempotent_double_suppress(self, client: TestClient) -> None:
        self._seed_block(client)
        payload = {"block_hash": _HASH_A, "warning_type": "red_length"}
        r1 = client.post("/api/analytics/warnings/suppress", json=payload)
        r2 = client.post("/api/analytics/warnings/suppress", json=payload)
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_bad_warning_type_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/analytics/warnings/suppress",
            json={"block_hash": _HASH_A, "warning_type": "not_a_type"},
        )
        assert resp.status_code == 422
