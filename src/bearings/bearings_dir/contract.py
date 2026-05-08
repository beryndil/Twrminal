# mypy: disable-error-code=explicit-any
"""Pydantic models for ``.bearings/`` TOML schemas (arch §1.1.6).

Covers ``manifest.toml``, ``state.toml``, and ``pending.toml``.  Each
model carries a ``schema_version`` field that the validation helpers check
against :data:`bearings.config.constants.BEARINGS_DIR_SCHEMA_VERSION`; a
mismatch raises :exc:`ValueError` with a human-readable message so the
caller (typically ``lifecycle.py``) can decide whether to re-run
onboarding rather than crash.

Pydantic carve-out
------------------
The ``# mypy: disable-error-code=explicit-any`` pragma is needed because
the validation helpers below accept ``dict[str, Any]`` — the type that
``tomllib.load()`` returns — and Pydantic's ``model_validate`` is typed
to accept ``Any``.  The carve-out is restricted to this file; the pragma
does not propagate to callers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bearings.config.constants import BEARINGS_DIR_SCHEMA_VERSION

# Re-export the schema version so contract users don't have to import from
# two modules.
SCHEMA_VERSION: Final[int] = BEARINGS_DIR_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# manifest.toml
# ---------------------------------------------------------------------------


class ManifestModel(BaseModel):
    """Schema for ``.bearings/manifest.toml``.

    Written by :func:`~bearings.bearings_dir.onboarding.dir_init_body`
    and read by :func:`~bearings.bearings_dir.lifecycle.read_brief`.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: int = SCHEMA_VERSION
    directory: str
    primary_marker: str
    created_at: datetime
    brief: str

    @model_validator(mode="after")
    def _check_schema_version(self) -> ManifestModel:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"manifest.toml schema_version {self.schema_version!r} "
                f"does not match current version {SCHEMA_VERSION!r}; "
                "re-run onboarding to refresh."
            )
        return self

    @model_validator(mode="after")
    def _check_nonempty(self) -> ManifestModel:
        if not self.directory:
            raise ValueError("ManifestModel.directory must be non-empty")
        if not self.primary_marker:
            raise ValueError("ManifestModel.primary_marker must be non-empty")
        if not self.brief:
            raise ValueError("ManifestModel.brief must be non-empty")
        return self


# ---------------------------------------------------------------------------
# state.toml
# ---------------------------------------------------------------------------


class StateModel(BaseModel):
    """Schema for ``.bearings/state.toml``.

    Updated by
    :func:`~bearings.bearings_dir.lifecycle.note_directory_context_start`
    on each session open.  All fields except ``schema_version`` are
    optional because a freshly initialised state has no session history.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: int = SCHEMA_VERSION
    last_session_id: str | None = None
    last_seen_at: datetime | None = None

    @model_validator(mode="after")
    def _check_schema_version(self) -> StateModel:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"state.toml schema_version {self.schema_version!r} "
                f"does not match current version {SCHEMA_VERSION!r}; "
                "re-run onboarding to refresh."
            )
        return self


# ---------------------------------------------------------------------------
# pending.toml
# ---------------------------------------------------------------------------


class PendingOpModel(BaseModel):
    """A single pending-operation entry in ``[ops.<name>]``.

    The two known fields are ``description`` and ``started_at``; any
    additional fields that a future writer adds are preserved via
    ``extra="allow"`` so old readers don't strip newer data.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    description: str
    started_at: str  # ISO 8601 string (TOML string, not native datetime)

    @model_validator(mode="after")
    def _check_description(self) -> PendingOpModel:
        if not self.description:
            raise ValueError("PendingOpModel.description must be non-empty")
        return self


class PendingModel(BaseModel):
    """Schema for ``.bearings/pending.toml``."""

    model_config = ConfigDict(frozen=True)

    ops: dict[str, PendingOpModel] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_schema_version(data: dict[str, Any], current: int = SCHEMA_VERSION) -> None:
    """Raise :exc:`ValueError` when ``data["schema_version"]`` mismatches *current*.

    Callers that read raw TOML dicts should call this before passing the dict
    to a model validator so the error message names the file type.  The
    per-model ``@model_validator`` also checks, so this is defence-in-depth
    for callers that bypass the model layer.
    """
    version = data.get("schema_version")
    if version != current:
        raise ValueError(f"schema_version {version!r} does not match expected {current!r}")


def load_manifest(data: dict[str, Any]) -> ManifestModel:
    """Parse and validate a raw TOML dict as :class:`ManifestModel`.

    Raises :exc:`pydantic.ValidationError` on field errors and
    :exc:`ValueError` on schema-version mismatch (surfaced through the
    ``@model_validator``).
    """
    return ManifestModel.model_validate(data)


def load_state(data: dict[str, Any]) -> StateModel:
    """Parse and validate a raw TOML dict as :class:`StateModel`."""
    return StateModel.model_validate(data)


def load_pending(data: dict[str, Any]) -> PendingModel:
    """Parse and validate a raw TOML dict as :class:`PendingModel`."""
    return PendingModel.model_validate(data)


__all__ = [
    "SCHEMA_VERSION",
    "ManifestModel",
    "PendingModel",
    "PendingOpModel",
    "StateModel",
    "load_manifest",
    "load_pending",
    "load_state",
    "validate_schema_version",
]
