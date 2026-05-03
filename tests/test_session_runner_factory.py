"""``RunnerFactory`` Protocol tests + cycle-prevention guard.

Covers:

* :class:`bearings.agent.runner.RunnerFactory` is a typing
  :class:`typing.Protocol` (not an ABC) whose only member is an async
  ``__call__(session_id) -> SessionRunner``;
* a concrete async function with the same shape satisfies the
  Protocol (structural typing — verified by calling it through a
  variable annotated with the Protocol type and observing mypy +
  runtime do not reject);
* the SDK-forwarding methods on :class:`bearings.agent.session.AgentSession`
  serialise correctly when a mock client is attached;
* the cycle-prevention guard: every ``*.py`` under
  ``src/bearings/agent/`` AST-walks to zero ``bearings.web.*`` and
  zero ``bearings.cli.*`` imports (per arch §3.1 rule #1 and §3.2's
  catalogue of v0.17.x cycles).
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from typing import get_type_hints
from unittest.mock import AsyncMock

import pytest

from bearings.agent import runner as runner_module
from bearings.agent.routing import RoutingDecision
from bearings.agent.runner import RunnerFactory, RunnerStatus, SessionRunner
from bearings.agent.session import (
    AgentSession,
    SessionConfig,
    SessionState,
    SessionStateError,
)

# ---------------------------------------------------------------------------
# RunnerFactory Protocol shape
# ---------------------------------------------------------------------------


def test_runner_factory_is_a_protocol() -> None:
    """Per arch §4.5 the type is a :class:`typing.Protocol`."""
    # Protocol classes set ``_is_protocol`` to True at class
    # construction (typing-internal flag); using getattr keeps this
    # test resilient to renames.
    assert getattr(RunnerFactory, "_is_protocol", False) is True


def test_runner_factory_signature() -> None:
    """The Protocol's ``__call__`` takes ``session_id: str`` and is async."""
    sig = inspect.signature(RunnerFactory.__call__)
    params = sig.parameters
    assert "session_id" in params
    # Async coroutines have a ``CO_COROUTINE`` flag; iscoroutinefunction
    # returns True for ``async def``.
    assert inspect.iscoroutinefunction(RunnerFactory.__call__)


async def test_concrete_async_callable_satisfies_protocol() -> None:
    """A bare ``async def`` of the right shape is structurally
    assignable to :class:`RunnerFactory`."""

    async def build(session_id: str) -> SessionRunner:
        # Item 1.2 fills the body — session id is now required.
        return SessionRunner(session_id)

    factory: RunnerFactory = build
    runner = await factory("sess-1")
    assert isinstance(runner, SessionRunner)
    assert runner.session_id == "sess-1"


def test_runner_status_is_frozen_with_routing_decision() -> None:
    """Arch §4.11 — RunnerStatus carries the active routing decision."""
    decision = RoutingDecision(
        executor_model="sonnet",
        advisor_model="opus",
        advisor_max_uses=5,
        effort_level="auto",
        source="default",
        reason="status test",
        matched_rule_id=None,
    )
    status = RunnerStatus(
        is_running=True,
        is_awaiting_user=False,
        routing_decision=decision,
    )
    assert status.routing_decision == decision
    # Frozen — assignment raises.
    with pytest.raises(Exception):  # FrozenInstanceError
        status.is_running = False  # type: ignore[misc]


def test_runner_status_routing_decision_is_optional() -> None:
    status = RunnerStatus(is_running=False, is_awaiting_user=True, routing_decision=None)
    assert status.routing_decision is None


# ---------------------------------------------------------------------------
# Forwards through the attached SDK client (mocked)
# ---------------------------------------------------------------------------


def _make_running_session() -> AgentSession:
    sess = AgentSession(
        SessionConfig(
            session_id="sess-1",
            working_dir="/tmp/forward",
            decision=RoutingDecision(
                executor_model="sonnet",
                advisor_model="opus",
                advisor_max_uses=5,
                effort_level="auto",
                source="default",
                reason="forward test",
                matched_rule_id=None,
            ),
            db=None,
        )
    )
    return sess


async def test_attach_then_set_model_forwards() -> None:
    sess = _make_running_session()
    await sess.start()
    client = AsyncMock()
    sess.attach_sdk_client(client)
    assert sess.has_sdk_client is True

    await sess.set_model("haiku")
    client.set_model.assert_awaited_once_with("haiku")


async def test_attach_then_set_permission_mode_forwards() -> None:
    sess = _make_running_session()
    await sess.start()
    client = AsyncMock()
    sess.attach_sdk_client(client)

    await sess.set_permission_mode("plan")
    client.set_permission_mode.assert_awaited_once_with("plan")


async def test_set_permission_mode_unknown_rejected_before_forward() -> None:
    sess = _make_running_session()
    await sess.start()
    client = AsyncMock()
    sess.attach_sdk_client(client)

    with pytest.raises(ValueError, match="permission_mode"):
        await sess.set_permission_mode("nonsense")
    client.set_permission_mode.assert_not_awaited()


async def test_interrupt_forwards_in_running() -> None:
    sess = _make_running_session()
    await sess.start()
    client = AsyncMock()
    sess.attach_sdk_client(client)

    await sess.interrupt()
    client.interrupt.assert_awaited_once()


async def test_interrupt_forwards_in_paused() -> None:
    """Interrupt is valid in PAUSED too (turn-level action)."""
    sess = _make_running_session()
    await sess.start()
    client = AsyncMock()
    sess.attach_sdk_client(client)
    await sess.pause()

    await sess.interrupt()
    client.interrupt.assert_awaited_once()


