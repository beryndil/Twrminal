"""Global exception handler.

Implements **Op directive: Zero-Crash** — uncaught exceptions are
captured, logged with full traceback, and never escape silently. This
base module installs a synchronous ``sys.excepthook`` only; recipes
provide framework-specific extensions:

- FastAPI: register an ``@app.exception_handler(Exception)`` that
  delegates here.
- PyQt5: install via ``threading.excepthook`` too (Qt swallows
  worker-thread exceptions otherwise).
- asyncio: register ``loop.set_exception_handler`` on the running loop.

Call :func:`setup_exception_handler` once at application bootstrap,
*after* :func:`bearings.log.configure_logging` (so the handler can
emit structured events).
"""

import sys
from types import TracebackType

import structlog

logger = structlog.get_logger(__name__)


def _handle_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    """Log an uncaught exception with structured context.

    Ctrl-C (``KeyboardInterrupt``) is intentionally passed through to
    the default handler so the process exits with the conventional
    status 130 — swallowing it would leave users unable to interrupt
    a stuck application.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error(
        "uncaught_exception",
        exc_type=exc_type.__name__,
        exc_message=str(exc_value),
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    # Op directive: fail fast at boundaries. Logging alone leaves the
    # process in a "succeeded" state from the OS's perspective; wrapping
    # shells, CI runners, and supervisors check exit code, not log lines.
    sys.exit(1)


def setup_exception_handler() -> None:
    """Install :func:`_handle_exception` as the global excepthook.

    Idempotent: safe to call more than once.
    """
    sys.excepthook = _handle_exception
