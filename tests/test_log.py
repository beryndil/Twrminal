"""Tests for bearings.log."""

from typing import cast

from structlog.types import EventDict, WrappedLogger

from bearings.log import _redact_sensitive, configure_logging, get_logger


def test_redact_sensitive_known_keys() -> None:
    """Sensitive-named keys have values replaced with `***`."""
    event_dict: EventDict = {
        "event": "auth_attempt",
        "password": "hunter2",
        "token": "secret-token",
        "user_id": 42,
    }
    redacted = _redact_sensitive(cast(WrappedLogger, None), "info", event_dict)
    assert redacted["password"] == "***"
    assert redacted["token"] == "***"
    assert redacted["user_id"] == 42  # untouched
    assert redacted["event"] == "auth_attempt"


def test_redact_sensitive_case_insensitive() -> None:
    """Key matching is case-insensitive."""
    event_dict: EventDict = {"Authorization": "Bearer xyz", "Cookie": "session=abc"}
    redacted = _redact_sensitive(cast(WrappedLogger, None), "info", event_dict)
    assert redacted["Authorization"] == "***"
    assert redacted["Cookie"] == "***"


def test_redact_sensitive_no_op_for_safe_keys() -> None:
    """Keys not on the deny-list are untouched."""
    event_dict: EventDict = {"event": "hello", "user_id": 42, "plan": "pro"}
    redacted = _redact_sensitive(cast(WrappedLogger, None), "info", event_dict)
    assert redacted == {"event": "hello", "user_id": 42, "plan": "pro"}


def test_configure_logging_dev_mode() -> None:
    """ConsoleRenderer mode runs without raising."""
    configure_logging(level="INFO", json=False)
    logger = get_logger("test")
    logger.info("dev_event", key="value")  # should not raise


def test_configure_logging_json_mode() -> None:
    """JSONRenderer mode runs without raising."""
    configure_logging(level="DEBUG", json=True)
    logger = get_logger("test")
    logger.info("prod_event", key="value")


def test_get_logger_has_logger_methods() -> None:
    """get_logger returns an object with the expected logger methods."""
    configure_logging(level="INFO", json=False)
    logger = get_logger("test")
    assert callable(logger.debug)
    assert callable(logger.info)
    assert callable(logger.warning)
    assert callable(logger.error)
    assert callable(logger.critical)
