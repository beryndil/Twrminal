"""Tests for the unauthenticated /api/health probe."""

from httpx import AsyncClient

from bearings import __version__


async def test_health_returns_ok_and_version(client: AsyncClient) -> None:
    """200 + JSON body with ``status=ok`` and the package version."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "version": __version__}


async def test_health_does_not_require_auth(client: AsyncClient) -> None:
    """No ``X-Bearings-Token`` header → still 200.

    The health route is intentionally outside the auth gate so probes
    and humans can verify liveness without minting a token.
    """
    response = await client.get("/api/health")
    assert response.status_code == 200


async def test_health_emits_request_id_header(client: AsyncClient) -> None:
    """Every response carries an ``X-Request-ID`` for log-correlation."""
    response = await client.get("/api/health")
    assert "X-Request-ID" in response.headers
    # uuid4().hex is 32 lowercase hex chars; guard against accidental dashes.
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert all(ch in "0123456789abcdef" for ch in request_id)
