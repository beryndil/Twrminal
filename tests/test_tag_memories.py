from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twrminal.db.store import (
    create_tag,
    delete_tag,
    delete_tag_memory,
    get_tag_memory,
    init_db,
    put_tag_memory,
)

# --- store -----------------------------------------------------------


@pytest.mark.asyncio
async def test_put_tag_memory_creates_row(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        tag = await create_tag(conn, name="infra")
        row = await put_tag_memory(conn, tag["id"], "Prefer nftables over iptables.")
        assert row is not None
        assert row["tag_id"] == tag["id"]
        assert row["content"] == "Prefer nftables over iptables."
        assert row["updated_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_put_tag_memory_overwrites_existing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        tag = await create_tag(conn, name="infra")
        first = await put_tag_memory(conn, tag["id"], "Rule A.")
        second = await put_tag_memory(conn, tag["id"], "Rule B.")
        assert first is not None and second is not None
        assert second["content"] == "Rule B."
        # Single row per tag (PK on tag_id).
        stored = await get_tag_memory(conn, tag["id"])
        assert stored is not None
        assert stored["content"] == "Rule B."
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_put_tag_memory_missing_tag_returns_none(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await put_tag_memory(conn, 999, "ghost") is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_tag_memory_missing_returns_none(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        tag = await create_tag(conn, name="infra")
        assert await get_tag_memory(conn, tag["id"]) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_tag_memory_returns_false_for_missing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await delete_tag_memory(conn, 999) is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_tag_cascades_tag_memories(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        tag = await create_tag(conn, name="infra")
        await put_tag_memory(conn, tag["id"], "Remember this.")
        assert await delete_tag(conn, tag["id"]) is True
        assert await get_tag_memory(conn, tag["id"]) is None
    finally:
        await conn.close()


# --- API -------------------------------------------------------------


def _default_tag_id(client: TestClient) -> int:
    """Every session must carry ≥1 tag (v0.2.13). Auto-seed one for
    tests that don't care about a specific tag."""
    existing = client.get("/api/tags").json()
    if existing:
        return int(existing[0]["id"])
    return int(client.post("/api/tags", json={"name": "default"}).json()["id"])


def test_get_tag_memory_missing_is_404(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    resp = client.get(f"/api/tags/{tag['id']}/memory")
    assert resp.status_code == 404


def test_put_tag_memory_creates_and_returns_row(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    resp = client.put(
        f"/api/tags/{tag['id']}/memory",
        json={"content": "Prefer nftables over iptables."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tag_id"] == tag["id"]
    assert body["content"] == "Prefer nftables over iptables."
    assert body["updated_at"]


def test_put_tag_memory_missing_tag_is_404(client: TestClient) -> None:
    resp = client.put("/api/tags/999/memory", json={"content": "x"})
    assert resp.status_code == 404


def test_put_then_get_round_trip(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    client.put(f"/api/tags/{tag['id']}/memory", json={"content": "Remember."})
    resp = client.get(f"/api/tags/{tag['id']}/memory")
    assert resp.status_code == 200
    assert resp.json()["content"] == "Remember."


def test_put_tag_memory_overwrites(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    client.put(f"/api/tags/{tag['id']}/memory", json={"content": "v1"})
    resp = client.put(f"/api/tags/{tag['id']}/memory", json={"content": "v2"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "v2"


def test_delete_tag_memory_is_204(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    client.put(f"/api/tags/{tag['id']}/memory", json={"content": "v"})
    resp = client.delete(f"/api/tags/{tag['id']}/memory")
    assert resp.status_code == 204
    assert client.get(f"/api/tags/{tag['id']}/memory").status_code == 404


def test_delete_tag_memory_missing_is_404(client: TestClient) -> None:
    resp = client.delete("/api/tags/999/memory")
    assert resp.status_code == 404


def test_patch_session_accepts_session_instructions(client: TestClient) -> None:
    sess = client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "claude-sonnet-4-6",
            "tag_ids": [_default_tag_id(client)],
        },
    ).json()
    assert sess["session_instructions"] is None
    resp = client.patch(
        f"/api/sessions/{sess['id']}",
        json={"session_instructions": "Focus on auth this session."},
    )
    assert resp.status_code == 200
    assert resp.json()["session_instructions"] == "Focus on auth this session."
    # Clearing via explicit null.
    resp = client.patch(
        f"/api/sessions/{sess['id']}",
        json={"session_instructions": None},
    )
    assert resp.status_code == 200
    assert resp.json()["session_instructions"] is None


# --- System prompt route (v0.2.8) ------------------------------------


def test_system_prompt_missing_session_is_404(client: TestClient) -> None:
    resp = client.get(f"/api/sessions/{'0' * 32}/system_prompt")
    assert resp.status_code == 404


def test_system_prompt_base_only(client: TestClient) -> None:
    # Session has a tag, but the tag has no memory row → no tag_memory
    # layer. Base is the only layer emitted.
    sess = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "tag_ids": [_default_tag_id(client)]},
    ).json()
    resp = client.get(f"/api/sessions/{sess['id']}/system_prompt")
    assert resp.status_code == 200
    body = resp.json()
    kinds = [layer["kind"] for layer in body["layers"]]
    assert kinds == ["base"]
    assert body["total_tokens"] == sum(layer["token_count"] for layer in body["layers"])
    assert body["layers"][0]["token_count"] >= 1


def test_system_prompt_full_stack(client: TestClient) -> None:
    tag = client.post("/api/tags", json={"name": "infra"}).json()
    sess = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "tag_ids": [tag["id"]]},
    ).json()
    client.put(f"/api/tags/{tag['id']}/memory", json={"content": "Prefer nftables."})
    client.patch(
        f"/api/sessions/{sess['id']}",
        json={"session_instructions": "Be concise."},
    )
    body = client.get(f"/api/sessions/{sess['id']}/system_prompt").json()
    kinds = [layer["kind"] for layer in body["layers"]]
    assert kinds == ["base", "tag_memory", "session"]
    contents = [layer["content"] for layer in body["layers"]]
    assert "Prefer nftables." in contents
    assert "Be concise." in contents
    # total_tokens is exactly the sum of per-layer counts.
    assert body["total_tokens"] == sum(layer["token_count"] for layer in body["layers"])
    # Every layer contributes at least one token when it has content.
    for layer in body["layers"]:
        if layer["content"]:
            assert layer["token_count"] >= 1
