"""Severity-group invariants and the v0.2.14 sidebar filter combination
(migration 0021). Covers the app-layer "exactly-one severity" rule in
attach_tag, the default-severity backfill on session create/import, and
the AND-between-groups / OR-within-group query shape in list_sessions."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bearings.db.store import (
    attach_tag,
    create_session,
    create_tag,
    delete_tag,
    ensure_default_severity,
    get_default_severity_tag_id,
    init_db,
    list_session_tags,
    list_sessions,
    list_tags,
    session_has_severity_tag,
)

# --- migration + seed ------------------------------------------------


@pytest.mark.asyncio
async def test_migration_seeds_five_severity_tags(tmp_path: Path) -> None:
    """The seed block in 0021 drops exactly five rows, ordered
    Blocker → Quality of Life. Colors are the green→red Tailwind hex
    ramp from the design."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute(
            "SELECT name, color, sort_order FROM tags "
            "WHERE tag_group = 'severity' ORDER BY sort_order"
        ) as cursor:
            rows = [dict(r) async for r in cursor]
        names = [r["name"] for r in rows]
        assert names == ["Blocker", "Critical", "Medium", "Low", "Quality of Life"]
        # Colors landed — don't pin exact hex, just insist they're all set.
        assert all(r["color"] for r in rows)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_migration_backfills_low_on_existing_sessions(tmp_path: Path) -> None:
    """Sessions created before 0021 land without a severity. The
    migration backfills 'Low' idempotently; re-running the init is a
    no-op because INSERT OR IGNORE."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        rows = await list_session_tags(conn, sess["id"])
        # Fresh session goes through ensure_default_severity on create
        # only if callers wire it; direct store call here leaves the
        # session with no tags. The important check: the DB migration
        # itself populated the default severity tag so the backfill can
        # succeed.
        default_id = await get_default_severity_tag_id(conn)
        assert default_id is not None
        # ensure_default_severity is idempotent — attaches on first call,
        # no-op on second.
        assert await ensure_default_severity(conn, sess["id"]) is True
        assert await ensure_default_severity(conn, sess["id"]) is False
        rows = await list_session_tags(conn, sess["id"])
        assert [r["name"] for r in rows] == ["Low"]
    finally:
        await conn.close()


# --- attach_tag enforcement ------------------------------------------


@pytest.mark.asyncio
async def test_attach_severity_replaces_existing_severity(tmp_path: Path) -> None:
    """Core "physical law" invariant: attaching a new severity detaches
    any other severity tag inside the same commit. No transient
    two-severity window."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await ensure_default_severity(conn, sess["id"])
        # Sanity: session starts with exactly one severity (Low).
        tags = await list_session_tags(conn, sess["id"])
        sevs = [t for t in tags if t["tag_group"] == "severity"]
        assert [t["name"] for t in sevs] == ["Low"]

        # Attach Blocker — Low should disappear in the same step.
        async with conn.execute("SELECT id FROM tags WHERE name = 'Blocker'") as cursor:
            blocker_row = await cursor.fetchone()
            assert blocker_row is not None
            blocker_id = int(blocker_row["id"])
        assert await attach_tag(conn, sess["id"], blocker_id) is True
        tags = await list_session_tags(conn, sess["id"])
        sevs = [t for t in tags if t["tag_group"] == "severity"]
        assert [t["name"] for t in sevs] == ["Blocker"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_attach_same_severity_is_idempotent(tmp_path: Path) -> None:
    """Re-attaching the currently-attached severity is a no-op — the
    `tag_id != ?` clause short-circuits the swap delete and INSERT OR
    IGNORE preserves the existing row."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await ensure_default_severity(conn, sess["id"])
        default_id = await get_default_severity_tag_id(conn)
        assert default_id is not None
        # Re-attach the same severity twice — count stays at one.
        assert await attach_tag(conn, sess["id"], default_id) is True
        assert await attach_tag(conn, sess["id"], default_id) is True
        tags = await list_session_tags(conn, sess["id"])
        sevs = [t for t in tags if t["tag_group"] == "severity"]
        assert len(sevs) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_attach_general_tag_leaves_severity_alone(tmp_path: Path) -> None:
    """Only the severity group is subject to the exactly-one rule.
    Attaching a general tag must not touch any existing severity."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await ensure_default_severity(conn, sess["id"])
        infra = await create_tag(conn, name="infra")  # default group='general'
        assert await attach_tag(conn, sess["id"], infra["id"]) is True
        tags = await list_session_tags(conn, sess["id"])
        names = {t["name"] for t in tags}
        # Low survives.
        assert "Low" in names
        assert "infra" in names
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_severity_tag_orphans_sessions_silently(tmp_path: Path) -> None:
    """Design call: deleting a severity tag leaves affected sessions
    severity-less rather than reassigning. Session row survives; the
    sidebar just renders without a shield. ensure_default_severity
    won't re-add until the user re-creates a 'Low' tag."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await ensure_default_severity(conn, sess["id"])
        default_id = await get_default_severity_tag_id(conn)
        assert default_id is not None
        await delete_tag(conn, default_id)
        # Session still exists, severity gone.
        assert await session_has_severity_tag(conn, sess["id"]) is False
        # Backfill is a no-op because no 'Low' tag exists to attach.
        assert await ensure_default_severity(conn, sess["id"]) is False
    finally:
        await conn.close()


# --- list_sessions filter combinations -------------------------------


@pytest.mark.asyncio
async def test_list_sessions_severity_tags_filter(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        # Two sessions — one Blocker, one Low.
        s1 = await create_session(conn, working_dir="/a", model="m", title="a")
        s2 = await create_session(conn, working_dir="/b", model="m", title="b")
        async with conn.execute("SELECT id, name FROM tags WHERE tag_group='severity'") as cursor:
            sev_rows = {r["name"]: int(r["id"]) async for r in cursor}
        await attach_tag(conn, s1["id"], sev_rows["Blocker"])
        await attach_tag(conn, s2["id"], sev_rows["Low"])

        rows = await list_sessions(conn, severity_tag_ids=[sev_rows["Blocker"]])
        assert {r["id"] for r in rows} == {s1["id"]}
        # OR within-group: Blocker OR Low returns both.
        rows = await list_sessions(conn, severity_tag_ids=[sev_rows["Blocker"], sev_rows["Low"]])
        assert {r["id"] for r in rows} == {s1["id"], s2["id"]}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_sessions_severity_and_general_combine_with_and(tmp_path: Path) -> None:
    """Combining the two axes narrows the result set — a session must
    match both to be returned. This is what made severity worth a
    dedicated group instead of a naming convention."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        s1 = await create_session(conn, working_dir="/a", model="m", title="a")
        s2 = await create_session(conn, working_dir="/b", model="m", title="b")
        async with conn.execute("SELECT id, name FROM tags WHERE tag_group='severity'") as cursor:
            sev_rows = {r["name"]: int(r["id"]) async for r in cursor}
        infra = await create_tag(conn, name="infra")
        await attach_tag(conn, s1["id"], sev_rows["Blocker"])
        await attach_tag(conn, s1["id"], infra["id"])
        await attach_tag(conn, s2["id"], sev_rows["Blocker"])
        # s2 has severity=Blocker but no infra tag.
        rows = await list_sessions(
            conn,
            tag_ids=[infra["id"]],
            severity_tag_ids=[sev_rows["Blocker"]],
        )
        assert {r["id"] for r in rows} == {s1["id"]}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_sessions_no_severity_sentinel(tmp_path: Path) -> None:
    """Sentinel `-1` in `severity_tag_ids` means "sessions with no
    severity tag attached" — the sidebar exposes this as a virtual
    'No severity' row so orphaned sessions (severity deleted, never
    reassigned) are findable. Combines with real severity ids via OR."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        # s_blocker: carries Blocker.
        # s_orphan: had Low, then the Low tag was deleted — severity gone.
        # s_low: plain Low-tagged session — acts as control.
        s_blocker = await create_session(conn, working_dir="/a", model="m", title="a")
        s_orphan = await create_session(conn, working_dir="/b", model="m", title="b")
        s_low = await create_session(conn, working_dir="/c", model="m", title="c")
        async with conn.execute("SELECT id, name FROM tags WHERE tag_group='severity'") as cursor:
            sev = {r["name"]: int(r["id"]) async for r in cursor}
        await attach_tag(conn, s_blocker["id"], sev["Blocker"])
        await attach_tag(conn, s_low["id"], sev["Low"])
        # Orphan the middle session by attaching Low then deleting the
        # Low row entirely. delete_tag cascades session_tags.
        await attach_tag(conn, s_orphan["id"], sev["Low"])
        # Re-read Low id after the delete won't work, so capture first,
        # but note: we still have s_low that carries Low too. Deleting
        # the Low tag wipes it from BOTH sessions. Instead, detach just
        # the orphan's severity by deleting Blocker for that one — no,
        # that still leaves a severity on others. Cleanest path: detach
        # the orphan directly.
        await conn.execute(
            "DELETE FROM session_tags WHERE session_id = ?",
            (s_orphan["id"],),
        )
        await conn.commit()

        # Sentinel-only: just the orphan.
        rows = await list_sessions(conn, severity_tag_ids=[-1])
        assert {r["id"] for r in rows} == {s_orphan["id"]}

        # Sentinel + Blocker (OR): orphan + the Blocker-tagged session.
        rows = await list_sessions(conn, severity_tag_ids=[-1, sev["Blocker"]])
        assert {r["id"] for r in rows} == {s_orphan["id"], s_blocker["id"]}

        # Plain real-id list still excludes the orphan.
        rows = await list_sessions(conn, severity_tag_ids=[sev["Blocker"]])
        assert {r["id"] for r in rows} == {s_blocker["id"]}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_sessions_includes_tag_ids(tmp_path: Path) -> None:
    """Medallion-row data: every row returned from list_sessions carries
    a `tag_ids` list so the sidebar can render per-tag icons without an
    N+1 round trip."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        infra = await create_tag(conn, name="infra")
        await attach_tag(conn, sess["id"], infra["id"])
        await ensure_default_severity(conn, sess["id"])
        rows = await list_sessions(conn)
        hit = next(r for r in rows if r["id"] == sess["id"])
        assert "tag_ids" in hit
        assert infra["id"] in hit["tag_ids"]
        default_id = await get_default_severity_tag_id(conn)
        assert default_id in hit["tag_ids"]
    finally:
        await conn.close()


# --- API surface -----------------------------------------------------


def test_api_create_session_attaches_default_severity(client: TestClient) -> None:
    """POST /api/sessions lands with 'Low' attached when the caller
    didn't pass an explicit severity, regardless of which general tags
    they supplied."""
    t = client.post("/api/tags", json={"name": "infra"}).json()
    sess = client.post(
        "/api/sessions",
        json={"working_dir": "/x", "model": "m", "title": "test session", "tag_ids": [t["id"]]},
    ).json()
    tag_rows = client.get(f"/api/sessions/{sess['id']}/tags").json()
    names = [r["name"] for r in tag_rows]
    assert "Low" in names
    assert "infra" in names
    # The session row itself echoes tag_ids.
    assert set(sess["tag_ids"]) >= {t["id"]}


def test_api_create_tag_with_severity_group(client: TestClient) -> None:
    resp = client.post(
        "/api/tags",
        json={"name": "Reviewed", "tag_group": "severity", "color": "#888888"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tag_group"] == "severity"
    assert body["color"] == "#888888"


# --- list_tags scope (v0.7.4 context-aware severity counts) ---------


@pytest.mark.asyncio
async def test_list_tags_unscoped_returns_absolute_counts(tmp_path: Path) -> None:
    """Default / legacy path: `scope_tag_ids=None` gives every tag its
    absolute session count. Preserves behavior for callers that just
    want a tag inventory."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        s = await create_session(conn, working_dir="/x", model="m", title="a")
        infra = await create_tag(conn, name="infra")
        await attach_tag(conn, s["id"], infra["id"])
        await ensure_default_severity(conn, s["id"])
        rows = await list_tags(conn)
        by_name = {r["name"]: r for r in rows}
        assert by_name["infra"]["session_count"] == 1
        assert by_name["Low"]["session_count"] == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_tags_empty_scope_zeros_severity_only(tmp_path: Path) -> None:
    """`scope_tag_ids=[]` means "no general tags selected in the
    sidebar" — severity counts collapse to 0 (the session list is
    empty anyway), but general-tag counts stay absolute so the user
    can still see which tag to pick."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        s = await create_session(conn, working_dir="/x", model="m", title="a")
        infra = await create_tag(conn, name="infra")
        await attach_tag(conn, s["id"], infra["id"])
        await ensure_default_severity(conn, s["id"])
        rows = await list_tags(conn, scope_tag_ids=[])
        by_name = {r["name"]: r for r in rows}
        # General: absolute (untouched).
        assert by_name["infra"]["session_count"] == 1
        assert by_name["infra"]["open_session_count"] == 1
        # Severity: zeroed across the board.
        assert by_name["Low"]["session_count"] == 0
        assert by_name["Low"]["open_session_count"] == 0
        assert by_name["Blocker"]["session_count"] == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_tags_scoped_narrows_severity_counts(tmp_path: Path) -> None:
    """`scope_tag_ids=[infra]` scopes severity counts to sessions that
    carry any of the listed general tags. General counts stay
    absolute so the general list isn't distorted by scope."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        s_infra = await create_session(conn, working_dir="/a", model="m", title="a")
        s_bug = await create_session(conn, working_dir="/b", model="m", title="b")
        infra = await create_tag(conn, name="infra")
        bug = await create_tag(conn, name="bug")
        await attach_tag(conn, s_infra["id"], infra["id"])
        await attach_tag(conn, s_bug["id"], bug["id"])
        # Put Blocker on the infra session, leave the bug session with
        # its default Low severity. Severity counts for scope=[infra]
        # should see Blocker=1, Low=0 — only infra-tagged sessions are
        # in scope.
        async with conn.execute("SELECT id, name FROM tags WHERE tag_group='severity'") as cursor:
            sev = {r["name"]: int(r["id"]) async for r in cursor}
        await attach_tag(conn, s_infra["id"], sev["Blocker"])
        await ensure_default_severity(conn, s_bug["id"])
        rows = await list_tags(conn, scope_tag_ids=[infra["id"]])
        by_name = {r["name"]: r for r in rows}
        # Severity narrowed to the infra session only.
        assert by_name["Blocker"]["session_count"] == 1
        assert by_name["Low"]["session_count"] == 0
        # General counts unchanged — both rows still reflect their
        # absolute membership.
        assert by_name["infra"]["session_count"] == 1
        assert by_name["bug"]["session_count"] == 1
        # Scope with OR of both general tags → severity covers both
        # sessions, so Blocker + Low each = 1.
        rows = await list_tags(conn, scope_tag_ids=[infra["id"], bug["id"]])
        by_name = {r["name"]: r for r in rows}
        assert by_name["Blocker"]["session_count"] == 1
        assert by_name["Low"]["session_count"] == 1
    finally:
        await conn.close()


def test_api_list_tags_scope_tags_query(client: TestClient) -> None:
    """The route exposes the scope via `?scope_tags=`. Empty param
    zeros severity counts; comma-separated ids narrow to the OR of
    matching sessions. Bad input is 400."""
    infra = client.post("/api/tags", json={"name": "infra"}).json()
    client.post(
        "/api/sessions",
        json={"working_dir": "/a", "model": "m", "title": "test session", "tag_ids": [infra["id"]]},
    )
    # Empty scope → severity counts zero.
    rows = client.get("/api/tags?scope_tags=").json()
    by_name = {r["name"]: r for r in rows}
    assert by_name["Low"]["session_count"] == 0
    assert by_name["infra"]["session_count"] == 1
    # Scoped to infra → Low session_count reflects infra-scoped
    # sessions (1).
    rows = client.get(f"/api/tags?scope_tags={infra['id']}").json()
    by_name = {r["name"]: r for r in rows}
    assert by_name["Low"]["session_count"] == 1
    bad = client.get("/api/tags?scope_tags=oops")
    assert bad.status_code == 400


def test_api_list_sessions_severity_tags_query(client: TestClient) -> None:
    """The severity_tags query param is a separate axis — combining
    with tags/mode narrows. Bad input is 400, same as the general-tag
    path."""
    # Grab the two severity ids we care about.
    all_tags = client.get("/api/tags").json()
    sev = {t["name"]: t["id"] for t in all_tags if t["tag_group"] == "severity"}
    t = client.post("/api/tags", json={"name": "infra"}).json()
    s1 = client.post(
        "/api/sessions",
        json={"working_dir": "/a", "model": "m", "title": "test session", "tag_ids": [t["id"], sev["Blocker"]]},
    ).json()
    client.post(
        "/api/sessions",
        json={"working_dir": "/b", "model": "m", "title": "test session", "tag_ids": [t["id"], sev["Low"]]},
    ).json()

    blockers = client.get(f"/api/sessions?severity_tags={sev['Blocker']}").json()
    assert {r["id"] for r in blockers} == {s1["id"]}

    bad = client.get("/api/sessions?severity_tags=oops")
    assert bad.status_code == 400
