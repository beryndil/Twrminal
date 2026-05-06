"""Tests for bearings.errors.

The exit-code test (:func:`test_uncaught_exception_exits_nonzero`)
encodes the Op directive **fail fast at boundaries** — exit code is
the channel that wrapping shells, CI runners, and supervisors check;
log lines aren't enough.

Tests pass exception classes to ``_handle_exception`` directly with
``traceback=None`` rather than capturing a real ``sys.exc_info()``
tuple. The handler doesn't introspect the traceback (it just hands it
to structlog as ``exc_info``); a None traceback exercises the same
code path with less ceremony.
"""

import sys

import pytest

from bearings.errors import _handle_exception, setup_exception_handler


def test_setup_installs_handler() -> None:
    """setup_exception_handler replaces sys.excepthook with our handler."""
    original = sys.excepthook
    try:
        setup_exception_handler()
        assert sys.excepthook is _handle_exception
    finally:
        sys.excepthook = original


def test_keyboard_interrupt_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl-C is delegated to the original excepthook so exit code is 130."""
    calls: list[tuple[object, ...]] = []

    def fake_default_hook(*args: object) -> None:
        calls.append(args)

    monkeypatch.setattr("sys.__excepthook__", fake_default_hook)

    _handle_exception(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert len(calls) == 1
    assert calls[0][0] is KeyboardInterrupt


def test_uncaught_exception_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handler logs and exits cleanly — it doesn't itself raise."""
    exit_calls: list[int] = []
    monkeypatch.setattr("sys.exit", exit_calls.append)

    _handle_exception(RuntimeError, RuntimeError("test"), None)


def test_uncaught_exception_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Op directive: fail fast at boundaries.

    An uncaught exception must exit with a non-zero status so wrapping
    shells, CI runners, and supervisors see the failure. Logging alone
    isn't enough — exit code 0 after a crash silently lies about
    success.
    """
    exit_calls: list[int] = []
    monkeypatch.setattr("sys.exit", exit_calls.append)

    _handle_exception(ValueError, ValueError("boom"), None)

    assert exit_calls == [1], (
        f"expected sys.exit(1) after logging uncaught exception; got {exit_calls}"
    )
