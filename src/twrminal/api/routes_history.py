from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from twrminal.db import store

router = APIRouter(prefix="/history", tags=["history"])


def _validate_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        date_cls.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid date (YYYY-MM-DD)") from e
    return value


async def _dump(request: Request, *, date_from: str | None, date_to: str | None) -> dict[str, Any]:
    conn = request.app.state.db
    return {
        "sessions": await store.list_all_sessions(conn, date_from=date_from, date_to=date_to),
        "messages": await store.list_all_messages(conn, date_from=date_from, date_to=date_to),
        "tool_calls": await store.list_all_tool_calls(conn, date_from=date_from, date_to=date_to),
    }


@router.get("/export")
async def export_history(
    request: Request,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
) -> dict[str, Any]:
    return await _dump(
        request,
        date_from=_validate_date(date_from),
        date_to=_validate_date(date_to),
    )


@router.get("/daily/{date}")
async def daily_log(date: str, request: Request) -> dict[str, Any]:
    validated = _validate_date(date)
    return await _dump(request, date_from=validated, date_to=validated)
