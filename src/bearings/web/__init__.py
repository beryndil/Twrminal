"""HTTP web layer.

FastAPI app factory + routers + middleware. Built in §8 on top of the
§7 foundation (config + log + errors + DB). The split mirrors the
service-layer rules in the plan-of-record:

- :mod:`bearings.web.app` — :func:`create_app` factory; wires routers,
  middleware, exception handlers, and the per-request DB connection
  dependency.
- :mod:`bearings.web.auth` — shared-token ``X-Bearings-Token`` header
  enforcement via FastAPI's :class:`APIKeyHeader`.
- :mod:`bearings.web.errors` — exception handlers translating Python
  exceptions to the stable ``{"error": {...}}`` JSON envelope.
- :mod:`bearings.web.logging` — request-context middleware binding
  ``request_id`` to structlog's contextvars so every log event in the
  request inherits it.
- :mod:`bearings.web.routers` — one module per resource. Routers are
  thin: validate → call service → return response model.

Public API: :func:`create_app` (called by ``bearings.app._bootstrap``
when the v0.2.0 wiring lands), :func:`require_auth` (FastAPI
dependency for protected routes — re-exported here for convenience).
"""

from bearings.web.app import create_app
from bearings.web.auth import require_auth

__all__ = ["create_app", "require_auth"]