async def test_set_model_without_client_raises() -> None:
    sess = _make_running_session()
    await sess.start()
    with pytest.raises(SessionStateError, match="set_model"):
        await sess.set_model("haiku")


async def test_set_model_outside_running_raises() -> None:
    sess = _make_running_session()
    client = AsyncMock()
    sess.attach_sdk_client(client)
    # Still in INITIALIZING.
    assert sess.state == SessionState.INITIALIZING
    with pytest.raises(SessionStateError, match="set_model"):
        await sess.set_model("haiku")


async def test_interrupt_without_client_raises() -> None:
    sess = _make_running_session()
    with pytest.raises(SessionStateError, match="no SDK client"):
        await sess.interrupt()


async def test_interrupt_from_closed_raises() -> None:
    sess = _make_running_session()
    client = AsyncMock()
    sess.attach_sdk_client(client)
    await sess.close()
    with pytest.raises(SessionStateError, match="cannot interrupt"):
        await sess.interrupt()


async def test_double_attach_raises() -> None:
    sess = _make_running_session()
    sess.attach_sdk_client(AsyncMock())
    with pytest.raises(SessionStateError, match="already has"):
        sess.attach_sdk_client(AsyncMock())


async def test_detach_returns_client_and_clears() -> None:
    sess = _make_running_session()
    client = AsyncMock()
    sess.attach_sdk_client(client)
    returned = sess.detach_sdk_client()
    assert returned is client
    assert sess.has_sdk_client is False
    # Detach again — idempotent, returns None.
    assert sess.detach_sdk_client() is None


# ---------------------------------------------------------------------------
# Cycle-prevention guard (arch §3.1 rule #1, §3.2 cycle catalogue)
# ---------------------------------------------------------------------------


_AGENT_PKG_DIR = pathlib.Path(__file__).parent.parent / "src" / "bearings" / "agent"


def _module_imports(path: pathlib.Path) -> set[str]:
    """Return the set of module names this file imports (top-level
    plus ``from X import ...``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def test_agent_package_directory_exists() -> None:
    assert _AGENT_PKG_DIR.is_dir(), f"missing {_AGENT_PKG_DIR}"
    # Sanity — at least the four files item 1.1 lays down.
    names = {p.name for p in _AGENT_PKG_DIR.glob("*.py")}
    assert {"__init__.py", "session.py", "events.py", "runner.py", "routing.py"} <= names


def test_no_agent_module_imports_web_layer() -> None:
    """Per arch §3.1 #1, the ``agent`` layer never imports from
    ``bearings.web`` — that would resurrect the v0.17.x lazy-import
    cycle the rebuild explicitly broke (arch §3.2)."""
    offenders: list[tuple[str, str]] = []
    for py in _AGENT_PKG_DIR.glob("*.py"):
        for imp in _module_imports(py):
            if imp.startswith("bearings.web"):
                offenders.append((py.name, imp))
    assert not offenders, f"agent layer imports web layer: {offenders}"


def test_no_agent_module_imports_cli_layer() -> None:
    """Per arch §3.1 #1, ``agent`` does not import ``bearings.cli``."""
    offenders: list[tuple[str, str]] = []
    for py in _AGENT_PKG_DIR.glob("*.py"):
        for imp in _module_imports(py):
            if imp.startswith("bearings.cli"):
                offenders.append((py.name, imp))
    assert not offenders, f"agent layer imports cli layer: {offenders}"


def test_runner_module_does_not_import_session() -> None:
    """Sibling-cycle guard (arch §3.1 #2): runner declares the
    Protocol that session consumes, but session is the consumer of
    runner, not vice versa. Reversing the edge would re-introduce the
    v0.17.x runner_subscribers ↔ runner cycle (arch §3.2)."""
    imports = _module_imports(_AGENT_PKG_DIR / "runner.py")
    assert "bearings.agent.session" not in imports


def test_runner_factory_protocol_resolvable() -> None:
    """Sanity check: :class:`RunnerFactory`'s ``__call__`` return
    annotation resolves to :class:`SessionRunner` (string forward-refs
    inside ``from __future__ import annotations`` resolve via
    ``typing.get_type_hints``)."""
    hints = get_type_hints(RunnerFactory.__call__)
    assert hints.get("return") is SessionRunner
    # The module-level export surface — arch §4.5's three names plus
    # the ``StreamEntry`` alias item 1.2 added for the web layer plus
    # the ``QueuedPrompt`` dataclass item 1.7 added for the prompt
    # endpoint's ``runner.enqueue_prompt()`` FIFO.
    assert set(runner_module.__all__) == {
        "QueuedPrompt",
        "RunnerFactory",
        "RunnerStatus",
        "SessionRunner",
        "SessionSetup",
        "SessionSetupFn",
        "StreamEntry",
    }


def test_request_stop_sets_event() -> None:
    """request_stop() sets the stop_event; idempotent on double-call."""
    from bearings.agent.runner import SessionRunner

    runner = SessionRunner("ses_test_stop")
    assert not runner.stop_event.is_set()
    runner.request_stop()
    assert runner.stop_event.is_set()
    # Idempotent
    runner.request_stop()
    assert runner.stop_event.is_set()


def test_stop_event_cleared_between_turns() -> None:
    """stop_event starts clear on a fresh runner; can be cleared manually."""
    from bearings.agent.runner import SessionRunner

    runner = SessionRunner("ses_test_stop2")
    runner.request_stop()
    assert runner.stop_event.is_set()
    runner.stop_event.clear()
    assert not runner.stop_event.is_set()
