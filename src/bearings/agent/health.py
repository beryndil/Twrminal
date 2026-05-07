"""Health-snapshot builder for ``GET /api/health``.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/health.py`` is
the readiness/liveness endpoint used by systemd and external
monitoring. Behavior docs are silent on the response shape; see
``src/bearings/config/constants.py`` §"Health" for the
decided-and-documented contract:

* HTTP status is always 200 (the response is "the server is alive").
* The JSON ``status`` field carries the deeper readiness signal
  (``ok`` when DB probe succeeds, ``degraded`` when it fails or the
  DB is not configured).
* ``db_ok`` is the explicit boolean readiness flag.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    HEALTH_DB_PROBE_QUERY,
    HEALTH_STATUS_DEGRADED,
    HEALTH_STATUS_OK,
)


@dataclass(frozen=True)
class HealthSnapshot:
    """Full health response shape."""

    status: str
    version: str
    uptime_s: float
    db_ok: bool
    data_dir: str


async def _probe_db(conn: aiosqlite.Connection | None) -> bool:
    """Run :data:`HEALTH_DB_PROBE_QUERY` against ``conn``; ``False`` on any error.

    Tolerant by design — a transient SQLite error on the probe should
    surface as ``db_ok=false`` in the wire response, not as a 500.
    """
    if conn is None:
        return False
    try:
        async with conn.execute(HEALTH_DB_PROBE_QUERY) as cur:
            row = await cur.fetchone()
    except Exception:
        return False
    return row is not None


async def build_health(
    *,
    db_connection: aiosqlite.Connection | None,
    version: str,
    uptime_s: float,
    data_dir: str = "",
) -> HealthSnapshot:
    """Assemble the health snapshot, probing the DB when configured."""
    db_ok = await _probe_db(db_connection)
    status = HEALTH_STATUS_OK if db_ok else HEALTH_STATUS_DEGRADED
    return HealthSnapshot(
        status=status,
        version=version,
        uptime_s=uptime_s,
        db_ok=db_ok,
        data_dir=data_dir,
    )


__all__ = ["HealthSnapshot", "build_health"]
