"""Per-resource query modules.

Convention: one module per resource. As §8 lands, modules like
``sessions.py``, ``tags.py``, ``messages.py`` will live here, each
exposing async functions that take an :class:`aiosqlite.Connection`
plus their inputs and return either domain dataclasses / Pydantic
models or raw row dicts.

This package is intentionally empty in §7 — the foundation needs the
DB layer wired up and migrations runnable, but the schema for actual
resources is owned by their respective build phases.
"""
