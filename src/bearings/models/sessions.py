"""Sessions resource — Pydantic request/response models.

Conventions:

- Request models (``SessionCreate``, ``SessionUpdate``) set
  ``extra="forbid"``. Unknown fields surface as 422 instead of being
  silently dropped — keeps the API contract auditable from logs alone.
- ``working_dir`` must be an absolute path. We don't probe the
  filesystem here (might not exist in the agent's environment); the
  shape check rejects ``./relative`` and ``~/tilde`` paths early.
- ``max_budget`` is optional and, if present, must be > 0. Negative
  budgets are nonsensical; zero would mean "ban every call" which is
  more cleanly modeled with a future "is_paused" flag.
- ``SessionUpdate`` makes every field optional. Fields the client
  doesn't send are left untouched.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SessionKind = Literal["chat", "executor", "orchestrator", "fixer"]

# Constraints reused across Create and Update. Centralized so a tweak
# (e.g. raising title length) lands in one place.
_TITLE_MIN = 1
_TITLE_MAX = 200
_DESCRIPTION_MAX = 8000
_MODEL_MIN = 1
_MODEL_MAX = 100
_WORKING_DIR_MAX = 4096


class SessionCreate(BaseModel):
    """Request body for ``POST /api/sessions``."""

    model_config = ConfigDict(extra="forbid")

    working_dir: Annotated[str, Field(min_length=1, max_length=_WORKING_DIR_MAX)]
    model: Annotated[str, Field(min_length=_MODEL_MIN, max_length=_MODEL_MAX)]
    title: Annotated[str, Field(min_length=_TITLE_MIN, max_length=_TITLE_MAX)]
    description: Annotated[str, Field(max_length=_DESCRIPTION_MAX)] = ""
    max_budget: Annotated[float | None, Field(gt=0)] = None
    kind: SessionKind

    @field_validator("working_dir")
    @classmethod
    def _working_dir_must_be_absolute(cls, value: str) -> str:
        """Reject non-absolute paths.

        We do not call :func:`os.path.isabs` because that varies by
        platform; on Windows ``\\`` is also absolute. Bearings is a
        POSIX-localhost dev tool today; require leading ``/``. When
        cross-platform §12 lands this gets relaxed via OS detection.
        """
        if not value.startswith("/"):
            msg = "working_dir must be an absolute path (start with '/')"
            raise ValueError(msg)
        return value


class SessionUpdate(BaseModel):
    """Request body for ``PATCH /api/sessions/{id}``.

    Every field optional. Unset fields stay as they were. Setting
    ``max_budget`` to ``None`` explicitly is allowed and means "remove
    the cap" — Pydantic distinguishes "field absent" from "field is
    null" via the model's ``model_fields_set`` attribute, which the
    service layer uses to build the SQL UPDATE.
    """

    model_config = ConfigDict(extra="forbid")

    working_dir: Annotated[str | None, Field(min_length=1, max_length=_WORKING_DIR_MAX)] = None
    model: Annotated[str | None, Field(min_length=_MODEL_MIN, max_length=_MODEL_MAX)] = None
    title: Annotated[str | None, Field(min_length=_TITLE_MIN, max_length=_TITLE_MAX)] = None
    description: Annotated[str | None, Field(max_length=_DESCRIPTION_MAX)] = None
    max_budget: Annotated[float | None, Field(gt=0)] = None
    kind: SessionKind | None = None

    @field_validator("working_dir")
    @classmethod
    def _working_dir_must_be_absolute(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("/"):
            msg = "working_dir must be an absolute path (start with '/')"
            raise ValueError(msg)
        return value


class SessionResponse(BaseModel):
    """Response body for any single-session endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    working_dir: str
    model: str
    title: str
    description: str
    max_budget: float | None
    kind: SessionKind
    created_at: str
    updated_at: str


class SessionList(BaseModel):
    """Paginated response for ``GET /api/sessions``.

    Includes the page parameters echoed back so clients don't have to
    track them locally to render "showing X-Y of Z" UI.
    """

    items: list[SessionResponse]
    total: int
    limit: int
    offset: int
