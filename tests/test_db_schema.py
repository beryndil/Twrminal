"""Schema test for the Bearings v1 DB bootstrap (item 0.4).

Covers the four contract guarantees the master item names in its
done-when:

1. **Fresh boot.** ``get_connection_factory`` + ``load_schema`` produces a
   DB whose user-table set matches the expected ten plus the
   ``session_tags`` join.
2. **Idempotent re-init.** Re-running ``load_schema`` on an existing DB
   does not raise, does not duplicate the seven seeded
   ``system_routing_rules`` rows, and leaves the table-list unchanged.
3. **Routing/usage columns** on ``messages`` exist with the spec §5
   types verbatim.
4. **Foreign-key enforcement** — ``PRAGMA foreign_keys`` is ON after
   bootstrap, and a constraint-violating insert into
   ``checklist_items.checklist_id`` raises ``IntegrityError``.

The seven default ``system_routing_rules`` rows are also asserted by
priority, executor, advisor, and reason to catch a drift in the spec
§3 verbatim seed.

References:

* ``docs/model-routing-v1-spec.md`` §3 (default rule table), §5
  (messages routing/usage columns), §4 (quota_snapshots).
* ``docs/architecture-v1.md`` §4 (RoutingDecision / RoutingRule /
  QuotaSnapshot dataclass shapes the columns mirror).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import aiosqlite
import pytest

from bearings.db import get_connection_factory, load_schema

# ---------------------------------------------------------------------------
# Expected shape — drift here when the schema legitimately changes.
# ---------------------------------------------------------------------------

# All ten tables named in the master item done-when, plus the session_tags
# join (declared inside `tags`'s comment block, required for tag↔session
# many-to-many per docs/behavior/chat.md "every chat must carry ≥1 tag").
EXPECTED_TABLES = frozenset(
    {
        "sessions",
        "messages",
        "tags",
        "session_tags",
        "tag_memories",
        "vault",
        "checklist_items",
        "paired_chats",
        "tag_routing_rules",
        "system_routing_rules",
        "quota_snapshots",
        # Item 1.3 additions — Bearings' own checkpoint table (arch §5
        # #12 keeps Bearings' named-snapshot checkpoints rather than
        # the SDK ``enable_file_checkpointing`` automatic-write
        # primitive) and the templates table (arch §1.1.3).
        "checkpoints",
        "templates",
        # Item 1.6 addition — durable mirror of the autonomous
        # checklist driver's run state per arch §1.1.4 + behavior/
        # checklists.md §"Run-control surface" (state machine,
        # counters, terminal outcome).
        "auto_driver_runs",
        # Item 1.10 addition — content-addressed file uploads metadata
        # mirror per arch §1.1.5 ``web/routes/uploads.py``. On-disk
        # body lives under the configured uploads-storage-root keyed
        # by sha256; this table is the metadata side of the contract.
        "uploads",
        # Item 3.2 addition — singleton user-preferences row (theme,
        # default_model, default_permission_mode, default_working_dir).
        "preferences",
        # 2026-05-05 addition — opaque mirror of the Claude Code CLI's
        # per-session JSONL transcript, persisted via the SDK
        # :class:`SessionStore` adapter so supervisor respawns (model
        # swap, idle reap, server restart, recovery from ERROR) restore
        # full conversation context to the new subprocess.
        "sdk_session_entries",
    }
)

# Per docs/model-routing-v1-spec.md §5 — every column the routing spec
# names, with the type the spec declares. Values are SQLite type
# affinities as reported by `PRAGMA table_info`.
EXPECTED_MESSAGES_ROUTING_COLUMNS: dict[str, str] = {
    "executor_model": "TEXT",
    "advisor_model": "TEXT",
    "effort_level": "TEXT",
    "routing_source": "TEXT",
    "routing_reason": "TEXT",
    # spec §App A ``RoutingDecision.matched_rule_id`` projection (item
    # 1.8 schema column required by spec §8 override-rate aggregator;
    # item 1.9 wires the read/write path through ``Message`` +
    # ``MessageOut``).
    "matched_rule_id": "INTEGER",
    "executor_input_tokens": "INTEGER",
    "executor_output_tokens": "INTEGER",
    "advisor_input_tokens": "INTEGER",
    "advisor_output_tokens": "INTEGER",
    "advisor_calls_count": "INTEGER",
    "cache_read_tokens": "INTEGER",
}

# Per docs/model-routing-v1-spec.md §3 default rule table.
# Tuple shape: (priority, match_type, executor_model, advisor_model, reason).
EXPECTED_SEEDED_RULES: tuple[tuple[int, str, str, str | None, str], ...] = (
    (
        10,
        "keyword",
        "opus",
        None,
        "Hard architectural reasoning — Opus solo with extended thinking",
    ),
    (
        20,
        "keyword",
        "haiku",
        "opus",
        "Mechanical task — Haiku handles 90% of Sonnet quality at fraction of cost",
    ),
    (
        30,
        "keyword",
        "haiku",
        "opus",
        "Exploration — Haiku is what Anthropic auto-selects for the Explore subagent",
    ),
    (40, "regex", "haiku", "opus", "Quick lookup"),
    (50, "length_lt", "haiku", "opus", "Short query, simple task"),
    (60, "length_gt", "sonnet", "opus", "Long context, complex problem"),
    (1000, "always", "sonnet", "opus", "Workhorse default"),
)

EXPECTED_SEEDED_RULE_COUNT = len(EXPECTED_SEEDED_RULES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """Per-test fresh DB path inside the pytest tmp directory."""
    return tmp_path / "bearings.db"


async def _list_user_tables(connection: aiosqlite.Connection) -> set[str]:
    """Return the set of user-defined table names (excludes sqlite internals)."""
    rows = await connection.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    # rows is an iterable of aiosqlite.Row; first column is the table name.
    return {str(row[0]) for row in rows}


async def _column_types(connection: aiosqlite.Connection, table: str) -> dict[str, str]:
    """Return ``{column_name: declared_type}`` for ``table``."""
    rows = await connection.execute_fetchall(f"PRAGMA table_info({table})")
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk.
    return {str(row[1]): str(row[2]) for row in rows}


async def _scalar(connection: aiosqlite.Connection, sql: str) -> int:
    """Run ``sql`` (must produce one row, one column) and return that value as int."""
    rows = list(await connection.execute_fetchall(sql))
    return int(rows[0][0])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_fresh_boot_creates_all_tables(database_path: Path) -> None:
    """Fresh boot: factory opens an empty DB, schema produces all 10 tables."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        tables = await _list_user_tables(connection)

    assert tables == EXPECTED_TABLES, (
        f"unexpected tables: missing={EXPECTED_TABLES - tables}, extra={tables - EXPECTED_TABLES}"
    )


