"""Integration tests for ``bearings.web.routes.routing`` (spec §9 routing).

Boots the real ASGI app via :class:`fastapi.testclient.TestClient`
with a freshly-bootstrapped DB; covers all 10 routing/preview
endpoints end-to-end.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.agent.quota import QuotaSnapshot, record_snapshot
from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    """App with fresh DB + a seed tag for tag-rule tests."""
    db_path = tmp_path / "routing_api.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        loop.run_until_complete(_seed_tag(conn))
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


async def _seed_tag(conn: aiosqlite.Connection) -> None:
    iso = "2026-04-28T12:00:00.000000+00:00"
    await conn.execute(
        "INSERT INTO tags (id, name, color, default_model, working_dir, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "bearings/architect", None, "opus", "/tmp/wd", iso, iso),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# 1. GET /api/tags/{id}/routing
# ---------------------------------------------------------------------------


def test_list_tag_rules_empty(app_client: TestClient) -> None:
    """No rules attached → empty list."""
    response = app_client.get("/api/tags/1/routing")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# 2. POST /api/tags/{id}/routing
# ---------------------------------------------------------------------------


def test_create_tag_rule_returns_201(app_client: TestClient) -> None:
    """POST a tag rule → 201 with shaped body."""
    response = app_client.post(
        "/api/tags/1/routing",
        json={
            "priority": 50,
            "match_type": "keyword",
            "match_value": "design",
            "executor_model": "opus",
            "advisor_model": None,
            "advisor_max_uses": 0,
            "effort_level": "xhigh",
            "reason": "Design discussions go to Opus",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tag_id"] == 1
    assert body["match_type"] == "keyword"
    assert body["executor_model"] == "opus"


def test_create_tag_rule_422_on_bad_shape(app_client: TestClient) -> None:
    """Unknown match_type → 422."""
    response = app_client.post(
        "/api/tags/1/routing",
        json={
            "match_type": "bogus_type",
            "match_value": "x",
            "executor_model": "sonnet",
            "reason": "test",
        },
    )
    assert response.status_code == 422


def test_create_tag_rule_404_on_missing_tag(app_client: TestClient) -> None:
    """POST to non-existent tag_id → 404 'tag not found', not 409.

    Regression for finding feature-3-005: the IntegrityError catch must
    distinguish the FK violation (tag absent) from other constraint
    violations and map only the FK case to 404.
    """
    response = app_client.post(
        "/api/tags/9999/routing",
        json={
            "match_type": "always",
            "match_value": None,
            "executor_model": "sonnet",
            "reason": "test missing tag",
        },
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 3. PATCH /api/routing/{id}
# ---------------------------------------------------------------------------


def test_patch_tag_rule_returns_updated_shape(app_client: TestClient) -> None:
    """PATCH replaces mutable fields."""
    create = app_client.post(
        "/api/tags/1/routing",
        json={
            "match_type": "always",
            "match_value": None,
            "executor_model": "sonnet",
            "advisor_model": "opus",
            "reason": "default workhorse for tag",
        },
    )
    rule_id = create.json()["id"]
    response = app_client.patch(
        f"/api/routing/{rule_id}",
        json={
            "priority": 200,
            "enabled": False,
            "match_type": "always",
            "match_value": None,
            "executor_model": "haiku",
            "advisor_model": "opus",
            "advisor_max_uses": 3,
            "effort_level": "low",
            "reason": "switched to haiku",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["executor_model"] == "haiku"


def test_patch_tag_rule_404_when_missing(app_client: TestClient) -> None:
    """PATCH on missing rule → 404."""
    response = app_client.patch(
        "/api/routing/99999",
        json={
            "priority": 100,
            "enabled": True,
            "match_type": "always",
            "match_value": None,
            "executor_model": "sonnet",
            "advisor_model": "opus",
            "advisor_max_uses": 5,
            "effort_level": "auto",
            "reason": "unused",
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. DELETE /api/routing/{id}
# ---------------------------------------------------------------------------


def test_delete_tag_rule_returns_204(app_client: TestClient) -> None:
    """DELETE → 204 on success, 404 on missing."""
    create = app_client.post(
        "/api/tags/1/routing",
        json={
            "match_type": "always",
            "match_value": None,
            "executor_model": "sonnet",
            "advisor_model": "opus",
            "reason": "to delete",
        },
    )
    rule_id = create.json()["id"]
    response = app_client.delete(f"/api/routing/{rule_id}")
    assert response.status_code == 204
    assert app_client.delete(f"/api/routing/{rule_id}").status_code == 404


# ---------------------------------------------------------------------------
# 5. PATCH /api/tags/{id}/routing/reorder
# ---------------------------------------------------------------------------


def test_reorder_tag_rules_restamps_priority(app_client: TestClient) -> None:
    """Re-order assigns priority = (index+1)*10."""
    rule_a = app_client.post(
        "/api/tags/1/routing",
        json={
            "priority": 100,
            "match_type": "always",
            "match_value": None,
            "executor_model": "sonnet",
            "advisor_model": "opus",
            "reason": "A",
        },
    ).json()
    rule_b = app_client.post(
        "/api/tags/1/routing",
        json={
            "priority": 200,
            "match_type": "always",
            "match_value": None,
            "executor_model": "sonnet",
            "advisor_model": "opus",
            "reason": "B",
        },
    ).json()
    response = app_client.patch(
        "/api/tags/1/routing/reorder",
        json={"ids_in_priority_order": [rule_b["id"], rule_a["id"]]},
    )
    assert response.status_code == 200
    body = response.json()
    # rule_b should now have priority 10, rule_a priority 20.
    by_id = {row["id"]: row for row in body}
    assert by_id[rule_b["id"]]["priority"] == 10
    assert by_id[rule_a["id"]]["priority"] == 20


# ---------------------------------------------------------------------------
# 6. GET /api/routing/system
# ---------------------------------------------------------------------------


def test_list_system_rules_returns_seeded_set(app_client: TestClient) -> None:
    """The seven default seeded system rules ship with the schema."""
    response = app_client.get("/api/routing/system")
    assert response.status_code == 200
    rows = response.json()
    seeded_count = sum(1 for r in rows if r["seeded"])
    assert seeded_count == 7


# ---------------------------------------------------------------------------
# 7. POST /api/routing/system
# ---------------------------------------------------------------------------


def test_create_system_rule_returns_201_seeded_false(
    app_client: TestClient,
) -> None:
    """User-added system rule has ``seeded = False``."""
    response = app_client.post(
        "/api/routing/system",
        json={
            "priority": 500,
            "match_type": "keyword",
            "match_value": "frontend",
            "executor_model": "haiku",
            "advisor_model": "opus",
            "advisor_max_uses": 3,
            "effort_level": "low",
            "reason": "Frontend tasks → haiku",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["seeded"] is False
    assert body["priority"] == 500


# ---------------------------------------------------------------------------
# 8. PATCH /api/routing/system/{id}
# ---------------------------------------------------------------------------


def test_patch_system_rule_preserves_seeded_flag(
    app_client: TestClient,
) -> None:
    """Updating a seeded rule keeps ``seeded=True``."""
    list_resp = app_client.get("/api/routing/system")
    seeded_rule = next(r for r in list_resp.json() if r["seeded"])
    response = app_client.patch(
        f"/api/routing/system/{seeded_rule['id']}",
        json={
            "priority": seeded_rule["priority"],
            "enabled": False,
            "match_type": seeded_rule["match_type"],
            "match_value": seeded_rule["match_value"],
            "executor_model": seeded_rule["executor_model"],
            "advisor_model": seeded_rule["advisor_model"],
            "advisor_max_uses": seeded_rule["advisor_max_uses"],
            "effort_level": seeded_rule["effort_level"],
            "reason": "tuned by user",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["seeded"] is True
    assert body["enabled"] is False
    assert body["reason"] == "tuned by user"


# ---------------------------------------------------------------------------
# 9. DELETE /api/routing/system/{id}
# ---------------------------------------------------------------------------


def test_delete_system_rule_returns_204(app_client: TestClient) -> None:
    """DELETE system rule → 204 on success."""
    create = app_client.post(
        "/api/routing/system",
        json={
            "priority": 600,
            "match_type": "always",
            "match_value": None,
            "executor_model": "sonnet",
            "advisor_model": "opus",
            "reason": "to delete",
        },
    ).json()
    response = app_client.delete(f"/api/routing/system/{create['id']}")
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# 10. POST /api/routing/preview
# ---------------------------------------------------------------------------


def test_preview_runs_evaluate_against_seeded_rules(
    app_client: TestClient,
) -> None:
    """Preview against the seeded rules — short message → haiku."""
    response = app_client.post(
        "/api/routing/preview",
        json={"tags": [], "message": "fix"},
    )
    assert response.status_code == 200
    body = response.json()
    # Spec §3 priority-50: ``length_lt 80`` → haiku.
    assert body["executor"] == "haiku"
    assert body["source"] == "system_rule"
    assert body["matched_rule_id"] is not None
    assert body["quota_downgrade_applied"] is False


def test_preview_quota_downgrade_applied_flag_set_when_guard_fires(
    tmp_path: Path,
) -> None:
    """Preview with a high-overall snapshot reports the guard fired."""
    db_path = tmp_path / "preview_quota.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        # Seed a snapshot above threshold.
        await record_snapshot(
            conn,
            QuotaSnapshot(
                captured_at=int(time.time()),
                overall_used_pct=0.85,
                sonnet_used_pct=0.20,
                overall_resets_at=None,
                sonnet_resets_at=None,
                raw_payload="{}",
            ),
        )
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            # Architect keyword → opus solo per priority-10 rule.
            # With overall=0.85 the guard downgrades opus→sonnet.
            response = client.post(
                "/api/routing/preview",
                json={"tags": [], "message": "design system architect changes"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["executor"] == "sonnet"
            assert body["quota_downgrade_applied"] is True
            assert body["source"] == "quota_downgrade"
        loop.run_until_complete(conn.close())
    finally:
        loop.close()
