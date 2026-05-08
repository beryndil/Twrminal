"""FastAPI dependency helpers shared across ``routes/`` modules.

This module is the single source of truth for the two ``app.state``
accessors that were previously duplicated verbatim in
:mod:`bearings.web.routes.routing`, :mod:`bearings.web.routes.quota`,
and :mod:`bearings.web.routes.usage` — identified in V1_FEATURE_AUDIT.md
feature 3 finding 3.

Centralising here means:

* A single docstring explains the 503 / ``None`` contracts once.
* Future route modules import rather than copy.
* The type-ignore on the ``no-any-return`` suppression is auditable in
  one place.

Public surface
--------------
* :func:`_db` — pull the long-lived :class:`aiosqlite.Connection` off
  ``app.state``; raises ``HTTP 503`` when absent.
* :func:`_quota_poller` — pull the optional
  :class:`bearings.agent.quota.QuotaPoller` off ``app.state``; returns
  ``None`` when absent (callers fall back to :func:`bearings.agent.quota.load_latest`).
"""

from __future__ import annotations

import aiosqlite
from fastapi import HTTPException, Request, status

from bearings.agent.quota import QuotaPoller


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``.

    Raises ``HTTP 503`` when the application was constructed without a
    DB connection (e.g. a misconfigured startup or a test app that
    intentionally omits the DB).  All route modules that need a
    synchronous handle to the SQLite connection use this helper so the
    503 contract is enforced uniformly.
    """
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return db  # type: ignore[no-any-return]


def _quota_poller(request: Request) -> QuotaPoller | None:
    """Pull the optional quota poller off ``app.state``.

    Returns ``None`` rather than raising when no poller is configured —
    callers fall back to :func:`bearings.agent.quota.load_latest` against
    the DB so a missing poller (e.g. tests that don't start it) still
    produces a quota-aware response.  The preview endpoint and the quota
    endpoints both use this pattern.
    """
    poller = getattr(request.app.state, "quota_poller", None)
    if poller is None:
        return None
    return poller  # type: ignore[no-any-return]


__all__ = ["_db", "_quota_poller"]
