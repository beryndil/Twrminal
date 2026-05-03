"""History search route (item 2.4).

``GET /api/history/search?q=<term>`` performs a case-insensitive substring
search over two data surfaces and returns a merged result list:

1. **Session hits** — sessions whose ``title`` or ``description`` contains
   the query term. Non-closed sessions are ranked ahead of closed ones;
   within each group, most-recently-updated first.
2. **Message hits** — messages whose ``content`` contains the query term,
   joined to their parent session for the ``session_title`` field.
   Most-recently-created first.

Result shape
------------
Each hit is a :class:`~bearings.web.models.history.HistorySearchResult`:

* ``kind`` — ``"session"`` or ``"message"``.
* ``session_id`` / ``session_title`` — parent session identifiers.
* ``message_id`` — ``None`` for session hits; the message row id for
  message hits (the frontend uses this to scroll-to-message via
  ``#msg-{id}`` hash navigation).
* ``snippet`` — up to
  :data:`~bearings.config.constants.HISTORY_SEARCH_SNIPPET_CHARS`
  characters of context around the first match occurrence.

Hard cap
--------
The total result count is bounded by
:data:`~bearings.config.constants.HISTORY_SEARCH_RESULT_CAP`. Session
hits are filled first; the remaining slots go to message hits.

Empty / blank queries return an empty list immediately without touching
the database.

Errors
------
The endpoint returns HTTP 503 when no ``db_connection`` is wired on
``app.state`` (same contract as the sessions / messages routes). It
never 500s on a search error — a logged warning and an empty list are
returned instead so the sidebar degrades gracefully.
"""

from __future__ import annotations

import logging
from typing import Annotated, cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.config.constants import HISTORY_SEARCH_RESULT_CAP, HISTORY_SEARCH_SNIPPET_CHARS
from bearings.web.models.history import HistorySearchResult

logger = logging.getLogger(__name__)

router = APIRouter()

# Session-hit share of the total cap. Allocating a fixed slot count for
# sessions first ensures session-title matches (the most navigable hits)
# always appear when the total cap is reached.
_SESSION_CAP = 20


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _extract_snippet(text: str, query: str, max_chars: int) -> str:
    """Return a snippet of *text* centred around the first match of *query*.

    If the query is not found (case-insensitive search may not match the
    same offset), the leading *max_chars* of the text are returned.
    Ellipsis characters are prepended / appended to signal truncation.
    """
    lower_text = text.lower()
    lower_query = query.lower()
    pos = lower_text.find(lower_query)
    if pos == -1:
        raw = text[:max_chars]
        return raw + ("…" if len(text) > max_chars else "")
    # Centre the snippet on the match with a quarter-window lead-in.
    lead = max_chars // 4
    start = max(0, pos - lead)
    end = min(len(text), start + max_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


async def _search(q: str, db: aiosqlite.Connection) -> list[HistorySearchResult]:
    """Run the two-surface LIKE search and merge results."""
    pattern = f"%{q}%"
    results: list[HistorySearchResult] = []

    # --- Session hits -------------------------------------------------------
    try:
        async with db.execute(
            """
            SELECT id, title, COALESCE(description, '')
            FROM   sessions
            WHERE  title       LIKE :pat ESCAPE '\\'
               OR  description LIKE :pat ESCAPE '\\'
            ORDER BY (closed_at IS NULL) DESC,
                     updated_at          DESC
            LIMIT  :cap
            """,
            {"pat": pattern, "cap": _SESSION_CAP},
        ) as cursor:
            session_rows = await cursor.fetchall()
    except Exception:
        logger.warning("history search: session query failed", exc_info=True)
        session_rows = []

    for sid, title, description in session_rows:
        text = title if q.lower() in title.lower() else description
        results.append(
            HistorySearchResult(
                kind="session",
                session_id=sid,
                session_title=title,
                message_id=None,
                snippet=_extract_snippet(text, q, HISTORY_SEARCH_SNIPPET_CHARS),
            )
        )

    # --- Message hits -------------------------------------------------------
    remaining = HISTORY_SEARCH_RESULT_CAP - len(results)
    if remaining > 0:
        try:
            async with db.execute(
                """
                SELECT m.id, m.session_id, m.content, s.title
                FROM   messages m
                JOIN   sessions s ON s.id = m.session_id
                WHERE  m.content LIKE :pat ESCAPE '\\'
                ORDER BY m.created_at DESC
                LIMIT  :cap
                """,
                {"pat": pattern, "cap": remaining},
            ) as cursor:
                message_rows = await cursor.fetchall()
        except Exception:
            logger.warning("history search: message query failed", exc_info=True)
            message_rows = []

        for mid, session_id, content, session_title in message_rows:
            results.append(
                HistorySearchResult(
                    kind="message",
                    session_id=session_id,
                    session_title=session_title,
                    message_id=mid,
                    snippet=_extract_snippet(content, q, HISTORY_SEARCH_SNIPPET_CHARS),
                )
            )

    return results


@router.get("/api/history/search", response_model=list[HistorySearchResult])
async def search_history(
    request: Request,
    q: Annotated[str, Query(description="Search term (case-insensitive substring match).")],
) -> list[HistorySearchResult]:
    """Search sessions and messages for ``q``.

    Returns up to :data:`~bearings.config.constants.HISTORY_SEARCH_RESULT_CAP`
    results, sessions first. An empty or whitespace-only ``q`` returns ``[]``
    immediately.
    """
    if not q.strip():
        return []
    db = _db(request)
    return await _search(q.strip(), db)


__all__ = ["router"]
