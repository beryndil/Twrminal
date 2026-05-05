"""Tests for ``bearings.db.sessions`` (item 1.7 — sessions CRUD).

Covers the surface item 1.7 needs: row create, get, exists, kind /
closed introspection, close / reopen lifecycle, delete cascade.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from bearings.config.constants import (
    SESSION_KIND_CHAT,
    SESSION_KIND_CHECKLIST,
)
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema


@pytest.fixture
async def conn(tmp_path: Path):
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await load_schema(connection)
        yield connection


async def test_create_chat_session_returns_validated_row(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="Hello",
        working_dir="/tmp/wd",
        model="sonnet",
    )
    assert session.id.startswith("ses_")
    assert session.kind == SESSION_KIND_CHAT
    assert session.title == "Hello"
    assert session.working_dir == "/tmp/wd"
    assert session.model == "sonnet"
    assert session.closed_at is None
    assert session.message_count == 0


async def test_get_returns_none_for_missing(conn: aiosqlite.Connection) -> None:
    assert await sessions_db.get(conn, "ses_nonexistent") is None


async def test_exists_true_after_create(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHECKLIST, title="C", working_dir="/wd", model="haiku"
    )
    assert await sessions_db.exists(conn, session.id)


async def test_get_kind_distinguishes_chat_from_checklist(conn: aiosqlite.Connection) -> None:
    chat = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    checklist = await sessions_db.create(
        conn, kind=SESSION_KIND_CHECKLIST, title="c", working_dir="/wd", model="sonnet"
    )
    assert await sessions_db.get_kind(conn, chat.id) == "chat"
    assert await sessions_db.get_kind(conn, checklist.id) == "checklist"
    assert await sessions_db.get_kind(conn, "ses_missing") is None


async def test_is_closed_tristate(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    assert await sessions_db.is_closed(conn, session.id) is False
    await sessions_db.close(conn, session.id)
    assert await sessions_db.is_closed(conn, session.id) is True
    assert await sessions_db.is_closed(conn, "ses_missing") is None


async def test_close_then_reopen_round_trip(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    closed = await sessions_db.close(conn, session.id)
    assert closed is not None and closed.closed_at is not None
    reopened = await sessions_db.reopen(conn, session.id)
    assert reopened is not None and reopened.closed_at is None


async def test_update_title(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="old", working_dir="/wd", model="sonnet"
    )
    updated = await sessions_db.update_title(conn, session.id, title="new")
    assert updated is not None and updated.title == "new"


async def test_update_title_rejects_empty(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    with pytest.raises(ValueError):
        await sessions_db.update_title(conn, session.id, title="")


async def test_delete_returns_false_when_missing(conn: aiosqlite.Connection) -> None:
    assert (await sessions_db.delete(conn, "ses_missing")) is False


async def test_create_validates_kind(conn: aiosqlite.Connection) -> None:
    with pytest.raises(ValueError, match="kind"):
        await sessions_db.create(conn, kind="bogus", title="t", working_dir="/wd", model="sonnet")


async def test_create_validates_model(conn: aiosqlite.Connection) -> None:
    with pytest.raises(ValueError, match="model"):
        await sessions_db.create(
            conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonet"
        )


async def test_list_all_filters(conn: aiosqlite.Connection) -> None:
    a = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="a", working_dir="/wd", model="sonnet"
    )
    b = await sessions_db.create(
        conn, kind=SESSION_KIND_CHECKLIST, title="b", working_dir="/wd", model="sonnet"
    )
    await sessions_db.close(conn, a.id)
    chats_open = await sessions_db.list_all(conn, kind="chat", include_closed=False)
    assert chats_open == []
    chats_all = await sessions_db.list_all(conn, kind="chat")
    assert {row.id for row in chats_all} == {a.id}
    every = await sessions_db.list_all(conn)
    assert {row.id for row in every} == {a.id, b.id}


async def test_list_all_filters_by_tag_ids_or_semantics(
    conn: aiosqlite.Connection,
) -> None:
    """Item 2.2 — OR semantics across tag_ids in :func:`list_all`.

    The done-when for master item #537 ("Sidebar, tag filter, session
    row. Finder-click filter + OR semantics across tags") is enforced
    here: a session attached to **either** of two selected tags must
    appear in the result, and AND-style intersection must NOT be
    applied. We construct a deliberately disjoint setup —
    session_a→tag1, session_b→tag2, session_c→untagged — and assert
    that ``tag_ids=(tag1, tag2)`` returns {a, b}, never {} (which AND
    semantics would yield against disjoint sessions).
    """
    from bearings.db import tags as tags_db

    tag1 = await tags_db.create(conn, name="bearings/architect")
    tag2 = await tags_db.create(conn, name="bearings/exec")

    session_a = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="a", working_dir="/wd", model="sonnet"
    )
    session_b = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="b", working_dir="/wd", model="sonnet"
    )
    session_c = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="c", working_dir="/wd", model="sonnet"
    )
    await tags_db.attach(conn, session_id=session_a.id, tag_id=tag1.id)
    await tags_db.attach(conn, session_id=session_b.id, tag_id=tag2.id)
    # session_c remains untagged.

    only_tag1 = await sessions_db.list_all(conn, tag_ids=(tag1.id,))
    assert {row.id for row in only_tag1} == {session_a.id}

    or_filter = await sessions_db.list_all(conn, tag_ids=(tag1.id, tag2.id))
    assert {row.id for row in or_filter} == {session_a.id, session_b.id}, (
        "OR semantics: session_a (tag1) or session_b (tag2) — AND would yield {}"
    )

    no_filter = await sessions_db.list_all(conn)
    assert {row.id for row in no_filter} == {session_a.id, session_b.id, session_c.id}


async def test_list_all_tag_ids_dedups_multi_attach(
    conn: aiosqlite.Connection,
) -> None:
    """Sessions attached to multiple selected tags appear exactly once.

    Without ``SELECT DISTINCT`` on the join path, a session attached to
    both tag1 and tag2 would surface as two rows when ``tag_ids=(tag1,
    tag2)``. The list_all contract is one row per session.
    """
    from bearings.db import tags as tags_db

    tag1 = await tags_db.create(conn, name="bearings/architect")
    tag2 = await tags_db.create(conn, name="bearings/exec")
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="multi", working_dir="/wd", model="sonnet"
    )
    await tags_db.attach(conn, session_id=session.id, tag_id=tag1.id)
    await tags_db.attach(conn, session_id=session.id, tag_id=tag2.id)

    rows = await sessions_db.list_all(conn, tag_ids=(tag1.id, tag2.id))
    assert [row.id for row in rows] == [session.id]


async def test_list_all_empty_tag_ids_raises(conn: aiosqlite.Connection) -> None:
    """Empty ``tag_ids`` is a caller bug — ``None`` means "no filter"."""
    with pytest.raises(ValueError, match="tag_ids must be non-empty"):
        await sessions_db.list_all(conn, tag_ids=())


async def test_list_all_combines_kind_and_tag_filter(conn: aiosqlite.Connection) -> None:
    """``kind`` + ``tag_ids`` AND together (kind narrows, tag_ids OR within).

    A checklist tagged with tag1 should NOT appear when filtering for
    chat + tag_ids=(tag1,) — the kind clause excludes it.
    """
    from bearings.db import tags as tags_db

    tag1 = await tags_db.create(conn, name="bearings/architect")
    chat_tagged = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="chat", working_dir="/wd", model="sonnet"
    )
    checklist_tagged = await sessions_db.create(
        conn, kind=SESSION_KIND_CHECKLIST, title="cl", working_dir="/wd", model="sonnet"
    )
    await tags_db.attach(conn, session_id=chat_tagged.id, tag_id=tag1.id)
    await tags_db.attach(conn, session_id=checklist_tagged.id, tag_id=tag1.id)

    chats_only = await sessions_db.list_all(conn, kind="chat", tag_ids=(tag1.id,))
    assert {row.id for row in chats_only} == {chat_tagged.id}


# ---------------------------------------------------------------------------
# Three-section faceted filter — tag-class feature
# ---------------------------------------------------------------------------


async def test_list_all_three_section_or_within_and_across(
    conn: aiosqlite.Connection,
) -> None:
    """OR within a section; AND across sections; empty = no constraint."""
    from bearings.db import tags as tags_db

    proj_a = await tags_db.create(conn, name="proj-a", class_="project")
    proj_b = await tags_db.create(conn, name="proj-b", class_="project")
    sev_high = await tags_db.create(conn, name="high", class_="severity")

    alpha = await sessions_db.create(
        conn, kind="chat", title="alpha", working_dir="/wd", model="sonnet"
    )
    beta = await sessions_db.create(
        conn, kind="chat", title="beta", working_dir="/wd", model="sonnet"
    )
    gamma = await sessions_db.create(
        conn, kind="chat", title="gamma", working_dir="/wd", model="sonnet"
    )
    await tags_db.attach(conn, session_id=alpha.id, tag_id=proj_a.id)
    await tags_db.attach(conn, session_id=alpha.id, tag_id=sev_high.id)
    await tags_db.attach(conn, session_id=beta.id, tag_id=proj_b.id)
    await tags_db.attach(conn, session_id=beta.id, tag_id=sev_high.id)
    await tags_db.attach(conn, session_id=gamma.id, tag_id=proj_a.id)

    # AND-across: project IN {a, b} AND severity IN {high}.
    rows = await sessions_db.list_all(
        conn,
        tag_ids_project=(proj_a.id, proj_b.id),
        tag_ids_severity=(sev_high.id,),
    )
    assert {r.id for r in rows} == {alpha.id, beta.id}


async def test_list_all_empty_section_means_no_constraint(
    conn: aiosqlite.Connection,
) -> None:
    """Omitting a section must not exclude rows from other sections."""
    from bearings.db import tags as tags_db

    proj = await tags_db.create(conn, name="proj", class_="project")
    a = await sessions_db.create(conn, kind="chat", title="a", working_dir="/wd", model="sonnet")
    b = await sessions_db.create(conn, kind="chat", title="b", working_dir="/wd", model="sonnet")
    await tags_db.attach(conn, session_id=a.id, tag_id=proj.id)
    await tags_db.attach(conn, session_id=b.id, tag_id=proj.id)

    rows = await sessions_db.list_all(conn, tag_ids_project=(proj.id,))
    assert {r.id for r in rows} == {a.id, b.id}


async def test_list_all_three_section_filter_returns_each_session_once(
    conn: aiosqlite.Connection,
) -> None:
    """EXISTS subquery path doesn't need DISTINCT — verify no duplicates."""
    from bearings.db import tags as tags_db

    proj = await tags_db.create(conn, name="proj", class_="project")
    sev = await tags_db.create(conn, name="high", class_="severity")
    other_a = await tags_db.create(conn, name="general-a")
    other_b = await tags_db.create(conn, name="general-b")

    s = await sessions_db.create(
        conn, kind="chat", title="multi", working_dir="/wd", model="sonnet"
    )
    await tags_db.attach(conn, session_id=s.id, tag_id=proj.id)
    await tags_db.attach(conn, session_id=s.id, tag_id=sev.id)
    await tags_db.attach(conn, session_id=s.id, tag_id=other_a.id)
    await tags_db.attach(conn, session_id=s.id, tag_id=other_b.id)

    rows = await sessions_db.list_all(
        conn,
        tag_ids_project=(proj.id,),
        tag_ids_severity=(sev.id,),
        tag_ids_other=(other_a.id, other_b.id),
    )
    assert [r.id for r in rows] == [s.id]
    assert len(rows) == 1, "EXISTS path returns each row once even with multi-tag matches"
