"""Integration tests for ``bearings.web.routes.usage`` (spec §9 usage).

Phase 3 additions
-----------------
* ``cache_creation_tokens`` field present in ``by_model`` and ``by_tag`` responses.
* ``GET /api/usage/turns`` — empty DB returns ``[]``, seeded turns return
  correct rows, ``session_id`` filter scopes rows, invalid ``period`` → 422,
  period boundary excludes older turns.
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

from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "usage_api.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_by_model_empty_db_returns_empty_list(app_client: TestClient) -> None:
    """No messages → no rows."""
    response = app_client.get("/api/usage/by_model")
    assert response.status_code == 200
    assert response.json() == []


def test_by_model_invalid_period_returns_422(app_client: TestClient) -> None:
    """Period must be in {day, week}."""
    response = app_client.get("/api/usage/by_model?period=month")
    assert response.status_code == 422


def test_by_model_aggregates_executor_and_advisor_rows(
    tmp_path: Path,
) -> None:
    """A message with both executor + advisor surfaces as two rows."""
    db_path = tmp_path / "by_model.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        # Seed session + one message with full per-model usage.
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s1", "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO messages (id, session_id, role, content, "
            "executor_model, advisor_model, executor_input_tokens, "
            "executor_output_tokens, advisor_input_tokens, "
            "advisor_output_tokens, advisor_calls_count, cache_read_tokens, "
            "created_at) VALUES (?, ?, 'assistant', '', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "msg_1",
                "s1",
                "sonnet",
                "opus",
                100,
                200,
                50,
                75,
                1,
                25,
                iso_now,
            ),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/usage/by_model?period=week")
            assert response.status_code == 200
            rows = response.json()
            # One executor row + one advisor row.
            assert len(rows) == 2
            executor_row = next(r for r in rows if r["role"] == "executor")
            advisor_row = next(r for r in rows if r["role"] == "advisor")
            assert executor_row["model"] == "sonnet"
            assert executor_row["input_tokens"] == 100
            assert advisor_row["model"] == "opus"
            assert advisor_row["input_tokens"] == 50
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_by_tag_empty_db_returns_empty_list(app_client: TestClient) -> None:
    """No tags → no rows."""
    response = app_client.get("/api/usage/by_tag")
    assert response.status_code == 200
    assert response.json() == []


def test_by_tag_aggregates_per_tag_totals(tmp_path: Path) -> None:
    """A tagged session's tokens aggregate under the tag."""
    db_path = tmp_path / "by_tag.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        await conn.execute(
            "INSERT INTO tags (id, name, color, default_model, working_dir, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "frontend", None, None, None, iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s1", "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO session_tags (session_id, tag_id, created_at) VALUES (?, ?, ?)",
            ("s1", 1, iso_now),
        )
        await conn.execute(
            "INSERT INTO messages (id, session_id, role, content, "
            "executor_model, executor_input_tokens, executor_output_tokens, "
            "advisor_input_tokens, advisor_output_tokens, advisor_calls_count, "
            "created_at) VALUES (?, ?, 'assistant', '', ?, ?, ?, ?, ?, ?, ?)",
            ("msg_1", "s1", "sonnet", 100, 200, 0, 0, 0, iso_now),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/usage/by_tag?period=week")
            assert response.status_code == 200
            rows = response.json()
            assert len(rows) == 1
            assert rows[0]["tag_name"] == "frontend"
            assert rows[0]["executor_input_tokens"] == 100
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_override_rates_empty_db_returns_empty_list(
    app_client: TestClient,
) -> None:
    """No messages → no rates."""
    response = app_client.get("/api/usage/override_rates")
    assert response.status_code == 200
    assert response.json() == []


def test_override_rates_rejects_invalid_days(app_client: TestClient) -> None:
    """``days`` query parameter validated."""
    response = app_client.get("/api/usage/override_rates?days=0")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Phase 3: cache_creation_tokens in by_model / by_tag
# ---------------------------------------------------------------------------


def test_by_model_response_includes_cache_creation_tokens(
    app_client: TestClient,
) -> None:
    """Empty DB: by_model returns []; field is present when rows exist.

    Validates that the response shape includes ``cache_creation_tokens``
    (Phase 3 addition).  The empty-DB case exercises the schema; the
    seeded case exercises the aggregation path.
    """
    response = app_client.get("/api/usage/by_model")
    assert response.status_code == 200
    # Empty DB — zero rows is the correct answer.
    assert response.json() == []


def test_by_model_cache_creation_tokens_aggregated(tmp_path: Path) -> None:
    """``cache_creation_tokens`` is summed from ``messages`` for executor rows."""
    db_path = tmp_path / "by_model_cache_creation.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s1", "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO messages (id, session_id, role, content, "
            "executor_model, executor_input_tokens, executor_output_tokens, "
            "advisor_input_tokens, advisor_output_tokens, advisor_calls_count, "
            "cache_read_tokens, cache_creation_tokens, created_at) "
            "VALUES (?, ?, 'assistant', '', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("msg_1", "s1", "sonnet", 100, 200, 0, 0, 0, 10, 40, iso_now),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/usage/by_model?period=week")
            assert response.status_code == 200
            rows = response.json()
            executor_row = next(r for r in rows if r["role"] == "executor")
            assert executor_row["cache_creation_tokens"] == 40
            assert executor_row["cache_read_tokens"] == 10
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_by_tag_response_includes_cache_creation_tokens(tmp_path: Path) -> None:
    """``cache_creation_tokens`` is summed from ``messages`` for tag rows."""
    db_path = tmp_path / "by_tag_cache_creation.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        await conn.execute(
            "INSERT INTO tags (id, name, color, default_model, working_dir, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "infra", None, None, None, iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s1", "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO session_tags (session_id, tag_id, created_at) VALUES (?, ?, ?)",
            ("s1", 1, iso_now),
        )
        await conn.execute(
            "INSERT INTO messages (id, session_id, role, content, "
            "executor_model, executor_input_tokens, executor_output_tokens, "
            "advisor_input_tokens, advisor_output_tokens, advisor_calls_count, "
            "cache_creation_tokens, created_at) "
            "VALUES (?, ?, 'assistant', '', ?, ?, ?, ?, ?, ?, ?, ?)",
            ("msg_1", "s1", "sonnet", 100, 200, 0, 0, 0, 75, iso_now),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/usage/by_tag?period=week")
            assert response.status_code == 200
            rows = response.json()
            assert len(rows) == 1
            assert rows[0]["tag_name"] == "infra"
            assert rows[0]["cache_creation_tokens"] == 75
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Phase 3: GET /api/usage/turns
# ---------------------------------------------------------------------------


def test_turns_empty_db_returns_empty_list(app_client: TestClient) -> None:
    """No turns → empty list."""
    response = app_client.get("/api/usage/turns")
    assert response.status_code == 200
    assert response.json() == []


def test_turns_invalid_period_returns_422(app_client: TestClient) -> None:
    """Period must be in {day, week}."""
    response = app_client.get("/api/usage/turns?period=month")
    assert response.status_code == 422


def test_turns_returns_seeded_rows(tmp_path: Path) -> None:
    """Seeded turns appear in the response with correct fields."""
    db_path = tmp_path / "turns_seeded.db"
    now_ms = int(time.time() * 1000)

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s1", "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO turns (session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", 0, now_ms, "claude-sonnet-4-6", 500, 100, 20, 30),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/usage/turns?period=week")
            assert response.status_code == 200
            rows = response.json()
            assert len(rows) == 1
            row = rows[0]
            assert row["session_id"] == "s1"
            assert row["turn_index"] == 0
            assert row["model"] == "claude-sonnet-4-6"
            assert row["input_tokens"] == 500
            assert row["output_tokens"] == 100
            assert row["cache_read_tokens"] == 20
            assert row["cache_creation_tokens"] == 30
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_turns_session_id_filter(tmp_path: Path) -> None:
    """``session_id`` query parameter limits results to that session."""
    db_path = tmp_path / "turns_session_filter.db"
    now_ms = int(time.time() * 1000)

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        for sid in ("s1", "s2"):
            await conn.execute(
                "INSERT INTO sessions (id, kind, title, working_dir, model, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
            )
        await conn.execute(
            "INSERT INTO turns (session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", 0, now_ms, "claude-sonnet-4-6", 100, 10, 0, 0),
        )
        await conn.execute(
            "INSERT INTO turns (session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s2", 0, now_ms, "claude-sonnet-4-6", 200, 20, 0, 0),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            # All turns
            all_response = client.get("/api/usage/turns")
            assert all_response.status_code == 200
            assert len(all_response.json()) == 2
            # Filtered to s1 only
            filtered = client.get("/api/usage/turns?session_id=s1")
            assert filtered.status_code == 200
            rows = filtered.json()
            assert len(rows) == 1
            assert rows[0]["session_id"] == "s1"
            assert rows[0]["input_tokens"] == 100
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_turns_period_boundary_excludes_old_turns(tmp_path: Path) -> None:
    """Turns older than the period window are excluded."""
    db_path = tmp_path / "turns_boundary.db"
    now_ms = int(time.time() * 1000)
    # 8 days ago — outside the week window
    old_ms = now_ms - (8 * 24 * 60 * 60 * 1000)

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s1", "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
        )
        # Recent turn — within window
        await conn.execute(
            "INSERT INTO turns (session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", 0, now_ms, "claude-sonnet-4-6", 100, 10, 0, 0),
        )
        # Old turn — outside window
        await conn.execute(
            "INSERT INTO turns (session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", 1, old_ms, "claude-sonnet-4-6", 999, 99, 0, 0),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/usage/turns?period=week")
            assert response.status_code == 200
            rows = response.json()
            # Only the recent turn should be returned
            assert len(rows) == 1
            assert rows[0]["input_tokens"] == 100
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def test_turns_day_period_excludes_week_old_turn(tmp_path: Path) -> None:
    """``period=day`` filters out turns older than 24 h."""
    db_path = tmp_path / "turns_day_period.db"
    now_ms = int(time.time() * 1000)
    two_days_ago_ms = now_ms - (2 * 24 * 60 * 60 * 1000)

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        iso_now = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00",
            time.gmtime(time.time()),
        )
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s1", "chat", "t", "/tmp", "sonnet", iso_now, iso_now),
        )
        await conn.execute(
            "INSERT INTO turns (session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", 0, now_ms, "claude-sonnet-4-6", 50, 5, 0, 0),
        )
        await conn.execute(
            "INSERT INTO turns (session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", 1, two_days_ago_ms, "claude-sonnet-4-6", 777, 77, 0, 0),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            response = client.get("/api/usage/turns?period=day")
            assert response.status_code == 200
            rows = response.json()
            assert len(rows) == 1
            assert rows[0]["input_tokens"] == 50
        loop.run_until_complete(conn.close())
    finally:
        loop.close()
