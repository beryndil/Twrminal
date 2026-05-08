"""Directory-context history.jsonl reader (arch §1.1.5).

``GET /api/history/jsonl?directory=<path>`` reads the ``history.jsonl``
file from the ``.bearings/`` sub-directory of *directory* and returns
its entries as a JSON array.

Result shape
------------
Each entry is a :class:`~bearings.web.models.history.DirectoryHistoryEntry`:

* ``event`` — event kind string (e.g. ``"context_start"``).
* ``session_id`` — the session that triggered the event, or ``None``.
* ``timestamp`` — ISO-8601 timestamp.

Unknown fields from future event types are silently dropped so older
clients remain forward-compatible.

Graceful degradation
--------------------
Returns an empty list when the file does not exist (directory not yet
onboarded) rather than raising 404, so callers can treat the response
uniformly without special-casing the first-time case.

The optional ``limit`` parameter (default:
:data:`~bearings.config.constants.BEARINGS_DIR_HISTORY_CAP`) controls
how many of the most-recent entries are returned.  Entries are ordered
oldest-first in the file; the *limit* newest are selected before
returning.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query

from bearings.bearings_dir import io as bdir_io
from bearings.config.constants import (
    BEARINGS_DIR_HISTORY_CAP,
    BEARINGS_DIR_HISTORY_FILENAME,
    BEARINGS_DIR_SUBDIR,
)
from bearings.web.models.history import DirectoryHistoryEntry

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/api/history/jsonl",
    response_model=list[DirectoryHistoryEntry],
    operation_id="get-directory-history",
    summary="Get .bearings/history.jsonl entries for a directory",
)
async def get_directory_history(
    directory: Annotated[
        str,
        Query(description="Absolute path to the project directory whose history to read."),
    ],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=BEARINGS_DIR_HISTORY_CAP,
            description=(
                "Maximum number of entries to return (most-recent first within the cap). "
                f"Defaults to {BEARINGS_DIR_HISTORY_CAP}."
            ),
        ),
    ] = BEARINGS_DIR_HISTORY_CAP,
) -> list[DirectoryHistoryEntry]:
    """Return ``history.jsonl`` entries for *directory*.

    Delegates to :func:`bearings.bearings_dir.io.read_jsonl`.  Returns an
    empty list when the file does not exist — directory not yet onboarded.
    Malformed individual entries are skipped rather than raising so a single
    corrupted line never breaks the whole read.
    """
    history_path = Path(directory) / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_HISTORY_FILENAME
    raw_entries = bdir_io.read_jsonl(history_path)
    # Apply limit against the tail (most-recent entries).
    sliced = raw_entries[-limit:]
    results: list[DirectoryHistoryEntry] = []
    for entry in sliced:
        try:
            results.append(DirectoryHistoryEntry.model_validate(entry))
        except Exception:
            logger.debug("read_directory_history: skipping malformed entry %r", entry)
    return results


__all__ = ["router"]
