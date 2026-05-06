"""Negative-path coverage for /api/sessions.

Negative-path discipline (coding-standards §"Testing"): every
boundary that can reject input gets at least one test that proves
it does. Validation errors, 404s, and unknown-field rejections all
funnel through the canonical error envelope.
"""

from typing import Any

from httpx import AsyncClient


async def test_create_rejects_missing_required_field(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Missing ``kind`` → 422, no row written."""
    response = await client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "sonnet", "title": "x"},  # noqa: S108
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable_entity"


async def test_create_rejects_bad_kind_enum(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Unknown ``kind`` value → 422 with the field error in the envelope."""
    response = await client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",  # noqa: S108
            "model": "sonnet",
            "title": "x",
            "kind": "wizard",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert any("kind" in error.get("loc", []) for error in body["error"]["errors"])


async def test_create_rejects_relative_working_dir(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Relative ``working_dir`` → 422 from the field validator."""
    response = await client.post(
        "/api/sessions",
        json={
            "working_dir": "./relative",
            "model": "sonnet",
            "title": "x",
            "kind": "chat",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_create_rejects_unknown_field(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """``extra='forbid'`` rejects unknown fields with 422."""
    body: dict[str, Any] = {
        "working_dir": "/tmp",  # noqa: S108
        "model": "sonnet",
        "title": "x",
        "kind": "chat",
        "rogue_field": "smuggled",
    }
    response = await client.post("/api/sessions", json=body, headers=auth_headers)
    assert response.status_code == 422


async def test_create_rejects_negative_max_budget(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """``max_budget`` must be > 0; -5 → 422."""
    response = await client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",  # noqa: S108
            "model": "sonnet",
            "title": "x",
            "kind": "chat",
            "max_budget": -5,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_get_unknown_id_yields_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET on a nonexistent UUID → 404 + canonical envelope."""
    response = await client.get(
        "/api/sessions/00000000000000000000000000000000",
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_patch_unknown_id_yields_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """PATCH on a nonexistent UUID → 404."""
    response = await client.patch(
        "/api/sessions/00000000000000000000000000000000",
        json={"title": "new"},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_delete_unknown_id_yields_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """DELETE on a nonexistent UUID → 404."""
    response = await client.delete(
        "/api/sessions/00000000000000000000000000000000",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_patch_rejects_relative_working_dir(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """``SessionUpdate`` enforces the same absolute-path rule as create."""
    create = await client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",  # noqa: S108
            "model": "sonnet",
            "title": "x",
            "kind": "chat",
        },
        headers=auth_headers,
    )
    session_id = create.json()["id"]

    response = await client.patch(
        f"/api/sessions/{session_id}",
        json={"working_dir": "./relative"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_session_update_validator_accepts_none() -> None:
    """The SessionUpdate validator's ``value is None`` short-circuit.

    Tested at the model layer (not through the HTTP path) because the
    DB enforces NOT NULL on ``working_dir`` — sending null over the
    wire would IntegrityError on commit. The validator itself returns
    None cleanly so absent-field semantics work.
    """
    from bearings.models.sessions import SessionUpdate

    update = SessionUpdate(working_dir=None)
    assert update.working_dir is None


async def test_patch_rejects_unknown_field(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """``SessionUpdate`` ``extra='forbid'`` rejects unknown fields too."""
    create = await client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",  # noqa: S108
            "model": "sonnet",
            "title": "x",
            "kind": "chat",
        },
        headers=auth_headers,
    )
    session_id = create.json()["id"]

    response = await client.patch(
        f"/api/sessions/{session_id}",
        json={"who_knows": "?"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_list_rejects_excessive_limit(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """``limit`` > LIST_LIMIT_MAX (200) → 422 from the query validator."""
    response = await client.get("/api/sessions?limit=999", headers=auth_headers)
    assert response.status_code == 422


async def test_list_rejects_negative_offset(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """``offset`` < 0 → 422."""
    response = await client.get("/api/sessions?offset=-1", headers=auth_headers)
    assert response.status_code == 422
