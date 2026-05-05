"""Integration tests for ``bearings.db.tags`` against a real SQLite.

Round-trips :func:`create` / :func:`get` / :func:`list_all` /
:func:`list_for_session` / :func:`list_groups` / :func:`update` /
:func:`delete` plus the per-session join helpers
:func:`attach` / :func:`detach` / :func:`set_for_session` against a
freshly-bootstrapped DB. Exercises the FK cascade behavior the schema
declares (``ON DELETE CASCADE`` on ``session_tags``) so a tag deletion
sweeps its session attachments.

References:

* ``docs/architecture-v1.md`` §1.1.3 — concern-module CRUD pattern.
* ``schema.sql`` — ``tags`` + ``session_tags`` tables, FK declarations.
* ``docs/behavior/chat.md`` §"When the user creates a chat" —
  every session carries ≥1 tag.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.config.constants import (
    TAG_CLASS_GENERAL,
    TAG_CLASS_PROJECT,
    TAG_CLASS_SEVERITY,
)
from bearings.db import get_connection_factory, load_schema
from bearings.db.tags import (
    Tag,
    attach,
    create,
    delete,
    detach,
    get,
    get_by_name,
    list_all,
    list_for_session,
    list_groups,
    set_for_session,
    update,
    update_sort_orders,
)


@pytest.fixture
async def connection(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Open + bootstrap a fresh DB connection per test."""
    factory = get_connection_factory(tmp_path / "tags.db")
    async with factory() as conn:
        await load_schema(conn)
        yield conn


async def _seed_session(
    connection: aiosqlite.Connection,
    *,
    session_id: str = "session_alpha",
) -> str:
    """Insert one minimal session; return its id."""
    timestamp = "2026-04-28T12:00:00+00:00"
    await connection.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, "chat", "Alpha", "/tmp/alpha", "sonnet", timestamp, timestamp),
    )
    await connection.commit()
    return session_id


async def test_create_round_trips_via_get(connection: aiosqlite.Connection) -> None:
    tag = await create(
        connection,
        name="bearings/architect",
        color="#ffaa00",
        default_model="opus",
        working_dir="/home/dave/proj",
    )
    fetched = await get(connection, tag.id)
    assert fetched == tag


async def test_get_returns_none_for_unknown_id(connection: aiosqlite.Connection) -> None:
    assert await get(connection, 99_999) is None


async def test_get_by_name_round_trips(connection: aiosqlite.Connection) -> None:
    tag = await create(connection, name="general")
    fetched = await get_by_name(connection, "general")
    assert fetched == tag
    assert await get_by_name(connection, "absent") is None


async def test_create_rejects_duplicate_name(connection: aiosqlite.Connection) -> None:
    await create(connection, name="dup")
    with pytest.raises(aiosqlite.IntegrityError):
        await create(connection, name="dup")


async def test_list_all_alphabetical(connection: aiosqlite.Connection) -> None:
    await create(connection, name="z-tag")
    await create(connection, name="a-tag")
    await create(connection, name="m-tag")
    rows = await list_all(connection)
    assert [t.name for t in rows] == ["a-tag", "m-tag", "z-tag"]


async def test_list_all_filters_by_group(connection: aiosqlite.Connection) -> None:
    await create(connection, name="bearings/architect")
    await create(connection, name="bearings/exec")
    await create(connection, name="general")
    rows = await list_all(connection, group="bearings")
    assert [t.name for t in rows] == ["bearings/architect", "bearings/exec"]


async def test_list_groups_returns_distinct_prefixes(
    connection: aiosqlite.Connection,
) -> None:
    await create(connection, name="bearings/architect")
    await create(connection, name="bearings/exec")
    await create(connection, name="research/lit")
    await create(connection, name="general")  # no group
    groups = await list_groups(connection)
    assert groups == ["bearings", "research"]


async def test_update_replaces_mutable_fields(connection: aiosqlite.Connection) -> None:
    tag = await create(connection, name="orig", default_model="sonnet")
    updated = await update(
        connection,
        tag.id,
        name="renamed",
        color="#000000",
        default_model="haiku",
        working_dir="/new/dir",
    )
    assert updated is not None
    assert updated.name == "renamed"
    assert updated.default_model == "haiku"
    assert updated.created_at == tag.created_at
    assert updated.updated_at >= tag.updated_at
    refetched = await get(connection, tag.id)
    assert refetched == updated


async def test_update_returns_none_on_unknown_id(
    connection: aiosqlite.Connection,
) -> None:
    result = await update(
        connection,
        99_999,
        name="x",
        color=None,
        default_model=None,
        working_dir=None,
    )
    assert result is None


async def test_delete_returns_true_for_existing_row(
    connection: aiosqlite.Connection,
) -> None:
    tag = await create(connection, name="rm-me")
    assert await delete(connection, tag.id) is True
    assert await get(connection, tag.id) is None
    assert await delete(connection, tag.id) is False


