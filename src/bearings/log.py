"""Structured logging via structlog.

Standards mapped:

- **Op: Zero-Crash** — :func:`configure_logging` is the only documented
  way to produce log output. Combined with ruff's ``T20`` (banning
  ``print()`` / ``pprint()``), every event flows through the structured
  pipeline.
- **Sec rule 2 — no PII or auth tokens in logs** — :func:`_redact_sensitive`
  scrubs values for keys matching a built-in deny-list. Forks extend
  the deny-list with domain-specific PII categories.
- **Op: Timezone — UTC internal** — timestamps are emitted in
  ISO 8601 with explicit ``+00:00`` offset.

The factory :func:`configure_logging` is called once at application
bootstrap (see ``app.main``). After that, modules obtain loggers via
:func:`get_logger` and emit structured events::

    logger = get_logger(__name__)
    logger.info("user.signup", user_id=user.id, plan="pro")
"""

import logging
import sys

import structlog
from structlog.stdlib import BoundLogger
from structlog.types import EventDict, Processor, WrappedLogger

# Keys whose values are scrubbed before emission. Match is
# case-insensitive against the full key name.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "set_cookie",
    }
)


def _redact_sensitive(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Replace values for sensitive keys with ``***`` in-place.

    Sec rule 2: no PII or auth tokens in logs. We can't catch every
    case — a key named ``user_data`` could carry anything — but the
    deny-list catches the common-name leaks (Authorization headers,
    bearer tokens, cookies, password fields).
    """
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***"
    return event_dict


def configure_logging(*, level: str = "INFO", json: bool = False) -> None:
    """Initialise structlog for the running application.

    :param level: Minimum log level (one of ``DEBUG``, ``INFO``,
        ``WARNING``, ``ERROR``, ``CRITICAL``).
    :param json: If true, render each event as a single JSON object on
        stdout (production-friendly, machine-parseable). If false,
        render as a coloured human-readable line for local development.
    """
    # Configure stdlib logging so structlog and any third-party libraries
    # (which use stdlib logging) share one stream and one log level.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_sensitive,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> BoundLogger:
    """Return a structlog logger for *name*.

    Convention: pass ``__name__`` from the calling module so log events
    carry their origin.
    """
    # structlog's get_logger is typed loosely upstream (returns the
    # configured wrapper class, which mypy resolves as Any). The runtime
    # object exposes the BoundLogger interface; the ignore is correct.
    return structlog.get_logger(name)  # type: ignore[no-any-return]
