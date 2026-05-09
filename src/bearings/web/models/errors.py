# mypy: disable-error-code=explicit-any
"""Shared HTTP error response models.

Used in ``responses={...}`` parameters of route decorators so FastAPI
emits typed schemas for error status codes in the OpenAPI specification.
FastAPI's default ``HTTPException`` handler serialises errors as
``{"detail": "<message>"}``; :class:`DetailError` names that shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DetailError(BaseModel):
    """Body returned by ``HTTPException`` raises throughout Bearings routes.

    All ``raise HTTPException(status_code=N, detail="...")`` calls produce
    this JSON shape.  Declaring it explicitly in the ``responses`` map of
    route decorators causes FastAPI to emit the schema in the OpenAPI spec
    rather than leaving the status code undocumented.
    """

    model_config = ConfigDict(extra="forbid")

    detail: str


__all__ = ["DetailError"]
