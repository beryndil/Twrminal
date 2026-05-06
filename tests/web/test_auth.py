"""Negative-path coverage for the shared-token auth dependency."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bearings.config import Settings
from bearings.errors import ConfigurationError
from bearings.web import create_app


async def test_missing_token_yields_401(client: AsyncClient) -> None:
    """No header → 401 with the canonical error envelope."""
    response = await client.get("/api/sessions")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"


async def test_empty_token_yields_401(client: AsyncClient) -> None:
    """Header present but empty string → 401."""
    response = await client.get("/api/sessions", headers={"X-Bearings-Token": ""})
    assert response.status_code == 401


async def test_wrong_token_yields_401(client: AsyncClient) -> None:
    """Mismatched token → 401."""
    response = await client.get(
        "/api/sessions",
        headers={"X-Bearings-Token": "this-is-not-the-right-token"},
    )
    assert response.status_code == 401


async def test_correct_token_passes(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Correct token → 200 + paginated empty list."""
    response = await client.get("/api/sessions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_create_app_rejects_empty_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty token + auth_disabled=False → ConfigurationError at boot.

    Op directive: never boot an unauthenticated server "by accident."
    """
    monkeypatch.setenv("BEARINGS_AUTH_TOKEN", "")
    monkeypatch.setenv("BEARINGS_AUTH_DISABLED", "false")
    settings = Settings()
    with pytest.raises(ConfigurationError):
        create_app(settings)


async def test_auth_disabled_skips_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """``auth_disabled=True`` lets every request through without a token.

    Tests use this dev-only escape; the warning at boot is logged but
    we don't assert the log line here — that's covered by the structlog
    integration's own tests.
    """
    monkeypatch.setenv("BEARINGS_AUTH_TOKEN", "")
    monkeypatch.setenv("BEARINGS_AUTH_DISABLED", "true")
    settings = Settings()
    from bearings.db import init_db

    await init_db(settings.db_path)
    app: FastAPI = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/sessions")
    assert response.status_code == 200


async def test_sentinel_require_auth_raises_when_unbound() -> None:
    """Calling the placeholder dependency directly is a developer error.

    Reaching :func:`bearings.web.auth.require_auth` without the app
    factory's override means the app was wired wrong; raise loudly.
    """
    from bearings.web.auth import require_auth

    with pytest.raises(RuntimeError):
        await require_auth()


async def test_sentinel_get_db_raises_when_unbound() -> None:
    """The DB sentinel raises for the same reason as require_auth."""
    from bearings.web.db import get_db

    with pytest.raises(RuntimeError):
        # ``get_db`` is an async generator; ``anext`` triggers the body.
        await anext(get_db())