async def test_fresh_boot_seeds_seven_default_system_rules(
    database_path: Path,
) -> None:
    """Per spec §3 default table — exactly seven rows seeded on fresh boot."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        rows = await connection.execute_fetchall(
            "SELECT priority, match_type, executor_model, advisor_model, reason "
            "FROM system_routing_rules WHERE seeded = 1 ORDER BY priority"
        )
        seeded = [(int(row[0]), str(row[1]), str(row[2]), row[3], str(row[4])) for row in rows]

    assert len(seeded) == EXPECTED_SEEDED_RULE_COUNT
    assert tuple(seeded) == EXPECTED_SEEDED_RULES


async def test_idempotent_reinit_does_not_duplicate_or_error(
    database_path: Path,
) -> None:
    """Re-running ``load_schema`` on an existing DB is a clean no-op."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        first_pass_tables = await _list_user_tables(connection)
        first_pass_rule_count = await _scalar(
            connection,
            "SELECT COUNT(*) FROM system_routing_rules WHERE seeded = 1",
        )

    # Re-open and re-apply — the production code path for boot-after-restart.
    async with factory() as connection:
        await load_schema(connection)  # must not raise
        second_pass_tables = await _list_user_tables(connection)
        second_pass_rule_count = await _scalar(
            connection,
            "SELECT COUNT(*) FROM system_routing_rules WHERE seeded = 1",
        )

    assert first_pass_tables == second_pass_tables == EXPECTED_TABLES
    assert first_pass_rule_count == EXPECTED_SEEDED_RULE_COUNT
    assert second_pass_rule_count == EXPECTED_SEEDED_RULE_COUNT


async def test_messages_has_routing_and_usage_columns_per_spec(
    database_path: Path,
) -> None:
    """All spec §5 per-message routing/usage columns exist with correct types."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        column_types = await _column_types(connection, "messages")

    for column, expected_type in EXPECTED_MESSAGES_ROUTING_COLUMNS.items():
        assert column in column_types, f"messages.{column} missing"
        assert column_types[column] == expected_type, (
            f"messages.{column} has type {column_types[column]!r}, expected {expected_type!r}"
        )


async def test_tags_has_class_and_sort_order_columns(database_path: Path) -> None:
    """Tag-class feature columns are present after bootstrap (fresh DB)."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        column_types = await _column_types(connection, "tags")

    assert "class" in column_types, "tags.class missing — schema.sql or _ADDED_COLUMNS regression"
    assert column_types["class"] == "TEXT"
    assert "sort_order" in column_types, "tags.sort_order missing"
    assert column_types["sort_order"] == "INTEGER"


async def test_tags_class_check_constraint_rejects_unknown(database_path: Path) -> None:
    """The CHECK on ``tags.class`` enforces the alphabet at the DB layer."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        with pytest.raises(aiosqlite.IntegrityError):
            await connection.execute(
                "INSERT INTO tags (name, class, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (
                    "bad",
                    "milestone",
                    "2026-04-28T00:00:00+00:00",
                    "2026-04-28T00:00:00+00:00",
                ),
            )
            await connection.commit()


async def test_tags_class_sort_order_index_exists(database_path: Path) -> None:
    """``idx_tags_class_sort_order`` index is created so listings stay cheap."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        rows = await connection.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tags'"
        )
        index_names = {str(row[0]) for row in rows}

    assert "idx_tags_class_sort_order" in index_names, (
        f"expected idx_tags_class_sort_order in {sorted(index_names)}"
    )


