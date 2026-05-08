"""Usage endpoints (spec §9 usage surface).

Endpoints (spec §9 verbatim):

* ``GET /api/usage/by_model?period=week`` — per-model token totals.
* ``GET /api/usage/by_tag?period=week`` — per-tag rollup.
* ``GET /api/usage/override_rates?days=14`` — for "Review:" rules.

The aggregations slice the ``messages`` table on the per-message
routing/usage columns landed in spec §5 (item 1.9 wires the writes;
until then the queries return zero-row aggregates, which is the
correct response for a fresh app).

``period`` accepts ``week`` (the spec-named default) and ``day``;
the alphabet is enforced via :data:`_KNOWN_USAGE_PERIODS` so a typo
fails 422 at the wire boundary.
"""

from __future__ import annotations

import time
from typing import Final

from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.agent.override_aggregator import OverrideAggregator
from bearings.config.constants import OVERRIDE_RATE_WINDOW_DAYS
from bearings.web.models.usage import (
    OverrideRateOut,
    UsageByModelRow,
    UsageByTagRow,
)
from bearings.web.routes._deps import _db

router = APIRouter()


_KNOWN_USAGE_PERIODS: Final[frozenset[str]] = frozenset({"day", "week"})


def _period_to_seconds(period: str) -> int:
    """Translate the spec-named period to a unix-seconds window."""
    if period == "day":
        return 86_400
    if period == "week":
        return 7 * 86_400
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"period {period!r} not in {sorted(_KNOWN_USAGE_PERIODS)}",
    )


@router.get(
    "/api/usage/by_model",
    response_model=list[UsageByModelRow],
    operation_id="get-usage-by-model",
)
async def by_model(
    request: Request,
    period: str = Query(default="week"),
) -> list[UsageByModelRow]:
    """Token totals per model, split by executor/advisor role.

    Aggregation: walks ``messages`` rows whose ``executor_model`` is
    set, summing the per-model token columns. Two pseudo-rows per
    model: one for the executor role, one for the advisor (when the
    advisor was used on that turn). ``sessions`` is ``COUNT(DISTINCT
    session_id)``.
    """
    if period not in _KNOWN_USAGE_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"period {period!r} not in {sorted(_KNOWN_USAGE_PERIODS)}",
        )
    cutoff_unix = int(time.time()) - _period_to_seconds(period)
    db = _db(request)
    out: list[UsageByModelRow] = []
    # Executor totals.
    cursor = await db.execute(
        "SELECT executor_model, "
        "       COALESCE(SUM(executor_input_tokens), 0), "
        "       COALESCE(SUM(executor_output_tokens), 0), "
        "       COALESCE(SUM(advisor_calls_count), 0), "
        "       COALESCE(SUM(cache_read_tokens), 0), "
        "       COUNT(DISTINCT session_id) "
        "FROM messages "
        "WHERE executor_model IS NOT NULL "
        "AND CAST(strftime('%s', created_at) AS INTEGER) >= ? "
        "GROUP BY executor_model ORDER BY executor_model ASC",
        (str(cutoff_unix),),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    for row in rows:
        out.append(
            UsageByModelRow(
                model=str(row[0]),
                role="executor",
                input_tokens=int(str(row[1])),
                output_tokens=int(str(row[2])),
                advisor_calls=int(str(row[3])),
                cache_read_tokens=int(str(row[4])),
                sessions=int(str(row[5])),
            )
        )
    # Advisor totals.
    cursor = await db.execute(
        "SELECT advisor_model, "
        "       COALESCE(SUM(advisor_input_tokens), 0), "
        "       COALESCE(SUM(advisor_output_tokens), 0), "
        "       COALESCE(SUM(advisor_calls_count), 0), "
        "       0, "
        "       COUNT(DISTINCT session_id) "
        "FROM messages "
        "WHERE advisor_model IS NOT NULL "
        "AND CAST(strftime('%s', created_at) AS INTEGER) >= ? "
        "GROUP BY advisor_model ORDER BY advisor_model ASC",
        (str(cutoff_unix),),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    for row in rows:
        out.append(
            UsageByModelRow(
                model=str(row[0]),
                role="advisor",
                input_tokens=int(str(row[1])),
                output_tokens=int(str(row[2])),
                advisor_calls=int(str(row[3])),
                cache_read_tokens=0,
                sessions=int(str(row[5])),
            )
        )
    return out


@router.get(
    "/api/usage/by_tag",
    response_model=list[UsageByTagRow],
    operation_id="get-usage-by-tag",
)
async def by_tag(
    request: Request,
    period: str = Query(default="week"),
) -> list[UsageByTagRow]:
    """Token totals per tag, joining ``session_tags`` to the messages.

    A session may carry multiple tags; this endpoint returns one row
    per (session, tag) pair, summed. The frontend then renders one row
    per tag with the per-tag total — multiple tags on the same
    session count toward each tag, which matches the user-mental
    model ("how much did I spend on architecture sessions?").
    """
    if period not in _KNOWN_USAGE_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"period {period!r} not in {sorted(_KNOWN_USAGE_PERIODS)}",
        )
    cutoff_unix = int(time.time()) - _period_to_seconds(period)
    db = _db(request)
    cursor = await db.execute(
        "SELECT t.id, t.name, "
        "       COALESCE(SUM(m.executor_input_tokens), 0), "
        "       COALESCE(SUM(m.executor_output_tokens), 0), "
        "       COALESCE(SUM(m.advisor_input_tokens), 0), "
        "       COALESCE(SUM(m.advisor_output_tokens), 0), "
        "       COALESCE(SUM(m.advisor_calls_count), 0), "
        "       COUNT(DISTINCT m.session_id) "
        "FROM tags t "
        "LEFT JOIN session_tags st ON st.tag_id = t.id "
        "LEFT JOIN messages m ON m.session_id = st.session_id "
        "AND CAST(strftime('%s', m.created_at) AS INTEGER) >= ? "
        "AND (m.executor_model IS NOT NULL OR m.advisor_model IS NOT NULL) "
        "GROUP BY t.id, t.name ORDER BY t.name ASC",
        (str(cutoff_unix),),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [
        UsageByTagRow(
            tag_id=int(str(row[0])),
            tag_name=str(row[1]),
            executor_input_tokens=int(str(row[2])),
            executor_output_tokens=int(str(row[3])),
            advisor_input_tokens=int(str(row[4])),
            advisor_output_tokens=int(str(row[5])),
            advisor_calls=int(str(row[6])),
            sessions=int(str(row[7])),
        )
        for row in rows
    ]


@router.get(
    "/api/usage/override_rates",
    response_model=list[OverrideRateOut],
    operation_id="get-usage-override-rates",
)
async def override_rates(
    request: Request,
    days: int = Query(
        default=OVERRIDE_RATE_WINDOW_DAYS,
        gt=0,
        le=365,
        description="rolling window in days (1-365)",
    ),
) -> list[OverrideRateOut]:
    """Per-rule override rates for the last ``days`` days (spec §9)."""
    db = _db(request)
    aggregator = OverrideAggregator(db, window_days=days)
    rates = await aggregator.compute()
    return [
        OverrideRateOut(
            rule_kind=r.rule_kind,
            rule_id=r.rule_id,
            fired_count=r.fired_count,
            overridden_count=r.overridden_count,
            rate=r.rate,
            review=r.review,
        )
        for r in rates
    ]


__all__ = ["router"]
