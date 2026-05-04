# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/templates.py`` (G7).

Per ``docs/architecture-v1.md`` §1.1.5 the wire DTOs live alongside
their route module. The shapes mirror :class:`bearings.db.templates.Template`
plus a :class:`TemplateIn` create body and :class:`TemplatePatch` update body.

The ``mypy: disable-error-code=explicit-any`` pragma is the same narrow
carve-out the other ``web/models/*.py`` files make for Pydantic's
metaclass-exposed ``Any`` surface — every public ``BaseModel`` subclass
below has a fully-typed field set.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bearings.config.constants import (
    DEFAULT_TEMPLATE_ADVISOR_MAX_USES,
    DEFAULT_TEMPLATE_EFFORT_LEVEL,
    DEFAULT_TEMPLATE_PERMISSION_PROFILE,
    TEMPLATE_DESCRIPTION_MAX_LENGTH,
    TEMPLATE_NAME_MAX_LENGTH,
)


class TemplateIn(BaseModel):
    """Request body for ``POST /api/templates``.

    The DB layer's :func:`bearings.db.templates.create` validates the
    routing-alphabet fields in :class:`bearings.db.templates.Template.__post_init__`;
    a bad payload surfaces as a 422 from the route.
    ``model_config`` forbids extra fields so a typo (e.g. ``permissionProfile``
    instead of ``permission_profile``) is rejected at the wire boundary.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=TEMPLATE_NAME_MAX_LENGTH)
    model: str = Field(min_length=1)
    description: str | None = Field(
        default=None,
        max_length=TEMPLATE_DESCRIPTION_MAX_LENGTH,
    )
    advisor_model: str | None = None
    advisor_max_uses: int = Field(default=DEFAULT_TEMPLATE_ADVISOR_MAX_USES, ge=0)
    effort_level: str = DEFAULT_TEMPLATE_EFFORT_LEVEL
    permission_profile: str = DEFAULT_TEMPLATE_PERMISSION_PROFILE
    system_prompt_baseline: str | None = None
    working_dir_default: str | None = None
    tag_names: list[str] = Field(default_factory=list)


class TemplatePatch(BaseModel):
    """Request body for ``PATCH /api/templates/{id}``.

    Every field is optional; missing fields are filled from the existing
    row so the caller only has to send the delta. The route layer fetches
    the existing row, merges, and calls :func:`bearings.db.templates.update`
    with the full field set.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=TEMPLATE_NAME_MAX_LENGTH)
    model: str | None = Field(default=None, min_length=1)
    description: str | None = None
    advisor_model: str | None = None
    advisor_max_uses: int | None = Field(default=None, ge=0)
    effort_level: str | None = None
    permission_profile: str | None = None
    system_prompt_baseline: str | None = None
    working_dir_default: str | None = None
    tag_names: list[str] | None = None


class TemplateOut(BaseModel):
    """Response body for template endpoints.

    One-to-one with :class:`bearings.db.templates.Template`.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    description: str | None
    model: str
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    permission_profile: str
    system_prompt_baseline: str | None
    working_dir_default: str | None
    tag_names: list[str]
    created_at: str
    updated_at: str


__all__ = ["TemplateIn", "TemplateOut", "TemplatePatch"]
