"""Store-helper tests for the autonomous-checklist foundation.

Exercises the three helpers added to `db/_checklists.py` that back
the autonomous driver's iteration + leg-chain lookups:

- `next_unchecked_top_level_item` — driver's outer-loop pick.
- `list_unchecked_children` — driver's recurse-into-children pick.
- `list_item_sessions` — enumerates all legs ever spawned for an
  item (via the reverse pointer `sessions.checklist_item_id`), so the
  UI can render the leg expander and the driver can resume mid-chain.

These live in their own file so the autonomous-driver slice's churn
doesn't touch `test_checklists.py` (which is stable Slice-1 ground
truth for the shipped checklist feature).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bearings.db.store import (
    create_checklist,
    create_item,
    create_session,
    init_db,
    list_item_sessions,
    list_unchecked_children,
    next_unchecked_top_level_item,
    set_item_chat_session,
    toggle_item,
)

# --- next_unchecked_top_level_item ---------------------------------


@pytest.mark.asyncio
async def test_next_unchecked_picks_lowest_sort_order(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        # Insert out of sort order to prove ordering is read from
        # `sort_order`, not insertion order.
        await create_item(conn, session["id"], label="second", sort_order=10)
        first = await create_item(conn, session["id"], label="first", sort_order=0)
        picked = await next_unchecked_top_level_item(conn, session["id"])
        assert picked is not None
        assert picked["id"] == first["id"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_next_unchecked_skips_checked_items(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        done_item = await create_item(conn, session["id"], label="already done", sort_order=0)
        pending = await create_item(conn, session["id"], label="still pending", sort_order=1)
        await toggle_item(conn, done_item["id"], checked=True)
        picked = await next_unchecked_top_level_item(conn, session["id"])
        assert picked is not None
        assert picked["id"] == pending["id"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_next_unchecked_ignores_nested_children(tmp_path: Path) -> None:
    # "Top-level" means `parent_item_id IS NULL`. A checklist whose
    # root is checked but whose children are unchecked should return
    # None from this helper — children belong to the recurse layer.
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        root = await create_item(conn, session["id"], label="root", sort_order=0)
        await create_item(
            conn,
            session["id"],
            label="child",
            parent_item_id=root["id"],
        )
        # Only the child is unchecked — but the helper looks at
        # top-level only, and toggling the root would cascade the
        # invariant (checked only when children checked). Here the
        # root is also unchecked, so top-level returns root.
        picked = await next_unchecked_top_level_item(conn, session["id"])
        assert picked is not None
        assert picked["id"] == root["id"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_next_unchecked_returns_none_when_all_top_level_done(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        a = await create_item(conn, session["id"], label="a", sort_order=0)
        b = await create_item(conn, session["id"], label="b", sort_order=1)
        await toggle_item(conn, a["id"], checked=True)
        await toggle_item(conn, b["id"], checked=True)
        picked = await next_unchecked_top_level_item(conn, session["id"])
        assert picked is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_next_unchecked_on_empty_checklist_returns_none(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        picked = await next_unchecked_top_level_item(conn, session["id"])
        assert picked is None
    finally:
        await conn.close()


# --- list_unchecked_children ---------------------------------------


@pytest.mark.asyncio
async def test_list_unchecked_children_returns_only_direct_children(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        parent = await create_item(conn, session["id"], label="parent", sort_order=0)
        c1 = await create_item(
            conn,
            session["id"],
            label="c1",
            parent_item_id=parent["id"],
            sort_order=0,
        )
        c2 = await create_item(
            conn,
            session["id"],
            label="c2",
            parent_item_id=parent["id"],
            sort_order=1,
        )
        # Grandchild — should NOT appear in the list.
        await create_item(
            conn,
            session["id"],
            label="gc",
            parent_item_id=c1["id"],
            sort_order=0,
        )
        children = await list_unchecked_children(conn, parent["id"])
        assert [r["id"] for r in children] == [c1["id"], c2["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_unchecked_children_skips_checked(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        parent = await create_item(conn, session["id"], label="parent", sort_order=0)
        done = await create_item(
            conn,
            session["id"],
            label="done",
            parent_item_id=parent["id"],
            sort_order=0,
        )
        pending = await create_item(
            conn,
            session["id"],
            label="pending",
            parent_item_id=parent["id"],
            sort_order=1,
        )
        await toggle_item(conn, done["id"], checked=True)
        children = await list_unchecked_children(conn, parent["id"])
        assert [r["id"] for r in children] == [pending["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_unchecked_children_on_leaf_returns_empty(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        leaf = await create_item(conn, session["id"], label="leaf")
        assert await list_unchecked_children(conn, leaf["id"]) == []
    finally:
        await conn.close()


# --- list_item_sessions --------------------------------------------


@pytest.mark.asyncio
async def test_list_item_sessions_returns_empty_when_never_paired(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        item = await create_item(conn, session["id"], label="solo")
        assert await list_item_sessions(conn, item["id"]) == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_item_sessions_enumerates_every_leg(tmp_path: Path) -> None:
    # The forward pointer (`checklist_items.chat_session_id`) only
    # remembers the most recent leg, but the driver needs to see every
    # leg ever spawned. `list_item_sessions` uses the reverse pointer
    # (`sessions.checklist_item_id`) to enumerate all of them.
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        parent_session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, parent_session["id"])
        item = await create_item(conn, parent_session["id"], label="task")
        # Three legs — simulate the driver spawning successor chats as
        # earlier legs fill their context windows.
        leg1 = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="chat",
            checklist_item_id=item["id"],
            title="task (leg 1)",
        )
        leg2 = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="chat",
            checklist_item_id=item["id"],
            title="task (leg 2)",
        )
        leg3 = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="chat",
            checklist_item_id=item["id"],
            title="task (leg 3)",
        )
        # Current-leg pointer only remembers the latest — prove that
        # `list_item_sessions` still finds all three.
        await set_item_chat_session(conn, item["id"], leg3["id"])
        legs = await list_item_sessions(conn, item["id"])
        assert [row["id"] for row in legs] == [
            leg1["id"],
            leg2["id"],
            leg3["id"],
        ]
        assert [row["title"] for row in legs] == [
            "task (leg 1)",
            "task (leg 2)",
            "task (leg 3)",
        ]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_item_sessions_does_not_leak_across_items(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        parent_session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, parent_session["id"])
        item_a = await create_item(conn, parent_session["id"], label="A")
        item_b = await create_item(conn, parent_session["id"], label="B")
        leg_a = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="chat",
            checklist_item_id=item_a["id"],
        )
        leg_b = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="chat",
            checklist_item_id=item_b["id"],
        )
        a_legs = await list_item_sessions(conn, item_a["id"])
        b_legs = await list_item_sessions(conn, item_b["id"])
        assert [r["id"] for r in a_legs] == [leg_a["id"]]
        assert [r["id"] for r in b_legs] == [leg_b["id"]]
    finally:
        await conn.close()
