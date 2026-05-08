# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/preferences.py`` (item 3.2)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from bearings.config.constants import DISPLAY_NAME_MAX_LENGTH


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
    # gap-cycle-07-001: desktop-notification opt-in (default False).
    notify_on_complete: bool
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
    # CCW-2 / feature-8-002: enforce DISPLAY_NAME_MAX_LENGTH at the wire
    # boundary so PATCH behaves identically to sync_from_system truncation.
    display_name: Annotated[str | None, Field(max_length=DISPLAY_NAME_MAX_LENGTH)] = None
    # gap-cycle-07-001: desktop-notification opt-in.
    # CCW-2 / feature-8-003: column is NOT NULL DEFAULT 0; null is never
    # legitimate — tighten to bool so Pydantic rejects {"notify_on_complete": null}.
    notify_on_complete: bool = False

    # Tracks which fields the caller explicitly set so the route can
    # distinguish "caller sent null" from "caller omitted the field".
    # Pydantic v2 model_fields_set fills this automatically.


__all__ = ["PreferencesOut", "PreferencesPatch"]
