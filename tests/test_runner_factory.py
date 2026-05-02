"""Unit tests — :mod:`bearings.web.runner_factory`.

Covers the in-process registry semantics: sticky runners (the same
runner is returned for the same session id), separate runners per id,
``get`` accessor, ``close_all`` test-only teardown.

The cycle-prevention test in :mod:`tests.test_session_runner_factory`
already verifies the ``agent`` package never imports ``bearings.web``;
this test covers the ``web`` side of the binding.
"""

from __future__ import annotations

import pytest

from bearings.agent.runner import RunnerFactory, SessionRunner
from bearings.web.runner_factory import (
    InProcessRunnerRegistry,
    build_in_process_factory,
)


async def test_factory_returns_sticky_runner_for_same_session_id() -> None:
    factory = InProcessRunnerRegistry()
    a = await factory("sess-1")
    b = await factory("sess-1")
    assert a is b


async def test_factory_returns_separate_runners_for_different_ids() -> None:
    factory = InProcessRunnerRegistry()
    a = await factory("sess-1")
    b = await factory("sess-2")
    assert a is not b
    assert a.session_id == "sess-1"
    assert b.session_id == "sess-2"


async def test_factory_rejects_empty_session_id() -> None:
    factory = InProcessRunnerRegistry()
    with pytest.raises(ValueError, match="session_id"):
        await factory("")


async def test_get_returns_existing_runner() -> None:
    registry = InProcessRunnerRegistry()
    created = await registry("sess-1")
    assert registry.get("sess-1") is created


def test_get_returns_none_for_unknown_id() -> None:
    registry = InProcessRunnerRegistry()
    assert registry.get("nonexistent") is None


async def test_close_all_drops_runners() -> None:
    registry = InProcessRunnerRegistry()
    await registry("sess-1")
    await registry("sess-2")
    registry.close_all()
    assert registry.get("sess-1") is None
    assert registry.get("sess-2") is None


async def test_build_in_process_factory_returns_runner_factory() -> None:
    factory: RunnerFactory = build_in_process_factory()
    runner = await factory("sess-1")
    assert isinstance(runner, SessionRunner)


def test_module_exports() -> None:
    from bearings.web import runner_factory as runner_factory_mod

    assert set(runner_factory_mod.__all__) == {
        "InProcessRunnerRegistry",
        "SessionSetup",
        "SessionSetupFn",
        "build_in_process_factory",
    }
