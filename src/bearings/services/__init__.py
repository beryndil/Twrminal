"""Service layer.

Composes :mod:`bearings.db.queries` calls into the business operations
the routers expose. The split:

- Routers (``bearings.web.routers.*``) — thin: validate request →
  call service → translate result → return response model.
- Services (here) — own ID generation, defaults, multi-step composition,
  any business validation that needs DB context.
- Queries (``bearings.db.queries.*``) — single SQL ops, no decisions.

A service function takes the inputs the router has already parsed
plus the per-request connection. It returns either a dict (mapped to
a response model by the router) or ``None`` for not-found.
"""
