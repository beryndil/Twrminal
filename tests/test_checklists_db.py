"""DB-layer integration tests for ``bearings.db.checklists``.

Covers the item CRUD round-trip + parent/child nesting + sort_order
collision-free renumbering + paired-chat link-and-leg recording +
Tab/Shift-Tab indent/outdent semantics from
``docs/behavior/checklists.md``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.config.constants import (
    CHECKLIST_SORT_ORDER_STEP,
    ITEM_OUTCOME_BLOCKED,
    ITEM_OUTCOME_FAILED,
    ITEM_OUTCOME_SKIPPED,
    PAIRED_CHAT_SPAWNED_BY_DRIVER,
    PAIRED_CHAT_SPAWNED_BY_USER,
)
from bearings.db import get_connection_factory, load_schema
from bearings.db.checklists import (
    ChecklistItem,
    PairedChatLeg,
    cascade_parent_checks,
    clear_outcome,
    clear_paired_chat,
    close_leg,
    count_legs,
    create,
    delete,
    get,
    indent,
    is_leaf,
    list_children,
    list_for_checklist,
    list_legs,
    mark_checked,
    mark_outcome,
    mark_unchecked,
    move_to_parent,
    outdent,
    record_leg,
    renumber_siblings,
    set_paired_chat,
    update_label,
    update_notes,
)


@pytest.fixture
async def connection(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    factory = get_connection_factory(tmp_path / "checklists.db")
    async with factory() as conn:
        await load_schema(conn)
        # Need a chat-kind session row so FKs from checklist_items.checklist_id
        # resolve. The session FK requires sessions(id) with kind in CHECK.
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("chk_1", "checklist", "T", "/tmp", "sonnet", "2026-01-01", "2026-01-01"),
        )
        await conn.commit()
        yield conn


async def test_create_and_get_round_trip(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="root")
    assert isinstance(item, ChecklistItem)
    assert item.label == "root"
    assert item.parent_item_id is None
    fetched = await get(connection, item.id)
    assert fetched is not None
    assert fetched.label == "root"
    assert fetched.sort_order == CHECKLIST_SORT_ORDER_STEP


async def test_create_with_parent_assigns_step_sort(
    connection: aiosqlite.Connection,
) -> None:
    parent = await create(connection, checklist_id="chk_1", label="P")
    child_a = await create(connection, checklist_id="chk_1", label="A", parent_item_id=parent.id)
    child_b = await create(connection, checklist_id="chk_1", label="B", parent_item_id=parent.id)
    assert child_a.sort_order == CHECKLIST_SORT_ORDER_STEP
    assert child_b.sort_order == 2 * CHECKLIST_SORT_ORDER_STEP


async def test_get_returns_none_when_absent(connection: aiosqlite.Connection) -> None:
    assert await get(connection, 99_999) is None


async def test_list_for_checklist_orders_roots_first(
    connection: aiosqlite.Connection,
) -> None:
    p = await create(connection, checklist_id="chk_1", label="P")
    await create(connection, checklist_id="chk_1", label="C", parent_item_id=p.id)
    await create(connection, checklist_id="chk_1", label="R")
    items = await list_for_checklist(connection, "chk_1")
    # Roots first (NULL parent), then children. Order: P, R (roots), then C.
    parent_ids = [item.parent_item_id for item in items]
    assert parent_ids[0] is None
    assert parent_ids[1] is None
    assert parent_ids[2] == p.id
    assert {item.label for item in items} == {"P", "R", "C"}


async def test_list_children_of_root_and_parent(
    connection: aiosqlite.Connection,
) -> None:
    parent = await create(connection, checklist_id="chk_1", label="P")
    a = await create(connection, checklist_id="chk_1", label="A", parent_item_id=parent.id)
    b = await create(connection, checklist_id="chk_1", label="B", parent_item_id=parent.id)
    roots = await list_children(connection, checklist_id="chk_1", parent_item_id=None)
    assert [r.label for r in roots] == ["P"]
    children = await list_children(connection, checklist_id="chk_1", parent_item_id=parent.id)
    assert [c.id for c in children] == [a.id, b.id]


async def test_is_leaf_distinguishes_parent_from_leaf(
    connection: aiosqlite.Connection,
) -> None:
    parent = await create(connection, checklist_id="chk_1", label="P")
    leaf = await create(connection, checklist_id="chk_1", label="L", parent_item_id=parent.id)
    assert await is_leaf(connection, leaf.id) is True
    assert await is_leaf(connection, parent.id) is False


async def test_update_label_and_notes(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="L")
    updated = await update_label(connection, item.id, label="L'")
    assert updated is not None
    assert updated.label == "L'"
    notes = await update_notes(connection, item.id, notes="some notes")
    assert notes is not None
    assert notes.notes == "some notes"
    cleared = await update_notes(connection, item.id, notes=None)
    assert cleared is not None
    assert cleared.notes is None


async def test_update_label_rejects_empty(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="L")
    with pytest.raises(ValueError, match="label"):
        await update_label(connection, item.id, label="")


async def test_update_returns_none_on_missing(
    connection: aiosqlite.Connection,
) -> None:
    assert await update_label(connection, 99_999, label="x") is None
    assert await update_notes(connection, 99_999, notes="x") is None


async def test_delete_removes_subtree(connection: aiosqlite.Connection) -> None:
    parent = await create(connection, checklist_id="chk_1", label="P")
    await create(connection, checklist_id="chk_1", label="C", parent_item_id=parent.id)
    removed = await delete(connection, parent.id)
    assert removed is True
    assert await delete(connection, parent.id) is False
    items = await list_for_checklist(connection, "chk_1")
    assert items == []


async def test_mark_checked_clears_blocked(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="L")
    await mark_outcome(connection, item.id, category=ITEM_OUTCOME_BLOCKED, reason="why")
    checked = await mark_checked(connection, item.id)
    assert checked is not None
    assert checked.checked_at is not None
    assert checked.blocked_at is None
    assert checked.blocked_reason_category is None


async def test_mark_unchecked_clears_check(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="L")
    await mark_checked(connection, item.id)
    unchecked = await mark_unchecked(connection, item.id)
    assert unchecked is not None
    assert unchecked.checked_at is None


async def test_mark_outcome_clears_check(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="L")
    await mark_checked(connection, item.id)
    blocked = await mark_outcome(connection, item.id, category=ITEM_OUTCOME_FAILED, reason="boom")
    assert blocked is not None
    assert blocked.checked_at is None
    assert blocked.blocked_reason_category == ITEM_OUTCOME_FAILED
    assert blocked.blocked_reason_text == "boom"


async def test_mark_outcome_validates_category(
    connection: aiosqlite.Connection,
) -> None:
    item = await create(connection, checklist_id="chk_1", label="L")
    with pytest.raises(ValueError, match="category"):
        await mark_outcome(connection, item.id, category="not-a-category")


async def test_clear_outcome_resets(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="L")
    await mark_outcome(connection, item.id, category=ITEM_OUTCOME_SKIPPED)
    cleared = await clear_outcome(connection, item.id)
    assert cleared is not None
    assert cleared.blocked_at is None


async def _make_chat_session(connection: aiosqlite.Connection, session_id: str) -> None:
    """Insert a chat-kind session so FKs from chat_session_id resolve."""
    await connection.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, "chat", "C", "/tmp", "sonnet", "2026-01-01", "2026-01-01"),
    )
    await connection.commit()


async def test_set_paired_chat_links_leaf(connection: aiosqlite.Connection) -> None:
    leaf = await create(connection, checklist_id="chk_1", label="L")
    await _make_chat_session(connection, "chat_a")
    linked = await set_paired_chat(connection, leaf.id, chat_session_id="chat_a")
    assert linked is not None
    assert linked.chat_session_id == "chat_a"


async def test_set_paired_chat_rejects_non_leaf(
    connection: aiosqlite.Connection,
) -> None:
    parent = await create(connection, checklist_id="chk_1", label="P")
    await create(connection, checklist_id="chk_1", label="C", parent_item_id=parent.id)
    await _make_chat_session(connection, "chat_z")
    with pytest.raises(ValueError, match="leaves-only"):
        await set_paired_chat(connection, parent.id, chat_session_id="chat_z")


async def test_clear_paired_chat(connection: aiosqlite.Connection) -> None:
    leaf = await create(connection, checklist_id="chk_1", label="L")
    await _make_chat_session(connection, "chat_b")
    await set_paired_chat(connection, leaf.id, chat_session_id="chat_b")
    cleared = await clear_paired_chat(connection, leaf.id)
    assert cleared is not None
    assert cleared.chat_session_id is None


async def test_record_leg_round_trip(connection: aiosqlite.Connection) -> None:
    leaf = await create(connection, checklist_id="chk_1", label="L")
    await _make_chat_session(connection, "chat_l1")
    leg = await record_leg(
        connection,
        checklist_item_id=leaf.id,
        chat_session_id="chat_l1",
        spawned_by=PAIRED_CHAT_SPAWNED_BY_USER,
    )
    assert isinstance(leg, PairedChatLeg)
    assert leg.leg_number == 1
    assert leg.spawned_by == PAIRED_CHAT_SPAWNED_BY_USER
    legs = await list_legs(connection, leaf.id)
    assert len(legs) == 1
    assert await count_legs(connection, leaf.id) == 1


async def test_record_leg_increments_leg_number(
    connection: aiosqlite.Connection,
) -> None:
    leaf = await create(connection, checklist_id="chk_1", label="L")
    await _make_chat_session(connection, "chat_l1")
    await _make_chat_session(connection, "chat_l2")
    leg1 = await record_leg(
        connection,
        checklist_item_id=leaf.id,
        chat_session_id="chat_l1",
        spawned_by=PAIRED_CHAT_SPAWNED_BY_DRIVER,
    )
    leg2 = await record_leg(
        connection,
        checklist_item_id=leaf.id,
        chat_session_id="chat_l2",
        spawned_by=PAIRED_CHAT_SPAWNED_BY_DRIVER,
    )
    assert leg1.leg_number == 1
    assert leg2.leg_number == 2


async def test_record_leg_rejects_unknown_spawned_by(
    connection: aiosqlite.Connection,
) -> None:
    leaf = await create(connection, checklist_id="chk_1", label="L")
    with pytest.raises(ValueError, match="spawned_by"):
        await record_leg(
            connection,
            checklist_item_id=leaf.id,
            chat_session_id="x",
            spawned_by="bogus",
        )


async def test_close_leg_stamps_closed_at(connection: aiosqlite.Connection) -> None:
    leaf = await create(connection, checklist_id="chk_1", label="L")
    await _make_chat_session(connection, "chat_l1")
    leg = await record_leg(
        connection,
        checklist_item_id=leaf.id,
        chat_session_id="chat_l1",
        spawned_by=PAIRED_CHAT_SPAWNED_BY_USER,
    )
    closed = await close_leg(connection, leg.id)
    assert closed is True
    legs = await list_legs(connection, leaf.id)
    assert legs[0].closed_at is not None


async def test_move_to_parent_rejects_self(connection: aiosqlite.Connection) -> None:
    item = await create(connection, checklist_id="chk_1", label="X")
    with pytest.raises(ValueError, match="itself"):
        await move_to_parent(connection, item.id, parent_item_id=item.id)


async def test_move_to_parent_rejects_into_subtree(
    connection: aiosqlite.Connection,
) -> None:
    parent = await create(connection, checklist_id="chk_1", label="P")
    child = await create(connection, checklist_id="chk_1", label="C", parent_item_id=parent.id)
    with pytest.raises(ValueError, match="subtree"):
        await move_to_parent(connection, parent.id, parent_item_id=child.id)


async def test_move_to_parent_reparents_with_step_sort(
    connection: aiosqlite.Connection,
) -> None:
    a = await create(connection, checklist_id="chk_1", label="A")
    b = await create(connection, checklist_id="chk_1", label="B")
    moved = await move_to_parent(connection, b.id, parent_item_id=a.id)
    assert moved is not None
    assert moved.parent_item_id == a.id


async def test_renumber_siblings_compacts(connection: aiosqlite.Connection) -> None:
    a = await create(connection, checklist_id="chk_1", label="A")
    b = await create(connection, checklist_id="chk_1", label="B")
    # Force collisions: set both to sort_order 1
    await connection.execute(
        "UPDATE checklist_items SET sort_order = 1 WHERE id IN (?, ?)",
        (a.id, b.id),
    )
    await connection.commit()
    await renumber_siblings(connection, checklist_id="chk_1", parent_item_id=None)
    rows = await list_for_checklist(connection, "chk_1")
    sort_orders = [item.sort_order for item in rows]
    assert sort_orders == [CHECKLIST_SORT_ORDER_STEP, 2 * CHECKLIST_SORT_ORDER_STEP]


async def test_indent_nests_under_previous_sibling(
    connection: aiosqlite.Connection,
) -> None:
    a = await create(connection, checklist_id="chk_1", label="A")
    b = await create(connection, checklist_id="chk_1", label="B")
    indented = await indent(connection, b.id)
    assert indented is not None
    assert indented.parent_item_id == a.id


async def test_indent_noop_at_first_sibling(
    connection: aiosqlite.Connection,
) -> None:
    first = await create(connection, checklist_id="chk_1", label="A")
    await create(connection, checklist_id="chk_1", label="B")
    same = await indent(connection, first.id)
    assert same is not None
    assert same.parent_item_id is None


async def test_outdent_pops_one_level(connection: aiosqlite.Connection) -> None:
    parent = await create(connection, checklist_id="chk_1", label="P")
    child = await create(connection, checklist_id="chk_1", label="C", parent_item_id=parent.id)
    out = await outdent(connection, child.id)
    assert out is not None
    assert out.parent_item_id is None


async def test_outdent_noop_at_root(connection: aiosqlite.Connection) -> None:
    a = await create(connection, checklist_id="chk_1", label="A")
    same = await outdent(connection, a.id)
    assert same is not None
    assert same.parent_item_id is None


async def test_create_validates_label_length(
    connection: aiosqlite.Connection,
) -> None:
    with pytest.raises(ValueError, match="label"):
        await create(connection, checklist_id="chk_1", label="")


async def test_close_leg_returns_false_on_missing(
    connection: aiosqlite.Connection,
) -> None:
    assert await close_leg(connection, 99_999) is False


# ---------------------------------------------------------------------------
# feature-6-002: cascade_parent_checks
# ---------------------------------------------------------------------------


async def test_cascade_parent_checks_returns_false_when_sibling_unchecked(
    connection: aiosqlite.Connection,
) -> None:
    """Parent stays unchecked when at least one sibling is not checked."""
    parent = await create(connection, checklist_id="chk_1", label="P")
    child_a = await create(connection, checklist_id="chk_1", label="A", parent_item_id=parent.id)
    await create(connection, checklist_id="chk_1", label="B", parent_item_id=parent.id)
    await mark_checked(connection, child_a.id)
    # second child is still unchecked — cascade should not mark parent.
    result = await cascade_parent_checks(connection, child_a.id)
    assert result is False
    refreshed_parent = await get(connection, parent.id)
    assert refreshed_parent is not None
    assert refreshed_parent.checked_at is None


async def test_cascade_parent_checks_marks_parent_when_last_sibling_checked(
    connection: aiosqlite.Connection,
) -> None:
    """Parent is auto-checked when the last unchecked sibling is checked."""
    parent = await create(connection, checklist_id="chk_1", label="P")
    child_a = await create(connection, checklist_id="chk_1", label="A", parent_item_id=parent.id)
    child_b = await create(connection, checklist_id="chk_1", label="B", parent_item_id=parent.id)
    await mark_checked(connection, child_a.id)
    await mark_checked(connection, child_b.id)
    # Both children checked; cascading from child_b should mark parent.
    await cascade_parent_checks(connection, child_b.id)
    refreshed_parent = await get(connection, parent.id)
    assert refreshed_parent is not None
    assert refreshed_parent.checked_at is not None


async def test_cascade_parent_checks_walks_multiple_levels(
    connection: aiosqlite.Connection,
) -> None:
    """Cascade walks all the way to the root when each level becomes fully checked."""
    grandparent = await create(connection, checklist_id="chk_1", label="GP")
    parent = await create(
        connection, checklist_id="chk_1", label="P", parent_item_id=grandparent.id
    )
    child = await create(connection, checklist_id="chk_1", label="C", parent_item_id=parent.id)
    await mark_checked(connection, child.id)
    await cascade_parent_checks(connection, child.id)
    # Both parent and grandparent should be checked (each has only one child).
    refreshed_parent = await get(connection, parent.id)
    refreshed_gp = await get(connection, grandparent.id)
    assert refreshed_parent is not None and refreshed_parent.checked_at is not None
    assert refreshed_gp is not None and refreshed_gp.checked_at is not None


async def test_cascade_parent_checks_returns_true_when_all_roots_checked(
    connection: aiosqlite.Connection,
) -> None:
    """Returns True when all root items of the checklist are now checked."""
    # Two root leaves — check both, then cascade from the second.
    leaf_a = await create(connection, checklist_id="chk_1", label="A")
    leaf_b = await create(connection, checklist_id="chk_1", label="B")
    await mark_checked(connection, leaf_a.id)
    await mark_checked(connection, leaf_b.id)
    result = await cascade_parent_checks(connection, leaf_b.id)
    assert result is True, "all roots checked → should return True to trigger checklist close"


async def test_cascade_parent_checks_returns_false_when_root_sibling_unchecked(
    connection: aiosqlite.Connection,
) -> None:
    """Returns False when a root sibling is still unchecked."""
    leaf_a = await create(connection, checklist_id="chk_1", label="A")
    _leaf_b = await create(connection, checklist_id="chk_1", label="B")
    await mark_checked(connection, leaf_a.id)
    result = await cascade_parent_checks(connection, leaf_a.id)
    assert result is False


async def test_cascade_parent_checks_noop_on_missing_item(
    connection: aiosqlite.Connection,
) -> None:
    """cascade_parent_checks returns False gracefully for a missing item_id."""
    result = await cascade_parent_checks(connection, 99_999)
    assert result is False
