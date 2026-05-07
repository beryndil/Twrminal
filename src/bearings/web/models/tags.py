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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bearings.config.constants import (
    TAG_CLASS_GENERAL,
    TAG_COLOR_MAX_LENGTH,
    TAG_DEFAULT_SORT_ORDER,
    TAG_MEMORY_BODY_MAX_LENGTH,
    TAG_MEMORY_TITLE_MAX_LENGTH,
    TAG_NAME_MAX_LENGTH,
)

# Wire-shape literal alphabet for the tag class column. Mirrors
# :data:`bearings.config.constants.KNOWN_TAG_CLASSES` so a frontend
# typo like ``"sevrity"`` (codespell:ignore sevrity) is rejected at
# the 422 boundary rather than surfacing a 500 from the dataclass
# downstream.
TagClass = Literal["project", "severity", "general"]


class TagIn(BaseModel):
    """Request body for ``POST /api/tags`` and ``PATCH /api/tags/{id}``.

    The validators mirror :class:`bearings.db.tags.Tag.__post_init__`
    so a bad payload fails at the wire boundary with a 422 rather than
    surfacing a 500 from the dataclass downstream. ``model_config``
    forbids extra fields so a typo (e.g. ``defaultModel`` instead of
    ``default_model``) is rejected loudly.

    The ``class_`` field is the tag-class feature partition; the
    trailing underscore matches the Python attribute on
    :class:`bearings.db.tags.Tag` and the JSON wire key (uniform
    naming across the layer rather than aliasing ``class`` only on
    the wire).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=TAG_NAME_MAX_LENGTH)
    color: str | None = Field(default=None, max_length=TAG_COLOR_MAX_LENGTH)
    default_model: str | None = None
    working_dir: str | None = Field(default=None, min_length=1)
    class_: TagClass = TAG_CLASS_GENERAL  # type: ignore[assignment]
    sort_order: int = Field(default=TAG_DEFAULT_SORT_ORDER, ge=0)


class TagOut(BaseModel):
    """Response body for tag endpoints.

    ``class_`` partitions the tag into project / severity / general
    (see :data:`bearings.config.constants.KNOWN_TAG_CLASSES`).
    ``sort_order`` is the per-class display order. ``pinned`` floats
    the tag to the top of its class section per context-menus §"Tag".

    ``group`` is the deprecated slash-prefix carrier (parsed from
    ``name``); retained for back-compat with v0.18.x frontend builds
    that still consume it. New consumers should use ``class_``.

    ``open_session_count`` is the number of sessions carrying this tag
    whose ``closed_at`` is NULL (i.e. open). ``session_count`` is the
    total number of sessions carrying this tag regardless of close
    state. Both fields are populated for the ``GET /api/tags`` listing
    via a single LEFT JOIN aggregation in
    :func:`bearings.db.tags.list_all_with_counts`; single-tag endpoints
    default to ``0`` (counts are a listing concern, not a per-tag
    concern).
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    color: str | None
    default_model: str | None
    working_dir: str | None
    pinned: bool
    class_: TagClass
    sort_order: int
    group: str | None
    created_at: str
    updated_at: str
    open_session_count: int = 0
    session_count: int = 0


class TagPinnedUpdate(BaseModel):
    """Request body for ``PATCH /api/tags/{id}/pinned``.

    ``pinned=true`` pins the tag in the sidebar filter panel;
    ``pinned=false`` unpins it. Mirrors :class:`SessionPinnedUpdate`.
    """

    model_config = ConfigDict(extra="forbid")

    pinned: bool


class TagSortOrderUpdate(BaseModel):
    """Request body for ``PUT /api/tags/sort-order``.

    Re-sequences tags within ``class_`` to match ``ordered_ids``. The
    drag-to-reorder UI on ``/tags`` posts the new order in one call;
    each id at index ``i`` gets ``sort_order = i``. Empty
    ``ordered_ids`` is a no-op.

    The route validates that every id belongs to a tag of ``class_``
    via :func:`bearings.db.tags.update_sort_orders` — a cross-class id
    raises 422.
    """

    model_config = ConfigDict(extra="forbid")

    class_: TagClass
    ordered_ids: list[int] = Field(default_factory=list)


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


class AllMemoriesOut(BaseModel):
    """Response body for ``GET /api/memories`` — global flat-list.

    Each row is a denormalised join of one tag-memory with its parent
    tag so the frontend global-index view can display tag context
    without a second round-trip. ``memory_body_preview`` is the body
    truncated to
    :data:`bearings.config.constants.MEMORY_BODY_PREVIEW_MAX_LENGTH`
    chars; the full body is available via ``GET /api/memories/{id}``.

    The list is sorted by ``(tag_name, memory_title)`` — grouping by
    tag is implied by the alphabetical sort.
    """

    model_config = ConfigDict(extra="forbid")

    tag_id: int
    tag_name: str
    tag_color: str | None
    memory_id: int
    memory_title: str
    memory_body_preview: str
    enabled: bool
    updated_at: str


__all__ = [
    "AllMemoriesOut",
    "TagClass",
    "TagIn",
    "TagMemoryIn",
    "TagMemoryOut",
    "TagOut",
    "TagPinnedUpdate",
    "TagSortOrderUpdate",
]
