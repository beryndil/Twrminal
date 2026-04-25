from __future__ import annotations

from fastapi.testclient import TestClient


def _create(client: TestClient, title: str = "t") -> str:
    # v0.2.13: tag_ids required. Seed one default tag per client.
    existing = client.get("/api/tags").json()
    if existing:
        tag_id = existing[0]["id"]
    else:
        tag_id = client.post("/api/tags", json={"name": "default"}).json()["id"]
    resp = client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "m",
            "title": title,
            "tag_ids": [tag_id],
        },
    )
    assert resp.status_code == 200
    session_id: str = resp.json()["id"]
    return session_id


def test_export_returns_all_sections(client: TestClient) -> None:
    sid = _create(client, "exported")
    resp = client.get("/api/history/export")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"sessions", "messages", "tool_calls"}
    assert any(s["id"] == sid for s in data["sessions"])
    assert data["messages"] == []
    assert data["tool_calls"] == []


def test_export_includes_messages(client: TestClient, mock_agent_stream: None) -> None:
    sid = _create(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "hi"})
        for _ in range(4):
            ws.receive_text()

    data = client.get("/api/history/export").json()
    roles = [m["role"] for m in data["messages"] if m["session_id"] == sid]
    assert roles == ["user", "assistant"]


def test_daily_filters_by_date(client: TestClient) -> None:
    sid = _create(client, "today")

    # Find the day we actually created on (test-server clock).
    today = client.get(f"/api/sessions/{sid}").json()["created_at"][:10]

    resp = client.get(f"/api/history/daily/{today}")
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["id"] == sid for s in data["sessions"])

    # A day long past — should return empty sections.
    empty = client.get("/api/history/daily/2000-01-01").json()
    assert empty["sessions"] == []
    assert empty["messages"] == []
    assert empty["tool_calls"] == []


def test_daily_rejects_bad_date(client: TestClient) -> None:
    resp = client.get("/api/history/daily/not-a-date")
    assert resp.status_code == 400
    resp = client.get("/api/history/daily/2026-13-40")
    assert resp.status_code == 400


def test_export_accepts_from_to_range(client: TestClient) -> None:
    sid = _create(client, "ranged")
    today = client.get(f"/api/sessions/{sid}").json()["created_at"][:10]

    # Both bounds include the session.
    inside = client.get(f"/api/history/export?from={today}&to={today}").json()
    assert any(s["id"] == sid for s in inside["sessions"])

    # from = tomorrow would exclude it — use a date guaranteed to be past.
    after = client.get("/api/history/export?from=2099-01-01").json()
    assert after["sessions"] == []

    # to = yesterday excludes.
    before = client.get("/api/history/export?to=2000-01-01").json()
    assert before["sessions"] == []


def test_export_rejects_bad_range(client: TestClient) -> None:
    resp = client.get("/api/history/export?from=bogus")
    assert resp.status_code == 400
    resp = client.get("/api/history/export?to=2026-99-99")
    assert resp.status_code == 400


def test_search_requires_q_param(client: TestClient) -> None:
    resp = client.get("/api/history/search")
    assert resp.status_code == 422  # q missing
    resp = client.get("/api/history/search?q=")
    assert resp.status_code == 422  # empty string


def test_search_returns_matches(client: TestClient, mock_agent_stream: None) -> None:
    sid = _create(client, "searchable")
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "pagination is tricky"})
        for _ in range(4):
            ws.receive_text()

    hits = client.get("/api/history/search?q=pagination").json()
    assert len(hits) >= 1
    user_hit = next(h for h in hits if h["role"] == "user")
    assert user_hit["session_id"] == sid
    assert user_hit["session_title"] == "searchable"
    assert "pagination" in user_hit["snippet"]
    assert user_hit["model"]  # joined from sessions


def test_search_empty_when_no_match(client: TestClient) -> None:
    _create(client)
    hits = client.get("/api/history/search?q=absolutely-not-there").json()
    assert hits == []


def test_search_escapes_like_wildcards(client: TestClient, mock_agent_stream: None) -> None:
    """A literal `%` in the query must NOT match every row. Without the
    LIKE-ESCAPE wrap the unescaped `%` would expand the pattern to
    `%%%` and return every message in the DB regardless of content
    (security audit 2026-04-21 §1)."""
    sid = _create(client, "wildcard-search")
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "ordinary text without metachars"})
        for _ in range(4):
            ws.receive_text()

    pct = client.get("/api/history/search?q=%25").json()
    assert pct == [], "literal % must not match plain text"
    underscore = client.get("/api/history/search?q=_").json()
    assert underscore == [], "literal _ must not match a single character"
    backslash = client.get("/api/history/search?q=%5C").json()
    assert backslash == [], "literal backslash must not match escape sequences"
    # Sanity check that a real substring still matches with the escape
    # in place — escaping must not break the happy path.
    real = client.get("/api/history/search?q=ordinary").json()
    assert any("ordinary" in h["snippet"] for h in real)
