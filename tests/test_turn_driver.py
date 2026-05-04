"""Tests for :mod:`bearings.agent.turn_driver`.

Covers the drain-loop contract for the production TurnDriver closure:

* Normal completion — ``MessageComplete`` arrives → body returned.
* Fatal error — ``ErrorEvent(fatal=True)`` arrives → ``RuntimeError`` raised.
* Non-fatal error — ignored; drain waits for ``MessageComplete``.
* Non-terminal events (``Token``) before completion are skipped.
* Subscriber is cleaned up after both success and failure paths.
"""

from __future__ import annotations

import asyncio

import pytest

from bearings.agent.events import (
    ErrorEvent,
    MessageComplete,
    Token,
)
from bearings.agent.runner import SessionRunner
from bearings.agent.turn_driver import build_turn_driver

# Stable fake ids used across all tests.
_FAKE_MSG_ID = "msg_fake000000000000000000000000"
_FAKE_SESSION_ID = "ses_testdriver000000000000000000"


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


class _FakeMessage:
    """Minimal stand-in for ``bearings.db.messages.Message``."""

    id: str = _FAKE_MSG_ID
    content: str = "test prompt"


class _FakeDB:
    """Minimal stand-in for ``aiosqlite.Connection``."""

    async def execute(self, *_: object, **__: object) -> object:
        return None

    async def commit(self) -> None:
        pass


@pytest.fixture()
def runner() -> SessionRunner:
    return SessionRunner(_FAKE_SESSION_ID)


@pytest.fixture()
def fake_db() -> _FakeDB:
    return _FakeDB()


def _patch_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``messages_db.insert_user`` with a fake that returns _FakeMessage."""
    import bearings.db.messages as messages_module

    async def _fake(
        _db: object,
        *,
        session_id: str,
        content: str,
    ) -> _FakeMessage:
        return _FakeMessage()

    monkeypatch.setattr(messages_module, "insert_user", _fake)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_body_on_message_complete(
    runner: SessionRunner,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MessageComplete → body text returned."""
    _patch_insert(monkeypatch)
    turn_driver = build_turn_driver(db_connection=fake_db)  # type: ignore[arg-type]

    async def _emit() -> None:
        await asyncio.sleep(0)
        await runner.emit(
            MessageComplete(
                session_id=_FAKE_SESSION_ID,
                message_id=_FAKE_MSG_ID,
                content="hello from the agent",
            )
        )

    _task = asyncio.create_task(_emit())  # noqa: RUF006
    result = await turn_driver(runner, "test prompt")
    assert result == "hello from the agent"


@pytest.mark.asyncio
async def test_raises_on_fatal_error(
    runner: SessionRunner,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ErrorEvent(fatal=True) → RuntimeError raised."""
    _patch_insert(monkeypatch)
    turn_driver = build_turn_driver(db_connection=fake_db)  # type: ignore[arg-type]

    async def _emit() -> None:
        await asyncio.sleep(0)
        await runner.emit(
            ErrorEvent(
                session_id=_FAKE_SESSION_ID,
                message="SDK subprocess crashed",
                fatal=True,
            )
        )

    _task = asyncio.create_task(_emit())  # noqa: RUF006
    with pytest.raises(RuntimeError, match="SDK subprocess crashed"):
        await turn_driver(runner, "test prompt")


@pytest.mark.asyncio
async def test_non_fatal_error_does_not_raise(
    runner: SessionRunner,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ErrorEvent(fatal=False) is ignored; drain waits for MessageComplete."""
    _patch_insert(monkeypatch)
    turn_driver = build_turn_driver(db_connection=fake_db)  # type: ignore[arg-type]

    async def _emit() -> None:
        await asyncio.sleep(0)
        await runner.emit(
            ErrorEvent(
                session_id=_FAKE_SESSION_ID,
                message="transient warning",
                fatal=False,
            )
        )
        await runner.emit(
            MessageComplete(
                session_id=_FAKE_SESSION_ID,
                message_id=_FAKE_MSG_ID,
                content="recovered body",
            )
        )

    _task = asyncio.create_task(_emit())  # noqa: RUF006
    result = await turn_driver(runner, "test prompt")
    assert result == "recovered body"


@pytest.mark.asyncio
async def test_intermediate_token_events_skipped(
    runner: SessionRunner,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token events before MessageComplete are skipped; body still returned."""
    _patch_insert(monkeypatch)
    turn_driver = build_turn_driver(db_connection=fake_db)  # type: ignore[arg-type]

    async def _emit() -> None:
        await asyncio.sleep(0)
        for delta in ("word1 ", "word2 ", "word3"):
            await runner.emit(
                Token(
                    session_id=_FAKE_SESSION_ID,
                    message_id=_FAKE_MSG_ID,
                    delta=delta,
                )
            )
        await runner.emit(
            MessageComplete(
                session_id=_FAKE_SESSION_ID,
                message_id=_FAKE_MSG_ID,
                content="final answer",
            )
        )

    _task = asyncio.create_task(_emit())  # noqa: RUF006
    result = await turn_driver(runner, "test prompt")
    assert result == "final answer"


@pytest.mark.asyncio
async def test_unsubscribes_after_completion(
    runner: SessionRunner,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subscriber count returns to 0 after MessageComplete."""
    _patch_insert(monkeypatch)
    turn_driver = build_turn_driver(db_connection=fake_db)  # type: ignore[arg-type]
    assert runner.subscriber_count == 0

    async def _emit() -> None:
        await asyncio.sleep(0)
        await runner.emit(
            MessageComplete(
                session_id=_FAKE_SESSION_ID,
                message_id=_FAKE_MSG_ID,
                content="body",
            )
        )

    _task = asyncio.create_task(_emit())  # noqa: RUF006
    await turn_driver(runner, "test prompt")
    assert runner.subscriber_count == 0


@pytest.mark.asyncio
async def test_unsubscribes_on_fatal_error(
    runner: SessionRunner,
    fake_db: _FakeDB,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subscriber is removed even when a fatal error causes an exception."""
    _patch_insert(monkeypatch)
    turn_driver = build_turn_driver(db_connection=fake_db)  # type: ignore[arg-type]

    async def _emit() -> None:
        await asyncio.sleep(0)
        await runner.emit(
            ErrorEvent(
                session_id=_FAKE_SESSION_ID,
                message="fatal",
                fatal=True,
            )
        )

    _task = asyncio.create_task(_emit())  # noqa: RUF006
    with pytest.raises(RuntimeError):
        await turn_driver(runner, "test prompt")
    assert runner.subscriber_count == 0
