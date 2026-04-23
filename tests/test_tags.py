from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bearings.db.store import (
    attach_tag,
    close_session,
    create_session,
    create_tag,
    delete_session,
    delete_tag,
    detach_tag,
    get_session,
    get_tag,
    init_db,
    list_session_tags,
    list_sessions,
    list_tags,
    reopen_session,
    update_tag,
)

# --- store -----------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_creates_tag_tables(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = [row[0] async for row in cursor]
        assert "tags" in tables
        assert "session_tags" in tables
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_session_tags_tag'"
        ) as cursor:
            assert await cursor.fetchone() is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_tag_returns_row_with_defaults(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_tag(conn, name="infra")
        assert row["id"] >= 1
        assert row["name"] == "infra"
        assert row["color"] is None
        assert row["pinned"] == 0
        assert row["sort_order"] == 0
        assert row["created_at"]
        assert row["session_count"] == 0
        assert row["open_session_count"] == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_tag_rejects_duplicate_name(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        await create_tag(conn, name="infra")
        with pytest.raises(Exception) as excinfo:
            await create_tag(conn, name="infra")
        assert "UNIQUE" in str(excinfo.value)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_tags_orders_pinned_then_sort_then_id(tmp_path: Path) -> None:
    """Pinned first, then ascending sort_order, then ascending id.
    Migration 0021 seeds five severity tags; filter them out here so the
    assertion stays focused on the order of the tags the test created."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        a = await create_tag(conn, name="a", sort_order=10)
        b = await create_tag(conn, name="b", sort_order=5)
        c = await create_tag(conn, name="c", pinned=True, sort_order=100)
        d = await create_tag(conn, name="d", pinned=True, sort_order=1)
        rows = await list_tags(conn)
        general = [r for r in rows if r["tag_group"] == "general"]
        assert [r["id"] for r in general] == [d["id"], c["id"], b["id"], a["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_tag_applies_partial_fields(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_tag(conn, name="infra")
        updated = await update_tag(
            conn, row["id"], fields={"name": "infrastructure", "pinned": True}
        )
        assert updated is not None
        assert updated["name"] == "infrastructure"
        assert updated["pinned"] == 1
        # color/sort_order left alone
        assert updated["color"] is None
        assert updated["sort_order"] == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_tag_returns_none_for_missing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await update_tag(conn, 999, fields={"name": "x"}) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_tag_returns_false_for_missing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await delete_tag(conn, 999) is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_attach_tag_is_idempotent(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="infra")
        assert await attach_tag(conn, sess["id"], tag["id"]) is True
        # Second attach is a no-op but still reports success.
        assert await attach_tag(conn, sess["id"], tag["id"]) is True
        rows = await list_session_tags(conn, sess["id"])
        assert [r["id"] for r in rows] == [tag["id"]]
        # session_count is 1, not 2. The session is open, so the
        # open-only partition matches.
        tags = await list_tags(conn)
        assert tags[0]["session_count"] == 1
        assert tags[0]["open_session_count"] == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_attach_tag_rejects_unknown_session_or_tag(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="infra")
        assert await attach_tag(conn, "missing-session", tag["id"]) is False
        assert await attach_tag(conn, sess["id"], 999) is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_attach_tag_touches_session_updated_at(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="infra")
        await asyncio.sleep(0.002)
        await attach_tag(conn, sess["id"], tag["id"])
        refreshed = await get_session(conn, sess["id"])
        assert refreshed is not None
        assert refreshed["updated_at"] > sess["updated_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_detach_tag_removes_pair(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="infra")
        await attach_tag(conn, sess["id"], tag["id"])
        assert await detach_tag(conn, sess["id"], tag["id"]) is True
        assert await list_session_tags(conn, sess["id"]) == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_tag_cascades_session_tags(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="infra")
        await attach_tag(conn, sess["id"], tag["id"])
        assert await delete_tag(conn, tag["id"]) is True
        assert await list_session_tags(conn, sess["id"]) == []
        # The session itself survives.
        assert await get_session(conn, sess["id"]) is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_sessions_filter_or(tmp_path: Path) -> None:
    """v0.7.4: general-tag filter is OR — a session matches if it
    carries any listed tag. The pre-v0.7.4 AND path was dropped with
    the Any/All toggle."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        s1 = await create_session(conn, working_dir="/a", model="m", title="a")
        s2 = await create_session(conn, working_dir="/b", model="m", title="b")
        await create_session(conn, working_dir="/c", model="m", title="c")
        t_infra = await create_tag(conn, name="infra")
        t_bug = await create_tag(conn, name="bug")
        await attach_tag(conn, s1["id"], t_infra["id"])
        await attach_tag(conn, s2["id"], t_bug["id"])
        rows = await list_sessions(conn, tag_ids=[t_infra["id"], t_bug["id"]])
        assert {r["id"] for r in rows} == {s1["id"], s2["id"]}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_sessions_empty_tag_filter_matches_nothing(tmp_path: Path) -> None:
    """v0.7.4: explicit empty tag list means "match nothing" — the
    sidebar sends this when no general tags are selected. Distinct
    from `tag_ids=None` which still means "no filter, every session"
    for legacy callers like the history export."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        s1 = await create_session(conn, working_dir="/a", model="m", title="a")
        s2 = await create_session(conn, working_dir="/b", model="m", title="b")
        # Empty list → zero results.
        rows = await list_sessions(conn, tag_ids=[])
        assert rows == []
        # None → every session (legacy unfiltered path).
        rows = await list_sessions(conn, tag_ids=None)
        assert {r["id"] for r in rows} == {s1["id"], s2["id"]}
    finally:
        await conn.close()


def test_api_list_sessions_filters_by_tag(client: TestClient) -> None:
    # Seed: two sessions, each with one distinct tag. v0.2.13 makes
    # tag_ids mandatory on POST /api/sessions so we attach at create.
    t1 = client.post("/api/tags", json={"name": "infra"}).json()
    t2 = client.post("/api/tags", json={"name": "bug"}).json()
    s1 = client.post(
        "/api/sessions",
        json={"working_dir": "/a", "model": "claude-sonnet-4-6", "tag_ids": [t1["id"]]},
    ).json()
    s2 = client.post(
        "/api/sessions",
        json={"working_dir": "/b", "model": "claude-sonnet-4-6", "tag_ids": [t2["id"]]},
    ).json()

    # v0.7.4: general-tag filter is OR. Two ids → both sessions.
    or_hits = client.get(f"/api/sessions?tags={t1['id']},{t2['id']}").json()
    assert {r["id"] for r in or_hits} == {s1["id"], s2["id"]}

    only_infra = client.get(f"/api/sessions?tags={t1['id']}").json()
    assert {r["id"] for r in only_infra} == {s1["id"]}


def test_api_list_sessions_empty_tag_param_matches_nothing(client: TestClient) -> None:
    """v0.7.4: `?tags=` (present but empty) means "match nothing".
    Omitting the param still returns every session (legacy path)."""
    t = client.post("/api/tags", json={"name": "infra"}).json()
    client.post(
        "/api/sessions",
        json={"working_dir": "/a", "model": "m", "tag_ids": [t["id"]]},
    )
    assert client.get("/api/sessions?tags=").json() == []
    assert len(client.get("/api/sessions").json()) == 1


def test_api_list_sessions_bad_tags_is_400(client: TestClient) -> None:
    resp = client.get("/api/sessions?tags=oops")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_open_session_count_tracks_close_and_reopen(tmp_path: Path) -> None:
    """The green open count next to each tag row is a live partition of
    `session_count` by `closed_at IS NULL`. Closing a tagged session
    should decrement the open count but leave the total alone;
    reopening should restore it. Two sessions share the tag so the
    totals are non-trivial on both sides."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        tag = await create_tag(conn, name="infra")
        s1 = await create_session(conn, working_dir="/x", model="m", title=None)
        s2 = await create_session(conn, working_dir="/y", model="m", title=None)
        await attach_tag(conn, s1["id"], tag["id"])
        await attach_tag(conn, s2["id"], tag["id"])

        row = await get_tag(conn, tag["id"])
        assert row is not None
        assert row["session_count"] == 2
        assert row["open_session_count"] == 2

        await close_session(conn, s1["id"])
        row = await get_tag(conn, tag["id"])
        assert row is not None
        assert row["session_count"] == 2
        assert row["open_session_count"] == 1

        await reopen_session(conn, s1["id"])
        row = await get_tag(conn, tag["id"])
        assert row is not None
        assert row["session_count"] == 2
        assert row["open_session_count"] == 2
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_session_cascades_session_tags(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="infra")
        await attach_tag(conn, sess["id"], tag["id"])
        await delete_session(conn, sess["id"])
        # Tag survives; the pair is gone — check via session_count on the tag.
        refreshed = await get_tag(conn, tag["id"])
        assert refreshed is not None
        assert refreshed["session_count"] == 0
        assert refreshed["open_session_count"] == 0
    finally:
        await conn.close()


# --- API -------------------------------------------------------------


def _create_session(client: TestClient, **kwargs: object) -> dict:
    # v0.2.13: seed a default tag so the gate is satisfied. Tests that
    # care about a specific tag pass `tag_ids=` explicitly.
    if "tag_ids" not in kwargs:
        existing = client.get("/api/tags").json()
        if existing:
            default_id = existing[0]["id"]
        else:
            default_id = client.post("/api/tags", json={"name": "default"}).json()["id"]
        kwargs["tag_ids"] = [default_id]
    body = {"working_dir": "/tmp", "model": "claude-sonnet-4-6", "title": None, **kwargs}
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    data: dict[str, object] = resp.json()
    return data


def test_get_tags_returns_only_seeded_severities_on_fresh_db(client: TestClient) -> None:
    """Migration 0021 seeds five severity tags, so a fresh DB is no
    longer empty. The general group, though, should be."""
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    body = resp.json()
    general = [t for t in body if t["tag_group"] == "general"]
    severity = [t for t in body if t["tag_group"] == "severity"]
    assert general == []
    assert [t["name"] for t in severity] == [
        "Blocker",
        "Critical",
        "Medium",
        "Low",
        "Quality of Life",
    ]


def test_post_tag_returns_201_and_row(client: TestClient) -> None:
    resp = client.post("/api/tags", json={"name": "infra", "pinned": True})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "infra"
    assert body["pinned"] is True
    assert body["sort_order"] == 0
    assert body["session_count"] == 0
    assert body["open_session_count"] == 0
    assert body["id"] >= 1


def test_post_tag_duplicate_name_is_409(client: TestClient) -> None:
    client.post("/api/tags", json={"name": "infra"})
    resp = client.post("/api/tags", json={"name": "infra"})
    assert resp.status_code == 409


def test_get_tag_round_trip(client: TestClient) -> None:
    created = client.post("/api/tags", json={"name": "infra"}).json()
    resp = client.get(f"/api/tags/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == created


def test_get_tag_missing_is_404(client: TestClient) -> None:
    resp = client.get("/api/tags/999")
    assert resp.status_code == 404


def test_patch_tag_updates_fields(client: TestClient) -> None:
    created = client.post("/api/tags", json={"name": "infra"}).json()
    resp = client.patch(f"/api/tags/{created['id']}", json={"pinned": True, "sort_order": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["pinned"] is True
    assert body["sort_order"] == 5
    assert body["name"] == "infra"


def test_patch_tag_duplicate_name_is_409(client: TestClient) -> None:
    a = client.post("/api/tags", json={"name": "a"}).json()
    client.post("/api/tags", json={"name": "b"})
    resp = client.patch(f"/api/tags/{a['id']}", json={"name": "b"})
    assert resp.status_code == 409


def test_patch_tag_missing_is_404(client: TestClient) -> None:
    resp = client.patch("/api/tags/999", json={"name": "x"})
    assert resp.status_code == 404


def test_delete_tag_is_204(client: TestClient) -> None:
    created = client.post("/api/tags", json={"name": "infra"}).json()
    resp = client.delete(f"/api/tags/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/tags/{created['id']}").status_code == 404


def test_delete_tag_missing_is_404(client: TestClient) -> None:
    resp = client.delete("/api/tags/999")
    assert resp.status_code == 404


def test_attach_session_tag_returns_tag_list(client: TestClient) -> None:
    # Attach the tag at create time (v0.2.13 enforcement). A second
    # POST to the attach endpoint is a no-op via INSERT OR IGNORE.
    # Migration 0021 also auto-attaches the default severity ('Low'),
    # so the returned list is {infra, Low} — filter to general-only for
    # the ordering assertion.
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    sess = _create_session(client, tag_ids=[tag["id"]])
    resp = client.post(f"/api/sessions/{sess['id']}/tags/{tag['id']}")
    assert resp.status_code == 200
    body = resp.json()
    general = [t for t in body if t["tag_group"] == "general"]
    assert [t["id"] for t in general] == [tag["id"]]
    # session_count rolls up to /api/tags; the just-created `infra` is
    # the only general tag so find it directly rather than indexing.
    tags = client.get("/api/tags").json()
    infra = next(t for t in tags if t["name"] == "infra")
    assert infra["session_count"] == 1
    assert infra["open_session_count"] == 1


def test_attach_is_idempotent_via_api(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    sess = _create_session(client, tag_ids=[tag["id"]])
    # Attach again — idempotent (already attached at create time).
    # Response carries Low (severity default) alongside infra.
    resp = client.post(f"/api/sessions/{sess['id']}/tags/{tag['id']}")
    assert resp.status_code == 200
    general = [t for t in resp.json() if t["tag_group"] == "general"]
    assert len(general) == 1


def test_attach_missing_session_is_404(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    resp = client.post(f"/api/sessions/{'0' * 32}/tags/{tag['id']}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "session not found"


def test_attach_missing_tag_is_404(client: TestClient) -> None:
    sess = _create_session(client)
    resp = client.post(f"/api/sessions/{sess['id']}/tags/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "tag not found"


def test_detach_session_tag_returns_remaining(client: TestClient) -> None:
    t1 = client.post("/api/tags", json={"name": "infra"}).json()
    t2 = client.post("/api/tags", json={"name": "bug-repro"}).json()
    sess = _create_session(client, tag_ids=[t1["id"], t2["id"]])
    resp = client.delete(f"/api/sessions/{sess['id']}/tags/{t1['id']}")
    assert resp.status_code == 200
    # Low (severity default) also attached; scope to general for the
    # meaningful assertion.
    general = [t for t in resp.json() if t["tag_group"] == "general"]
    assert [t["id"] for t in general] == [t2["id"]]


def test_detach_missing_session_is_404(client: TestClient) -> None:
    resp = client.delete(f"/api/sessions/{'0' * 32}/tags/1")
    assert resp.status_code == 404


def test_list_session_tags_returns_attached(client: TestClient) -> None:
    t1 = client.post("/api/tags", json={"name": "a", "sort_order": 2}).json()
    t2 = client.post("/api/tags", json={"name": "b", "pinned": True}).json()
    sess = _create_session(client, tag_ids=[t1["id"], t2["id"]])
    resp = client.get(f"/api/sessions/{sess['id']}/tags")
    assert resp.status_code == 200
    # Pinned first; severity default Low also attached but sits in its
    # own group so scope to general for the ordering check.
    general = [t for t in resp.json() if t["tag_group"] == "general"]
    assert [t["id"] for t in general] == [t2["id"], t1["id"]]


def test_list_session_tags_missing_session_is_404(client: TestClient) -> None:
    resp = client.get(f"/api/sessions/{'0' * 32}/tags")
    assert resp.status_code == 404


# --- Tag defaults (v0.2.10) ------------------------------------------


@pytest.mark.asyncio
async def test_create_tag_accepts_defaults(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_tag(
            conn,
            name="bearings",
            default_working_dir="/srv/example-project",
            default_model="claude-opus-4-7",
        )
        assert row["default_working_dir"] == "/srv/example-project"
        assert row["default_model"] == "claude-opus-4-7"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_tag_defaults_default_to_null(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_tag(conn, name="plain")
        assert row["default_working_dir"] is None
        assert row["default_model"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_update_tag_sets_and_clears_defaults(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_tag(conn, name="bearings")
        updated = await update_tag(
            conn,
            row["id"],
            fields={
                "default_working_dir": "/x",
                "default_model": "claude-opus-4-7",
            },
        )
        assert updated is not None
        assert updated["default_working_dir"] == "/x"
        assert updated["default_model"] == "claude-opus-4-7"
        # Explicit null clears.
        cleared = await update_tag(
            conn,
            row["id"],
            fields={"default_working_dir": None, "default_model": None},
        )
        assert cleared is not None
        assert cleared["default_working_dir"] is None
        assert cleared["default_model"] is None
    finally:
        await conn.close()


def test_post_tag_accepts_defaults(client: TestClient) -> None:
    resp = client.post(
        "/api/tags",
        json={
            "name": "bearings",
            "default_working_dir": "/srv/example-project",
            "default_model": "claude-opus-4-7",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["default_working_dir"] == "/srv/example-project"
    assert body["default_model"] == "claude-opus-4-7"


def test_patch_tag_sets_defaults(client: TestClient) -> None:
    created = client.post("/api/tags", json={"name": "bearings"}).json()
    resp = client.patch(
        f"/api/tags/{created['id']}",
        json={"default_working_dir": "/x", "default_model": "m"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_working_dir"] == "/x"
    assert body["default_model"] == "m"
