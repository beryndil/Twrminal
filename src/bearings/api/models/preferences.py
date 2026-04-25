"""Server-side user-preference DTOs (migration 0026).

`PreferencesOut` is the singleton row served by `GET /api/preferences`
and returned again from a successful PATCH. `PreferencesPatch` is the
partial-update body — every field defaults to "unset" so a frontend
that only knows about `display_name` can PATCH that one field without
clobbering the rest. The route uses `model_dump(exclude_unset=True)` to
forward only the fields the client explicitly sent.

Design notes:

* `display_name` carries explicit length validation (max 64) plus a
  trim-and-coalesce-empty validator. Whitespace-only submissions
  collapse to `None` so a stray spacebar press doesn't produce an
  invisible role label in `MessageTurn`. No character restrictions —
  Svelte text interpolation auto-escapes, and the field is purely
  cosmetic; ban-listing characters would be theatre.
* `theme` is a free-form slug for now; the themes session
  (`8b21a8e`) ships `data-theme="<slug>"` on `<html>` and the v1
  selector lands later. Validating against an enum here would require
  re-deploying every time a theme is added; we let the frontend
  authoritatively own the valid-slug set.
* `notify_on_complete` is `bool` here even though the column is
  INTEGER 0/1 — the store layer coerces.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PreferencesOut(BaseModel):
    """Singleton preferences row, served by GET and echoed by PATCH.

    Every field is nullable on the wire because the seed row lands at
    migration time with NULL display_name / theme / model / workdir,
    and `notify_on_complete = 0`. The frontend treats NULL as "unset"
    and falls back to its built-in defaults (literal 'user' for the
    role label, the configured `data-theme`, the global default model
    string, etc.).
    """

    display_name: str | None = None
    theme: str | None = None
    default_model: str | None = None
    default_working_dir: str | None = None
    notify_on_complete: bool = False
    updated_at: str


class PreferencesPatch(BaseModel):
    """Partial update body for PATCH /api/preferences.

    Every field is optional. Fields the client doesn't include stay at
    their current DB value; explicit `null` clears the column (for the
    nullable string columns). `notify_on_complete` is non-nullable in
    the schema, so passing `None` here is rejected by Pydantic.

    Length / coercion rules live on `display_name` only — the other
    string fields are unconstrained because they're system identifiers
    (model slug, filesystem path) the user enters with intent.
    """

    display_name: str | None = Field(default=None, max_length=64)
    theme: str | None = None
    default_model: str | None = None
    default_working_dir: str | None = None
    notify_on_complete: bool | None = None

    @field_validator("display_name", mode="before")
    @classmethod
    def _coalesce_blank_display_name(cls, value: object) -> object:
        """Trim leading/trailing whitespace and collapse empty strings
        to `None` so the DB stores either a meaningful name or NULL.

        Without this, a user who types a name and then deletes it back
        to spaces would land an invisible whitespace-only label in the
        `MessageTurn` header. We don't want to encode "is this string
        meaningful?" logic in every consumer; do it once at the
        boundary.

        Non-string values fall through unchanged so explicit `null`
        from the client (intent: clear the field) still reaches the
        DB layer as `None`."""
        if not isinstance(value, str):
            return value
        trimmed = value.strip()
        return trimmed or None
