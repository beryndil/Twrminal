# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/preferences.py`` (item 3.2)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PreferencesOut(BaseModel):
    """Response shape for GET / PATCH / avatar ``/api/preferences``."""

    model_config = ConfigDict(extra="forbid")

    theme: str
    default_model: str | None
    default_permission_mode: str | None
    default_working_dir: str | None
    # gap-cycle-03-011 profile / identity fields.
    # ``display_name`` is the human-readable name shown in the identity block.
    # ``avatar_url`` is the URL path to serve the avatar image
    # (``/api/preferences/avatar``), or ``None`` when no avatar is set.
    # The frontend appends ``?v=<updated_at>`` for cache-busting.
    display_name: str | None
    avatar_url: str | None
    updated_at: str


class PreferencesPatch(BaseModel):
    """Request shape for PATCH ``/api/preferences``.

    All fields are optional; omitted fields are not modified.  To clear
    a nullable field to NULL supply ``null`` explicitly in the JSON
    body.
    """

    model_config = ConfigDict(extra="forbid")

    theme: str | None = None
    default_model: str | None = None
    default_permission_mode: str | None = None
    default_working_dir: str | None = None
    # gap-cycle-03-011: display_name is patchable via the normal PATCH
    # endpoint; avatar_path / avatar_mime_type are managed by the
    # dedicated avatar upload/delete/sync routes only and are therefore
    # NOT exposed here (prevents a caller from writing an arbitrary path).
    display_name: str | None = None

    # Tracks which fields the caller explicitly set so the route can
    # distinguish "caller sent null" from "caller omitted the field".
    # Pydantic v2 model_fields_set fills this automatically.


__all__ = ["PreferencesOut", "PreferencesPatch"]