async def test_attach_and_detach_round_trip(connection: aiosqlite.Connection) -> None:
    session_id = await _seed_session(connection)
    tag = await create(connection, name="t1")
    assert await attach(connection, session_id=session_id, tag_id=tag.id) is True
    # Idempotent — second attach is a no-op (returns False).
    assert await attach(connection, session_id=session_id, tag_id=tag.id) is False
    rows = await list_for_session(connection, session_id)
    assert [t.id for t in rows] == [tag.id]
    assert await detach(connection, session_id=session_id, tag_id=tag.id) is True
    assert await detach(connection, session_id=session_id, tag_id=tag.id) is False
    assert await list_for_session(connection, session_id) == []


async def test_attach_rejects_unknown_session_or_tag(
    connection: aiosqlite.Connection,
) -> None:
    with pytest.raises(aiosqlite.IntegrityError):
        await attach(connection, session_id="missing", tag_id=1)


async def test_session_delete_cascades_to_session_tags(
    connection: aiosqlite.Connection,
) -> None:
    session_id = await _seed_session(connection)
    tag = await create(connection, name="cascade-test")
    await attach(connection, session_id=session_id, tag_id=tag.id)
    await connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await connection.commit()
    # Tag still exists, but no longer attached.
    assert await get(connection, tag.id) is not None
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM session_tags WHERE tag_id = ?", (tag.id,)
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    assert row is not None
    assert int(row[0]) == 0


async def test_tag_delete_cascades_to_session_tags(
    connection: aiosqlite.Connection,
) -> None:
    session_id = await _seed_session(connection)
    tag = await create(connection, name="del-cascade")
    await attach(connection, session_id=session_id, tag_id=tag.id)
    await delete(connection, tag.id)
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM session_tags WHERE session_id = ?", (session_id,)
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    assert row is not None
    assert int(row[0]) == 0


async def test_set_for_session_replaces_tag_set(
    connection: aiosqlite.Connection,
) -> None:
    session_id = await _seed_session(connection)
    tag_a = await create(connection, name="A")
    tag_b = await create(connection, name="B")
    tag_c = await create(connection, name="C")
    await attach(connection, session_id=session_id, tag_id=tag_a.id)
    await attach(connection, session_id=session_id, tag_id=tag_b.id)
    # Replace {A, B} with {B, C}.
    await set_for_session(connection, session_id=session_id, tag_ids=(tag_b.id, tag_c.id))
    rows: list[Tag] = await list_for_session(connection, session_id)
    assert {t.id for t in rows} == {tag_b.id, tag_c.id}


async def test_set_for_session_empty_clears(connection: aiosqlite.Connection) -> None:
    session_id = await _seed_session(connection)
    tag = await create(connection, name="solo")
    await attach(connection, session_id=session_id, tag_id=tag.id)
    await set_for_session(connection, session_id=session_id, tag_ids=())
    assert await list_for_session(connection, session_id) == []


async def test_create_invalid_default_model_raises_before_db(
    connection: aiosqlite.Connection,
) -> None:
    """Dataclass cap fires before any DB write — DB stays untouched."""
    with pytest.raises(ValueError, match="default_model"):
        await create(connection, name="bad", default_model="not-a-model")
    rows = await list_all(connection)
    assert rows == []


# ---------------------------------------------------------------------------
# class_ + sort_order — tag-class feature
# ---------------------------------------------------------------------------


async def test_create_with_class_round_trips(connection: aiosqlite.Connection) -> None:
    """Class column persists round-trip via :func:`get`."""
    tag = await create(
        connection,
        name="bearings",
        class_=TAG_CLASS_PROJECT,
        default_model="opus",
        working_dir="/home/dave/proj",
    )
    assert tag.class_ == TAG_CLASS_PROJECT
    fetched = await get(connection, tag.id)
    assert fetched is not None
    assert fetched.class_ == TAG_CLASS_PROJECT


async def test_create_severity_with_inheritance_field_rejected(
    connection: aiosqlite.Connection,
) -> None:
    """Phantom-validate fires before DB write — severity + default_model is rejected."""
    with pytest.raises(ValueError, match="default_model"):
        await create(
            connection,
            name="urgent",
            class_=TAG_CLASS_SEVERITY,
            default_model="opus",
        )
    assert await list_all(connection) == []


async def test_create_defaults_to_general_class(
    connection: aiosqlite.Connection,
) -> None:
    """Pre-class call site (no class_ kwarg) lands as ``general``."""
    tag = await create(connection, name="freeform")
    assert tag.class_ == TAG_CLASS_GENERAL
    assert tag.sort_order == 0


