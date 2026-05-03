"""User-preferences singleton endpoint (item 3.2).

Exposes two operations against the :class:`bearings.db.preferences.Preferences`
singleton row:

* ``GET /api/preferences`` — return current values.
* ``PATCH /api/preferences`` — update supplied fields; omitted fields
  are left unchanged.

The preferences row is seeded by ``schema.sql``'s
``INSERT OR IGNORE INTO preferences (id) VALUES (1)`` and therefore
always exists after :func:`bearings.db.connection.load_schema` has run.

PATCH semantics (Pydantic ``model_fields_set``)
------------------------------------------------
The request body is a JSON object; only explicitly-supplied keys are
written to the DB. This means:

* ``{}``                    — no-op; returns current row.
* ``{"theme": "evergreen"}``— updates theme only.
* ``{"default_model": null}``— clears default_model to NULL.
* ``{"default_model": "haiku", "default_working_dir": null}``
                            — updates two fields.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status

from bearings.db import preferences as prefs_db
from bearings.db.preferences import Preferences
from bearings.web.models.preferences import PreferencesOut, PreferencesPatch

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return db  # type: ignore[no-any-return]


def _to_out(prefs: Preferences) -> PreferencesOut:
    return PreferencesOut(
        theme=prefs.theme,
        default_model=prefs.default_model,
        default_permission_mode=prefs.default_permission_mode,
        default_working_dir=prefs.default_working_dir,
        updated_at=prefs.updated_at,
    )


@router.get("/api/preferences", response_model=PreferencesOut)
async def get_preferences(request: Request) -> PreferencesOut:
    """Return the singleton user-preferences row."""
    prefs = await prefs_db.get_preferences(_db(request))
    return _to_out(prefs)


@router.patch("/api/preferences", response_model=PreferencesOut)
async def patch_preferences(
    body: PreferencesPatch,
    request: Request,
) -> PreferencesOut:
    """Partially update user preferences.

    Only fields present in the request body are written; omitted fields
    retain their current values.
    """
    db = _db(request)
    supplied = body.model_fields_set

    # Pass model_fields_set as ``fields`` so patch_preferences knows
    # which nullable columns were explicitly supplied (vs. omitted).
    prefs = await prefs_db.patch_preferences(
        db,
        theme=body.theme if "theme" in supplied else None,
        default_model=body.default_model,
        default_permission_mode=body.default_permission_mode,
        default_working_dir=body.default_working_dir,
        fields=frozenset(supplied - {"theme"}),
    )
    return _to_out(prefs)


__all__ = ["router"]
