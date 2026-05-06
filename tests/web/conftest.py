"""Fixtures for the HTTP layer.

Concept: ``httpx.AsyncClient(transport=ASGITransport(app=app))`` runs
requests through the FastAPI app in-process. No socket, no uvicorn,
no thread-pool — the request body is shipped straight to the ASGI
app and the response comes back in the same coroutine. Fast and
deterministic; the right shape for unit-style HTTP tests.

The ``client`` fixture initialises a per-test SQLite DB (so sessions
created in one test don't leak into the next), builds the app with
the test ``Settings``, and yields an :class:`httpx.AsyncClient`
already pointed at the app.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bearings.config import Settings
from bearings.db import init_db
from bearings.web import create_app
from tests.conftest import TEST_AUTH_TOKEN

__all__ = ["TEST_AUTH_TOKEN"]


@pytest.fixture
async def app() -> AsyncIterator[FastAPI]:
    """Build a fresh FastAPI app against a per-test SQLite DB."""
    settings = Settings()
    await init_db(settings.db_path)
    yield create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Yield an :class:`AsyncClient` wired to the in-memory ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Headers carrying the test auth token in the configured header name."""
    return {"X-Bearings-Token": TEST_AUTH_TOKEN}
