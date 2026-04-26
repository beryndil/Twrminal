"""Checklist store unit tests (Slice 1 of nimble-checking-heron).

Covers migration shape, the `sessions.kind` discriminator, CRUD on
`checklists` / `checklist_items`, and cascade-on-delete from session
removal. The API layer + guards land in Slice 2 and have their own
tests — this file exercises `db/_checklists.py` directly."""

from __future__ import annotations

from pathlib import Path

import pytest

from bearings.db.store import (
    create_checklist,
    create_item,
    create_session,
    delete_item,
    delete_session,
    get_checklist,
    get_item,
    get_session,
    init_db,
    is_checklist_complete,
    reorder_items,
    set_item_blocked,
    toggle_item,
    update_checklist,
    update_item,
)

# --- migration shape -------------------------------------------------


@pytest.mark.asyncio
async def test_migration_creates_checklist_tables(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = [row[0] async for row in cursor]
        assert "checklists" in tables
        assert "checklist_items" in tables
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name IN ('idx_checklist_items_checklist', 'idx_checklist_items_parent')"
        ) as cursor:
            idx = {row[0] async for row in cursor}
        assert idx == {"idx_checklist_items_checklist", "idx_checklist_items_parent"}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_existing_sessions_backfill_as_chat(tmp_path: Path) -> None:
    """The `kind` column is NOT NULL DEFAULT 'chat' — every session
    row created via the existing `create_session` path should land as
    a chat without the caller having to opt in."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_session(conn, working_dir="/tmp", model="claude-sonnet-4-6")
        assert row["kind"] == "chat"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_session_accepts_checklist_kind(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        assert row["kind"] == "checklist"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_session_rejects_unknown_kind(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        with pytest.raises(ValueError):
            await create_session(conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="bogus")
    finally:
        await conn.close()


# --- checklists ------------------------------------------------------


@pytest.mark.asyncio
async def test_create_checklist_round_trips(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        row = await create_checklist(conn, session["id"], notes="pre-flight")
        assert row["session_id"] == session["id"]
        assert row["notes"] == "pre-flight"
        assert row["items"] == []
        assert row["created_at"]
        assert row["updated_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_checklist_notes(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        row = await update_checklist(conn, session["id"], fields={"notes": "after"})
        assert row is not None
        assert row["notes"] == "after"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_checklist_ignores_unknown_fields(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"], notes="original")
        row = await update_checklist(conn, session["id"], fields={"bogus": "value"})
        assert row is not None
        assert row["notes"] == "original"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_missing_checklist_returns_none(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await update_checklist(conn, "nonexistent", fields={"notes": "x"})
        assert row is None
    finally:
        await conn.close()


# --- items -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_item_appends_by_default(tmp_path: Path) -> None:
    """Omitting sort_order appends — `MAX(sort_order) + 1` among
    siblings. Four items in order should carry sort_order 0..3."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        labels = ["a", "b", "c", "d"]
        items = [await create_item(conn, session["id"], label=lbl) for lbl in labels]
        assert [i["sort_order"] for i in items if i is not None] == [0, 1, 2, 3]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_item_returns_none_for_missing_checklist(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_item(conn, "nonexistent", label="x")
        assert row is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_toggle_item_round_trip(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        item = await create_item(conn, session["id"], label="first")
        assert item is not None
        checked = await toggle_item(conn, item["id"], checked=True)
        assert checked is not None
        assert checked["checked_at"] is not None
        unchecked = await toggle_item(conn, item["id"], checked=False)
        assert unchecked is not None
        assert unchecked["checked_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_toggle_item_closes_all_paired_sessions(tmp_path: Path) -> None:
    """When an item with multiple paired chat legs becomes checked,
    EVERY paired session moves to closed — not just the
    forward-pointer (`chat_session_id`). The reverse pointer
    (`sessions.checklist_item_id`) enumerates all legs spawned for
    the item, including handoff successors and the original leg.

    Regression for the 2026-04-25 fae8f1a8 cleanup gap: the manual UI
    toggle path used to close only the forward pointer, leaving any
    handoff legs orphaned in the Open group. Backend ownership of the
    cascade closes that gap once for all callers."""
    from bearings.db.store import (
        get_session,
        list_item_sessions,
        set_item_chat_session,
    )

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        parent = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, parent["id"])
        item = await create_item(conn, parent["id"], label="multi-leg")
        assert item is not None
        # Three legs paired to this item via the reverse pointer.
        legs = []
        for _ in range(3):
            leg = await create_session(
                conn,
                working_dir="/tmp",
                model="claude-sonnet-4-6",
                kind="chat",
                checklist_item_id=int(item["id"]),
            )
            legs.append(leg)
        # Forward pointer points at leg 3 (latest). Used to be the
        # only one the UI toggle path closed.
        await set_item_chat_session(conn, int(item["id"]), legs[-1]["id"])
        # Sanity: all three legs report on the reverse pointer.
        listed = await list_item_sessions(conn, int(item["id"]))
        assert {row["id"] for row in listed} == {leg["id"] for leg in legs}

        # Toggle. Backend must close all three.
        await toggle_item(conn, int(item["id"]), checked=True)

        for leg in legs:
            row = await get_session(conn, leg["id"])
            assert row is not None
            assert row["closed_at"] is not None, f"leg {leg['id']} should be closed"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_toggle_item_cascade_check_only_for_rollup_parents(
    tmp_path: Path,
) -> None:
    """Cascade-check (parent auto-checked when all children checked)
    applies ONLY to rollup-only parents — those without their own
    paired chat. A parent with `chat_session_id` set has work of its
    own; its children are preconditions (driver-created blockers),
    not the totality of the parent's task. Auto-checking that parent
    would defeat the fix-and-return contract.

    Two-part assertion: a rollup parent (no chat) DOES cascade-check;
    a work-having parent (chat set) does NOT."""
    from bearings.db.store import (
        get_item,
        get_session,
        set_item_chat_session,
    )

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, cl["id"])
        # Rollup parent (no chat) — cascade-checks normally.
        rollup = await create_item(conn, cl["id"], label="rollup-parent")
        assert rollup is not None
        rollup_child = await create_item(
            conn, cl["id"], label="r-child", parent_item_id=int(rollup["id"])
        )
        assert rollup_child is not None
        # Work-having parent (chat set) — does NOT cascade-check.
        work = await create_item(conn, cl["id"], label="work-parent")
        assert work is not None
        work_child = await create_item(
            conn, cl["id"], label="w-child", parent_item_id=int(work["id"])
        )
        assert work_child is not None
        work_chat = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="chat",
            checklist_item_id=int(work["id"]),
        )
        await set_item_chat_session(conn, int(work["id"]), work_chat["id"])

        # Toggle each child.
        await toggle_item(conn, int(rollup_child["id"]), checked=True)
        await toggle_item(conn, int(work_child["id"]), checked=True)

        # Rollup parent cascade-checked.
        rollup_refreshed = await get_item(conn, int(rollup["id"]))
        assert rollup_refreshed is not None
        assert rollup_refreshed["checked_at"] is not None, "rollup-only parent should cascade-check"

        # Work-having parent did NOT cascade-check.
        work_refreshed = await get_item(conn, int(work["id"]))
        assert work_refreshed is not None
        assert work_refreshed["checked_at"] is None, (
            "work-having parent (with chat_session_id) should NOT cascade-check; "
            "agent must explicitly emit CHECKLIST_ITEM_DONE after fixing the blocker"
        )
        # And its work chat stays open.
        work_chat_row = await get_session(conn, work_chat["id"])
        assert work_chat_row is not None
        assert work_chat_row["closed_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_toggle_last_item_auto_closes_parent_checklist(tmp_path: Path) -> None:
    """Completing the last unchecked item auto-closes the parent
    checklist session. Used to live in the close_session cascade
    (only fired when at least one paired chat existed); now lives in
    toggle_item so an items-without-legs list also closes cleanly."""
    from bearings.db.store import get_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, cl["id"])
        a = await create_item(conn, cl["id"], label="a", sort_order=0)
        b = await create_item(conn, cl["id"], label="b", sort_order=1)
        assert a and b
        # No legs paired to either item — pure flag-flip toggles.
        await toggle_item(conn, int(a["id"]), checked=True)
        # Checklist still has b unchecked → not yet closed.
        cl_row = await get_session(conn, cl["id"])
        assert cl_row is not None
        assert cl_row["closed_at"] is None

        await toggle_item(conn, int(b["id"]), checked=True)
        # Now complete; checklist auto-closes.
        cl_row = await get_session(conn, cl["id"])
        assert cl_row is not None
        assert cl_row["closed_at"] is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_toggle_unchecked_item_does_not_close_anything(
    tmp_path: Path,
) -> None:
    """Unchecking is a pure flag flip — no session-close side
    effects. Reopening a closed chat is a deliberate user action
    that lives in the sidebar, not the checkbox."""
    from bearings.db.store import get_session

    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, cl["id"])
        item = await create_item(conn, cl["id"], label="x")
        assert item is not None
        leg = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="chat",
            checklist_item_id=int(item["id"]),
        )
        # Toggle off (was never on) — nothing to close anyway.
        await toggle_item(conn, int(item["id"]), checked=False)
        leg_row = await get_session(conn, leg["id"])
        assert leg_row is not None
        assert leg_row["closed_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_item_fields(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        item = await create_item(conn, session["id"], label="old")
        assert item is not None
        updated = await update_item(conn, item["id"], fields={"label": "new", "notes": "why"})
        assert updated is not None
        assert updated["label"] == "new"
        assert updated["notes"] == "why"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_item_removes_row(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        item = await create_item(conn, session["id"], label="doomed")
        assert item is not None
        assert await delete_item(conn, item["id"]) is True
        assert await get_item(conn, item["id"]) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_missing_item_returns_false(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await delete_item(conn, 9999) is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_reorder_items_rewrites_sort_order(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        a = await create_item(conn, session["id"], label="a")
        b = await create_item(conn, session["id"], label="b")
        c = await create_item(conn, session["id"], label="c")
        assert a and b and c
        # Reverse the order.
        written = await reorder_items(conn, session["id"], [c["id"], b["id"], a["id"]])
        assert written == 3
        checklist = await get_checklist(conn, session["id"])
        assert checklist is not None
        labels_in_order = [i["label"] for i in checklist["items"]]
        assert labels_in_order == ["c", "b", "a"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_reorder_ignores_foreign_ids(tmp_path: Path) -> None:
    """Reordering with an id belonging to a different checklist must
    silently skip that id — a client can't reorder a list it doesn't
    own even if it guesses the id."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        s1 = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        s2 = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, s1["id"])
        await create_checklist(conn, s2["id"])
        a = await create_item(conn, s1["id"], label="a")
        foreign = await create_item(conn, s2["id"], label="foreign")
        assert a and foreign
        # Try to reorder s1 using a foreign id mixed in.
        written = await reorder_items(conn, s1["id"], [foreign["id"], a["id"]])
        # Only the own-checklist row should be rewritten.
        assert written == 1
    finally:
        await conn.close()


# --- cascade ---------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_session_cascades_to_checklist(tmp_path: Path) -> None:
    """Deleting the session row should sweep the checklist and its
    items via `ON DELETE CASCADE`. Guards against orphan rows."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, session["id"])
        item = await create_item(conn, session["id"], label="to-cascade")
        assert item is not None
        await delete_session(conn, session["id"])
        assert await get_session(conn, session["id"]) is None
        assert await get_checklist(conn, session["id"]) is None
        assert await get_item(conn, item["id"]) is None
    finally:
        await conn.close()


# --- blocked-item cascade ----------------------------------------
#
# Migration 0033 adds `blocked_at` as a third item state. The cascade
# rules need to treat blocked siblings as "not done" so a parent never
# rolls up to checked while one of its children is still blocked-on-Dave.
# Resolution path (blocked → done) clears `blocked_at` in the same write.


@pytest.mark.asyncio
async def test_blocked_child_keeps_parent_unchecked_on_sibling_check(
    tmp_path: Path,
) -> None:
    """Two children: A blocked, B checked. Parent must stay unchecked.
    The cascade query that aggregates child state has to count blocked
    children as not-done, otherwise a partial-completion parent would
    auto-close prematurely."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(conn, working_dir="/tmp", model="m", kind="checklist")
        await create_checklist(conn, session["id"])
        parent = await create_item(conn, session["id"], label="parent")
        a = await create_item(conn, session["id"], label="A", parent_item_id=parent["id"])
        b = await create_item(conn, session["id"], label="B", parent_item_id=parent["id"])
        await set_item_blocked(conn, a["id"], category="payment", reason="need card")
        await toggle_item(conn, b["id"], checked=True)
        parent_row = await get_item(conn, parent["id"])
        assert parent_row is not None
        assert parent_row["checked_at"] is None, (
            "parent must not auto-roll-up while a child is blocked"
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_blocking_a_child_unrolls_a_previously_checked_parent(
    tmp_path: Path,
) -> None:
    """A and B both checked → parent rolled up. A then becomes blocked.
    Parent must be unrolled (`checked_at` cleared) — otherwise the
    sidebar would show a stale checked parent over an active blocked
    leaf."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(conn, working_dir="/tmp", model="m", kind="checklist")
        await create_checklist(conn, session["id"])
        parent = await create_item(conn, session["id"], label="parent")
        a = await create_item(conn, session["id"], label="A", parent_item_id=parent["id"])
        b = await create_item(conn, session["id"], label="B", parent_item_id=parent["id"])
        await toggle_item(conn, a["id"], checked=True)
        await toggle_item(conn, b["id"], checked=True)
        parent_after_check = await get_item(conn, parent["id"])
        assert parent_after_check is not None
        assert parent_after_check["checked_at"] is not None, (
            "preconditions: both children checked, parent should have rolled up"
        )
        # Now block A. Parent must un-roll.
        await set_item_blocked(conn, a["id"], category="physical_action", reason="plug it in")
        parent_after_block = await get_item(conn, parent["id"])
        assert parent_after_block is not None
        assert parent_after_block["checked_at"] is None, (
            "blocking a previously-checked child must clear the parent's rollup"
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_is_checklist_complete_false_with_blocked_root_item(
    tmp_path: Path,
) -> None:
    """A whole-checklist completion check must respect blocked items.
    Otherwise the auto-close cascade would close the parent checklist
    session and Dave would lose the navigation entry."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(conn, working_dir="/tmp", model="m", kind="checklist")
        await create_checklist(conn, session["id"])
        a = await create_item(conn, session["id"], label="A", sort_order=0)
        b = await create_item(conn, session["id"], label="B", sort_order=1)
        await toggle_item(conn, b["id"], checked=True)
        await set_item_blocked(conn, a["id"], category="identity_or_2fa", reason="need 2fa")
        assert await is_checklist_complete(conn, session["id"]) is False
        # Resolve the block by checking off A — completion becomes true.
        await toggle_item(conn, a["id"], checked=True)
        assert await is_checklist_complete(conn, session["id"]) is True
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_checking_a_blocked_item_clears_blocked_fields(tmp_path: Path) -> None:
    """Resolution path: Dave acts, agent re-engages and emits
    CHECKLIST_ITEM_DONE, the close-cascade calls `toggle_item(checked=True)`.
    That call must clear `blocked_at`/category/reason in the same
    transaction so the item ends up cleanly done with no stale
    blocked stamp left over."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(conn, working_dir="/tmp", model="m", kind="checklist")
        await create_checklist(conn, session["id"])
        item = await create_item(conn, session["id"], label="paid")
        await set_item_blocked(conn, item["id"], category="payment", reason="need card")
        before = await get_item(conn, item["id"])
        assert before is not None
        assert before["blocked_at"] is not None
        assert before["checked_at"] is None
        # Simulate the resolution: agent emits done, toggle fires.
        await toggle_item(conn, item["id"], checked=True)
        after = await get_item(conn, item["id"])
        assert after is not None
        assert after["checked_at"] is not None
        assert after["blocked_at"] is None
        assert after["blocked_reason_category"] is None
        assert after["blocked_reason_text"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_unchecking_does_not_re_stamp_blocked(tmp_path: Path) -> None:
    """Uncheck is a rollback to 'open,' not a transition to 'blocked.'
    `toggle_item(checked=False)` must leave `blocked_at` NULL.
    Otherwise a UI uncheck of a normal done item would silently flag
    it as blocked-on-Dave, which is wrong."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        session = await create_session(conn, working_dir="/tmp", model="m", kind="checklist")
        await create_checklist(conn, session["id"])
        item = await create_item(conn, session["id"], label="x")
        await toggle_item(conn, item["id"], checked=True)
        await toggle_item(conn, item["id"], checked=False)
        row = await get_item(conn, item["id"])
        assert row is not None
        assert row["checked_at"] is None
        assert row["blocked_at"] is None
    finally:
        await conn.close()
