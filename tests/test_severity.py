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
        json={"working_dir": "/x", "model": "m", "tag_ids": [t["id"]]},
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
        json={"working_dir": "/a", "model": "m", "tag_ids": [t["id"], sev["Blocker"]]},
    ).json()
    client.post(
        "/api/sessions",
        json={"working_dir": "/b", "model": "m", "tag_ids": [t["id"], sev["Low"]]},
    ).json()

    blockers = client.get(f"/api/sessions?severity_tags={sev['Blocker']}").json()
    assert {r["id"] for r in blockers} == {s1["id"]}

    bad = client.get("/api/sessions?severity_tags=oops")
    assert bad.status_code == 400
