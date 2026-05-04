# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/tags.py`` + ``routes/memories.py``.

Per ``docs/architecture-v1.md`` §1.1.5 the wire DTOs live alongside
the route module. The shapes mirror :class:`bearings.db.tags.Tag` and
:class:`bearings.db.memories.TagMemory` row dataclasses; the API layer
constructs an ``Out`` model from a row dataclass at the wire boundary
and validates ``In`` payloads at request entry.

The ``mypy: disable-error-code=explicit-any`` pragma is the same narrow
carve-out :mod:`bearings.web.serialize` and :mod:`bearings.agent.events`
make for Pydantic's metaclass-exposed ``Any`` surface. Restricting the
disable to this file keeps the carve-out narrow — every public
``BaseModel`` subclass below has a fully-typed field set.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bearings.config.constants import (
    TAG_COLOR_MAX_LENGTH,
    TAG_MEMORY_BODY_MAX_LENGTH,
    TAG_MEMORY_TITLE_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
)


class TagIn(BaseModel):
    """Request body for ``POST /api/tags`` and ``PATCH /api/tags/{id}``.

    The validators mirror :class:`bearings.db.tags.Tag.__post_init__`
    so a bad payload fails at the wire boundary with a 422 rather than
    surfacing a 500 from the dataclass downstream. ``model_config``
    forbids extra fields so a typo (e.g. ``defaultModel`` instead of
    ``default_model``) is rejected loudly.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=TAG_NAME_MAX_LENGTH)
    color: str | None = Field(default=None, max_length=TAG_COLOR_MAX_LENGTH)
    default_model: str | None = None
    working_dir: str | None = Field(default=None, min_length=1)


class TagOut(BaseModel):
    """Response body for tag endpoints.

    ``group`` is computed from ``name`` (slash-namespace convention per
    :data:`bearings.config.constants.TAG_GROUP_SEPARATOR`) and exposed
    so the frontend filter panel doesn't have to re-parse it.
    ``pinned`` controls sidebar sort order — pinned tags float to the
    top of the filter panel per context-menus §"Tag".
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    color: str | None
    default_model: str | None
    working_dir: str | None
    pinned: bool
    group: str | None
    created_at: str
    updated_at: str


class TagPinnedUpdate(BaseModel):
    """Request body for ``PATCH /api/tags/{id}/pinned``.

    ``pinned=true`` pins the tag in the sidebar filter panel;
    ``pinned=false`` unpins it. Mirrors :class:`SessionPinnedUpdate`.
    """

    model_config = ConfigDict(extra="forbid")

    pinned: bool


class TagMemoryIn(BaseModel):
    """Request body for memory create / update endpoints."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=TAG_MEMORY_TITLE_MAX_LENGTH)
    body: str = Field(min_length=1, max_length=TAG_MEMORY_BODY_MAX_LENGTH)
    enabled: bool = True


class TagMemoryOut(BaseModel):
    """Response body for memory endpoints."""

    model_config = ConfigDict(extra="forbid")

    id: int
    tag_id: int
    title: str
    body: str
    enabled: bool
    created_at: str
    updated_at: str


__all__ = ["TagIn", "TagMemoryIn", "TagMemoryOut", "TagOut", "TagPinnedUpdate"]