async def test_list_all_orders_by_class_then_sort_order(
    connection: aiosqlite.Connection,
) -> None:
    """``(class ASC, sort_order ASC, name ASC)`` is the canonical render order."""
    await create(connection, name="z-general")
    await create(connection, name="a-general")
    await create(
        connection,
        name="b-project",
        class_=TAG_CLASS_PROJECT,
        sort_order=2,
    )
    await create(
        connection,
        name="a-project",
        class_=TAG_CLASS_PROJECT,
        sort_order=1,
    )
    await create(
        connection,
        name="high",
        class_=TAG_CLASS_SEVERITY,
        sort_order=10,
    )
    rows = await list_all(connection)
    # Class order: general < project < severity (alphabetical within class
    # is the SQL-level fallback). Within-class: sort_order ASC, name ASC.
    assert [t.name for t in rows] == [
        "a-general",
        "z-general",
        "a-project",
        "b-project",
        "high",
    ]


async def test_list_all_filters_by_class(connection: aiosqlite.Connection) -> None:
    """``class_=`` filter returns only the requested class."""
    await create(connection, name="freeform")
    await create(connection, name="bearings", class_=TAG_CLASS_PROJECT)
    await create(connection, name="archon", class_=TAG_CLASS_PROJECT)
    rows = await list_all(connection, class_=TAG_CLASS_PROJECT)
    assert {t.name for t in rows} == {"bearings", "archon"}
    assert all(t.class_ == TAG_CLASS_PROJECT for t in rows)


async def test_list_all_class_filter_rejects_unknown(
    connection: aiosqlite.Connection,
) -> None:
    with pytest.raises(ValueError, match="class_"):
        await list_all(connection, class_="milestone")


async def test_update_sort_orders_resequences_within_class(
    connection: aiosqlite.Connection,
) -> None:
    """Drag-reorder path: ids in the new order get sort_order = index."""
    a = await create(connection, name="a", class_=TAG_CLASS_PROJECT, sort_order=0)
    b = await create(connection, name="b", class_=TAG_CLASS_PROJECT, sort_order=1)
    c = await create(connection, name="c", class_=TAG_CLASS_PROJECT, sort_order=2)
    await update_sort_orders(
        connection,
        class_=TAG_CLASS_PROJECT,
        ordered_ids=(c.id, a.id, b.id),
    )
    rows = await list_all(connection, class_=TAG_CLASS_PROJECT)
    assert [t.name for t in rows] == ["c", "a", "b"]


async def test_update_sort_orders_rejects_cross_class(
    connection: aiosqlite.Connection,
) -> None:
    """A project id cannot appear in a severity re-sequence call."""
    proj = await create(connection, name="proj", class_=TAG_CLASS_PROJECT)
    sev = await create(connection, name="sev", class_=TAG_CLASS_SEVERITY)
    with pytest.raises(ValueError, match="not in class"):
        await update_sort_orders(
            connection,
            class_=TAG_CLASS_SEVERITY,
            ordered_ids=(sev.id, proj.id),
        )


async def test_update_sort_orders_rejects_missing_id(
    connection: aiosqlite.Connection,
) -> None:
    with pytest.raises(ValueError, match="not found"):
        await update_sort_orders(
            connection,
            class_=TAG_CLASS_PROJECT,
            ordered_ids=(99_999,),
        )


async def test_update_sort_orders_empty_is_noop(
    connection: aiosqlite.Connection,
) -> None:
    a = await create(connection, name="a", class_=TAG_CLASS_PROJECT, sort_order=5)
    await update_sort_orders(connection, class_=TAG_CLASS_PROJECT, ordered_ids=())
    fetched = await get(connection, a.id)
    assert fetched is not None
    assert fetched.sort_order == 5


async def test_update_sort_orders_rejects_unknown_class(
    connection: aiosqlite.Connection,
) -> None:
    with pytest.raises(ValueError, match="class_"):
        await update_sort_orders(connection, class_="milestone", ordered_ids=(1,))


async def test_update_can_change_class(connection: aiosqlite.Connection) -> None:
    """Promoting a general tag to project class persists round-trip."""
    tag = await create(connection, name="bearings")
    assert tag.class_ == TAG_CLASS_GENERAL
    updated = await update(
        connection,
        tag.id,
        name="bearings",
        color=None,
        default_model="opus",
        working_dir="/home/dave/proj",
        class_=TAG_CLASS_PROJECT,
    )
    assert updated is not None
    assert updated.class_ == TAG_CLASS_PROJECT
    assert updated.default_model == "opus"
    refetched = await get(connection, tag.id)
    assert refetched is not None
    assert refetched.class_ == TAG_CLASS_PROJECT


async def test_update_to_severity_strips_inheritance_via_validator(
    connection: aiosqlite.Connection,
) -> None:
    """Promoting to severity while keeping default_model is rejected by the validator."""
    tag = await create(
        connection,
        name="urgent",
        default_model="opus",
        working_dir="/x",
    )
    with pytest.raises(ValueError, match="default_model"):
        await update(
            connection,
            tag.id,
            name="urgent",
            color=None,
            default_model="opus",
            working_dir=None,
            class_=TAG_CLASS_SEVERITY,
        )