async def test_tags_added_columns_apply_to_pre_class_db(database_path: Path) -> None:
    """A DB created before the class column gets the column added on next bootstrap.

    Simulates an existing v1 install that pre-dates the tag-class feature
    by creating ``tags`` with the original column set, then re-running
    :func:`load_schema` and verifying the new columns + index appear via
    the ``_ADDED_COLUMNS`` ALTER path.
    """
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        # Pre-class shape — every column the original schema.sql shipped
        # *before* the tag-class feature. The ``IF NOT EXISTS`` clause in
        # the bootstrap-time CREATE TABLE will skip on re-init, leaving
        # the legacy shape intact for the ALTER pass to fix up.
        await connection.execute(
            "CREATE TABLE tags ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL UNIQUE, "
            "color TEXT, "
            "default_model TEXT, "
            "working_dir TEXT, "
            "pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)), "
            "created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL"
            ")"
        )
        await connection.commit()

        # Now re-run bootstrap — _ADDED_COLUMNS should ALTER in class +
        # sort_order without touching the existing rows.
        await connection.execute(
            "INSERT INTO tags (name, created_at, updated_at) VALUES (?, ?, ?)",
            ("legacy", "2026-04-28T00:00:00+00:00", "2026-04-28T00:00:00+00:00"),
        )
        await connection.commit()

        await load_schema(connection)
        column_types = await _column_types(connection, "tags")
        assert "class" in column_types
        assert "sort_order" in column_types

        # Existing row gets the column DEFAULTs.
        rows = list(
            await connection.execute_fetchall(
                "SELECT class, sort_order FROM tags WHERE name = ?", ("legacy",)
            )
        )
        assert len(rows) == 1
        assert str(rows[0][0]) == "general"
        assert int(rows[0][1]) == 0


async def test_foreign_keys_pragma_is_on_after_bootstrap(
    database_path: Path,
) -> None:
    """Bootstrap enables FK enforcement on the connection it touches."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)
        # PRAGMA returns a single row with a single 0/1 column.
        assert await _scalar(connection, "PRAGMA foreign_keys") == 1


async def test_foreign_key_violation_is_rejected(database_path: Path) -> None:
    """``checklist_items.checklist_id`` FK is enforced — bad ref raises."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        await load_schema(connection)

        # Inserting a checklist_items row whose checklist_id does not match
        # any sessions(id) must raise IntegrityError because the FK is
        # active and ON DELETE CASCADE is declared on the relationship.
        with pytest.raises(aiosqlite.IntegrityError):
            await connection.execute(
                "INSERT INTO checklist_items "
                "(checklist_id, label, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "no-such-session-id",
                    "stray item",
                    0,
                    "2026-04-28T00:00:00+00:00",
                    "2026-04-28T00:00:00+00:00",
                ),
            )
            await connection.commit()


async def test_seeded_rule_has_no_duplicate_priorities(
    database_path: Path,
) -> None:
    """Partial unique index — re-applying schema preserves single-row-per-priority."""
    factory = get_connection_factory(database_path)
    async with factory() as connection:
        # Apply twice in the same connection scope.
        await load_schema(connection)
        await load_schema(connection)

        rows = await connection.execute_fetchall(
            "SELECT priority, COUNT(*) FROM system_routing_rules WHERE seeded = 1 GROUP BY priority"
        )
        per_priority_counts = {int(row[0]): int(row[1]) for row in rows}

    assert per_priority_counts == {10: 1, 20: 1, 30: 1, 40: 1, 50: 1, 60: 1, 1000: 1}


async def test_hand_verify_recipe_runs_clean() -> None:
    """End-to-end mirror of the hand-verify recipe in item-0.4 instructions.

    Uses a tempfile path outside the pytest tmp_path fixture to make the
    test resilient to a future change of the fixture name; this test is
    the literal sequence the auditor runs from a fresh shell.
    """
    with tempfile.TemporaryDirectory() as workspace:
        database_path = Path(workspace) / "test.db"
        factory = get_connection_factory(database_path)

        async with factory() as connection:
            await load_schema(connection)
            rows = await connection.execute_fetchall(
                "SELECT priority FROM system_routing_rules WHERE seeded = 1 ORDER BY priority"
            )
            priorities = [int(row[0]) for row in rows]

        # Re-run against the same path — confirmed idempotent.
        async with factory() as connection:
            await load_schema(connection)
            rows_after_reinit = await connection.execute_fetchall(
                "SELECT priority FROM system_routing_rules WHERE seeded = 1 ORDER BY priority"
            )
            priorities_after_reinit = [int(row[0]) for row in rows_after_reinit]

    assert priorities == [10, 20, 30, 40, 50, 60, 1000]
    assert priorities == priorities_after_reinit
