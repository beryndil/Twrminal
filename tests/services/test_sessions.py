"""Service-layer unit tests for sessions, decoupled from HTTP."""

from collections.abc import AsyncIterator

import pytest

from bearings.config import Settings
from bearings.db import connect, init_db
from bearings.models.sessions import SessionCreate, SessionUpdate
from bearings.services import sessions as sessions_service


@pytest.fixture
async def db() -> AsyncIterator[object]:
    """Yield a per-test aiosqlite connection against a fresh DB."""
    settings = Settings()
    await init_db(settings.db_path)
    async with connect(settings.db_path) as connection:
        yield connection


async def test_create_assigns_uuid_and_timestamps(db: object) -> None:
    """``create_session`` mints an id and stamps both timestamps."""
    payload = SessionCreate(
        working_dir="/tmp/x",  # noqa: S108
        model="sonnet",
        title="t",
        kind="chat",
    )
    row = await sessions_service.create_session(db, payload)  # type: ignore[arg-type]
    assert len(row["id"]) == 32
    assert row["created_at"] == row["updated_at"]
    assert row["description"] == ""
    assert row["max_budget"] is None


async def test_get_returns_none_when_missing(db: object) -> None:
    """``get_session`` returns ``None`` for an unknown id."""
    assert await sessions_service.get_session(db, "missing") is None  # type: ignore[arg-type]


async def test_update_only_writes_fields_set_by_caller(db: object) -> None:
    """``model_fields_set`` semantics: only client-supplied fields write."""
    create = await sessions_service.create_session(
        db,  # type: ignore[arg-type]
        SessionCreate(
            working_dir="/tmp/x",  # noqa: S108
            model="sonnet",
            title="orig",
            kind="chat",
        ),
    )
    update = SessionUpdate(title="renamed")
    updated = await sessions_service.update_session(db, create["id"], update)  # type: ignore[arg-type]
    assert updated is not None
    assert updated["title"] == "renamed"
    # Untouched field remains.
    assert updated["model"] == "sonnet"


async def test_delete_returns_false_when_missing(db: object) -> None:
    """``delete_session`` returns False if no row matched."""
    assert await sessions_service.delete_session(db, "nope") is False  # type: ignore[arg-type]
