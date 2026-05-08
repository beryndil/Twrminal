# mypy: disable-error-code=explicit-any
"""Analytics API routes — ``/api/analytics/`` surface (spec §9).

Per ``BEARINGS_ANALYTICS_v1.md`` §9 all analytics endpoints live under
the ``/api/analytics/`` prefix and operate on the five analytics tables
landed in Phase 1 (``turns``, ``plug_blocks``, ``session_plug_blocks``,
``bucket_snapshots``, ``suppressed_warnings``).

Endpoint inventory (§9.1 logging, §9.2 reads, §9.3 actions):

Logging (called by the request pipeline, not the UI):
* ``POST /api/analytics/turns`` — record one Claude API turn.
* ``POST /api/analytics/plug-blocks/batch`` — record plug blocks injected
  into a session at creation time.

Reads (UI polling):
* ``GET /api/analytics/bucket/current`` — latest bucket snapshot.
* ``GET /api/analytics/attribution`` — per-tag token attribution.
* ``GET /api/analytics/redundancy`` — repeated plug blocks.
* ``GET /api/analytics/plug-blocks/{hash}`` — single block detail.
* ``GET /api/analytics/plug-blocks/{hash}/versions`` — version history.
* ``GET /api/analytics/sessions/{session_id}/plug-summary`` — plug
  composition for one session.

Actions:
* ``POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory``
* ``POST /api/analytics/plug-blocks/{hash}/promote-to-on-open``
* ``POST /api/analytics/draft-new-session``
* ``POST /api/analytics/sessions/from-draft``
* ``POST /api/analytics/warnings/suppress``

All handlers pull the ``aiosqlite.Connection`` via :func:`_db` from
:mod:`bearings.web.routes._deps` — HTTP 503 when the DB is absent.
"""

from __future__ import annotations

import asyncio
import difflib
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.config.constants import (
    ANALYTICS_ATTRIBUTION_WINDOW_5H,
    ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY,
    ANALYTICS_REDUNDANCY_DEFAULT_LAST_N,
    ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS,
    ANALYTICS_REDUNDANCY_LAST_N_MAX,
    ANALYTICS_REDUNDANCY_LAST_N_MIN,
    KNOWN_ANALYTICS_ATTRIBUTION_WINDOWS,
    KNOWN_ANALYTICS_BLOCK_TYPES,
    KNOWN_ANALYTICS_WARNING_TYPES,
)
from bearings.db import memories as memories_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db.analytics import (
    compute_tag_attribution,
    get_latest_bucket_snapshot,
    get_plug_block,
    insert_turn,
    is_warning_suppressed,
    list_redundant_plug_blocks,
    list_session_plug_blocks,
    list_versions_for_block,
    record_session_plug_blocks,
    suppress_warning,
    upsert_plug_block,
)
from bearings.web.models.analytics import (
    BucketCurrentOut,
    BucketWindowOut,
    DraftNewSessionIn,
    DraftNewSessionOut,
    PlugBlockOut,
    PlugBlocksBatchIn,
    PlugBlockVersionOut,
    PlugSummaryBlockOut,
    PromoteToOnOpenIn,
    PromoteToOnOpenOut,
    PromoteToTagMemoryIn,
    PromoteToTagMemoryOut,
    RedundancyBlockOut,
    RedundancySessionRef,
    SessionFromDraftIn,
    SessionFromDraftOut,
    SessionPlugSummaryOut,
    SuppressWarningIn,
    TagAttributionOut,
    TurnIn,
)
from bearings.web.routes._deps import _db

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BEARINGS_ON_OPEN_DIR: str = ".bearings"
_BEARINGS_ON_OPEN_FILENAME: str = "on_open.sh"


def _now_ms() -> int:
    """Current unix time in milliseconds."""
    return int(time.time() * 1000)


def _window_cutoff_ms(window: str) -> int:
    """Return the unix-ms cutoff for the given attribution window string.

    ``window`` must be one of :data:`KNOWN_ANALYTICS_ATTRIBUTION_WINDOWS`.
    """
    now_ms = _now_ms()
    if window == ANALYTICS_ATTRIBUTION_WINDOW_5H:
        return now_ms - 5 * 60 * 60 * 1000
    # weekly
    return now_ms - 7 * 24 * 60 * 60 * 1000


def _unified_diff(old: str, new: str) -> str:
    """Return a unified diff string between ``old`` and ``new`` content."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="previous",
            tofile="current",
        )
    )
    return "".join(diff)


# ---------------------------------------------------------------------------
# §9.1 Logging endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/analytics/turns",
    status_code=status.HTTP_201_CREATED,
    operation_id="analytics-log-turn",
)
async def post_turn(request: Request, body: TurnIn) -> dict[str, str]:
    """Record one Claude API turn's token consumption (spec §9.1).

    Uses ``INSERT OR IGNORE`` on ``(session_id, turn_index)`` so duplicate
    deliveries of the same turn are safe no-ops.  Returns
    ``{"status": "ok"}`` on success.
    """
    db = _db(request)
    await insert_turn(
        db,
        session_id=body.session_id,
        turn_index=body.turn_index,
        model=body.model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        cache_read_tokens=body.cache_read_tokens,
        cache_creation_tokens=body.cache_creation_tokens,
    )
    return {"status": "ok"}


@router.post(
    "/api/analytics/plug-blocks/batch",
    status_code=status.HTTP_201_CREATED,
    operation_id="analytics-log-plug-blocks-batch",
)
async def post_plug_blocks_batch(request: Request, body: PlugBlocksBatchIn) -> dict[str, int]:
    """Record the plug blocks injected into a session at creation time (spec §9.1).

    Each block is upserted via ``INSERT OR IGNORE`` on ``hash`` (spec §5.1).
    Then the ``session_plug_blocks`` join rows are written.

    Returns ``{"inserted": N}`` where N is the number of block descriptors
    processed (not necessarily the number of new rows — duplicates are
    silently skipped).
    """
    db = _db(request)
    now = _now_ms()
    hashes: list[str] = []
    for blk in body.blocks:
        if blk.block_type not in KNOWN_ANALYTICS_BLOCK_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"block_type {blk.block_type!r} is not a known analytics block type"),
            )
        await upsert_plug_block(
            db,
            hash=blk.hash,
            block_type=blk.block_type,
            content=blk.content,
            # Token count is approximated from content length on first insert
            # (spec §5.3 — full tokenizer integration is a future Phase).
            token_count=max(1, len(blk.content) // 4),
            token_count_model=body.model,
            source_path=blk.source_path,
            now=now,
        )
        hashes.append(blk.hash)
    if hashes:
        await record_session_plug_blocks(db, body.session_id, hashes, injected_at=now)
    return {"inserted": len(hashes)}


# ---------------------------------------------------------------------------
# §9.2 Read endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/api/analytics/bucket/current",
    response_model=BucketCurrentOut,
    operation_id="analytics-get-bucket-current",
)
async def get_bucket_current(request: Request) -> BucketCurrentOut:
    """Return the most recent ``/usage`` poll snapshot (spec §9.2).

    When no snapshot exists yet (the poller hasn't run), ``five_hour``
    and ``weekly`` are ``None`` and ``as_of`` is the current server time.
    """
    db = _db(request)
    snap = await get_latest_bucket_snapshot(db)
    if snap is None:
        return BucketCurrentOut(five_hour=None, weekly=None, as_of=_now_ms())

    five_hour: BucketWindowOut | None = None
    if snap.five_hour_used is not None and snap.five_hour_limit is not None:
        pct = (snap.five_hour_used / snap.five_hour_limit * 100.0) if snap.five_hour_limit else 0.0
        five_hour = BucketWindowOut(
            used=snap.five_hour_used,
            limit=snap.five_hour_limit,
            percent=round(pct, 2),
        )

    weekly: BucketWindowOut | None = None
    if snap.weekly_used is not None and snap.weekly_limit is not None:
        pct = (snap.weekly_used / snap.weekly_limit * 100.0) if snap.weekly_limit else 0.0
        weekly = BucketWindowOut(
            used=snap.weekly_used,
            limit=snap.weekly_limit,
            percent=round(pct, 2),
        )

    return BucketCurrentOut(five_hour=five_hour, weekly=weekly, as_of=snap.timestamp)


@router.get(
    "/api/analytics/attribution",
    response_model=list[TagAttributionOut],
    operation_id="analytics-get-attribution",
)
async def get_attribution(
    request: Request,
    window: str = Query(
        default=ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY,
        description=f"One of: {sorted(KNOWN_ANALYTICS_ATTRIBUTION_WINDOWS)}",
    ),
    group_by: str = Query(
        default="tag",
        description="Grouping dimension — currently only 'tag' is supported",
    ),
) -> list[TagAttributionOut]:
    """Per-tag token attribution for the selected time window (spec §9.2).

    ``window`` is ``5h`` (rolling 5-hour) or ``weekly`` (rolling 7-day).
    ``group_by`` must be ``tag``; other values return 422.

    Per spec §3.2 the ``tokens_by_model`` dict must not be summed across
    models without normalisation.  ``share_total`` is computed after
    grouping by model so the fraction is meaningful.
    """
    if window not in KNOWN_ANALYTICS_ATTRIBUTION_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"window {window!r} not in {sorted(KNOWN_ANALYTICS_ATTRIBUTION_WINDOWS)}",
        )
    if group_by != "tag":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="group_by must be 'tag'",
        )
    db = _db(request)
    cutoff_ms = _window_cutoff_ms(window)
    rows = await compute_tag_attribution(db, cutoff_ms=cutoff_ms)

    # Aggregate per-tag, collapsing the per-model rows into tokens_by_model dict.
    tag_totals: dict[str, dict[str, int]] = {}
    grand_total = 0
    for row in rows:
        tag = str(row["tag"])
        model = str(row["model"])
        tokens = int(row["tokens"])
        grand_total = int(row["grand_total"])
        if tag not in tag_totals:
            tag_totals[tag] = {}
        tag_totals[tag][model] = tag_totals[tag].get(model, 0) + tokens

    window_minutes = (5 * 60) if window == ANALYTICS_ATTRIBUTION_WINDOW_5H else (7 * 24 * 60)
    out: list[TagAttributionOut] = []
    for tag, by_model in sorted(tag_totals.items()):
        tag_total = sum(by_model.values())
        share = (tag_total / grand_total) if grand_total > 0 else 0.0
        burn = tag_total / window_minutes if window_minutes > 0 else 0.0
        out.append(
            TagAttributionOut(
                tag=tag,
                tokens_by_model=by_model,
                share_total=round(share, 6),
                burn_rate_per_min=round(burn, 4),
            )
        )
    return out


@router.get(
    "/api/analytics/redundancy",
    response_model=list[RedundancyBlockOut],
    operation_id="analytics-get-redundancy",
)
async def get_redundancy(
    request: Request,
    tag: str | None = Query(
        default=None,
        description="Filter to sessions with this tag name",
    ),
    last_n: int = Query(
        default=ANALYTICS_REDUNDANCY_DEFAULT_LAST_N,
        ge=ANALYTICS_REDUNDANCY_LAST_N_MIN,
        le=ANALYTICS_REDUNDANCY_LAST_N_MAX,
        description=(
            f"Sample the last N sessions "
            f"({ANALYTICS_REDUNDANCY_LAST_N_MIN}-{ANALYTICS_REDUNDANCY_LAST_N_MAX})"
        ),
    ),
    min_repeats: int = Query(
        default=ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS,
        ge=2,
        description="Minimum number of sessions a block must appear in",
    ),
    block_types: str | None = Query(
        default=None,
        description="Comma-separated block_type filter (e.g. 'claude_md,tag_memory')",
    ),
) -> list[RedundancyBlockOut]:
    """Plug blocks repeated across sessions — ranked by total token cost (spec §9.2).

    Blocks returned have appeared in at least ``min_repeats`` of the
    ``last_n`` most-recent sessions (optionally scoped to a tag).

    ``block_types`` is a comma-separated filter; absent means all types.
    """
    db = _db(request)
    tag_id: int | None = None
    if tag is not None:
        tag_row = await tags_db.get_by_name(db, tag)
        if tag_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"tag {tag!r} not found",
            )
        tag_id = tag_row.id

    parsed_types: list[str] | None = None
    if block_types is not None:
        parsed_types = [t.strip() for t in block_types.split(",") if t.strip()]
        unknown = [t for t in parsed_types if t not in KNOWN_ANALYTICS_BLOCK_TYPES]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unknown block_types: {unknown}",
            )

    raw = await list_redundant_plug_blocks(
        db,
        last_n=last_n,
        min_repeats=min_repeats,
        tag_id=tag_id,
        block_types=parsed_types,
    )

    return [
        RedundancyBlockOut(
            hash=str(r["hash"]),
            block_type=str(r["block_type"]),
            token_count=int(r["token_count"]),
            token_count_model=str(r["token_count_model"]),
            repeat_count=int(r["repeat_count"]),
            total_cost_tokens=int(r["total_cost_tokens"]),
            source_path=r["source_path"],
            sessions=[
                RedundancySessionRef(
                    id=str(s["id"]),
                    title=str(s["title"]),
                    timestamp=int(s["timestamp"]),
                    tags=[str(t) for t in s["tags"]],
                )
                for s in r["sessions"]
            ],
        )
        for r in raw
    ]


@router.get(
    "/api/analytics/plug-blocks/{hash}",
    response_model=PlugBlockOut,
    operation_id="analytics-get-plug-block",
)
async def get_plug_block_detail(request: Request, hash: str) -> PlugBlockOut:
    """Return full detail for one plug block by sha256 hash (spec §9.2)."""
    db = _db(request)
    block = await get_plug_block(db, hash)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"plug_block {hash!r} not found",
        )
    return PlugBlockOut(
        id=block.id,
        hash=block.hash,
        block_type=block.block_type,
        content=block.content,
        token_count=block.token_count,
        token_count_model=block.token_count_model,
        first_seen=block.first_seen,
        last_seen=block.last_seen,
        source_path=block.source_path,
    )


@router.get(
    "/api/analytics/plug-blocks/{hash}/versions",
    response_model=list[PlugBlockVersionOut],
    operation_id="analytics-get-plug-block-versions",
)
async def get_plug_block_versions(request: Request, hash: str) -> list[PlugBlockVersionOut]:
    """Version history for a plug block, identified by its sha256 hash (spec §9.2).

    Returns all blocks sharing the same ``source_path`` and ``block_type``
    as ``hash``, ordered oldest-first.  Each entry carries a ``unified_diff``
    from the prior version (``None`` for the first entry).

    404 when ``hash`` does not exist.  Single-element list when the block
    has no ``source_path`` (no versioning information available).
    """
    db = _db(request)
    versions = await list_versions_for_block(db, hash)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"plug_block {hash!r} not found",
        )
    out: list[PlugBlockVersionOut] = []
    for i, v in enumerate(versions):
        if i == 0:
            diff: str | None = None
        else:
            diff = _unified_diff(versions[i - 1].content, v.content) or None
        out.append(
            PlugBlockVersionOut(
                hash=v.hash,
                first_seen=v.first_seen,
                last_seen=v.last_seen,
                token_count=v.token_count,
                unified_diff=diff,
            )
        )
    return out


@router.get(
    "/api/analytics/sessions/{session_id}/plug-summary",
    response_model=SessionPlugSummaryOut,
    operation_id="analytics-get-session-plug-summary",
)
async def get_session_plug_summary(request: Request, session_id: str) -> SessionPlugSummaryOut:
    """Plug composition summary for one session (spec §9.2).

    Returns total tokens, status (green / yellow / red), and the
    per-block breakdown.  404 when the session does not exist.
    """
    db = _db(request)
    session = await sessions_db.get(db, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id!r} not found",
        )
    links = await list_session_plug_blocks(db, session_id)
    blocks_out: list[PlugSummaryBlockOut] = []
    total = 0
    for link in links:
        block = await get_plug_block(db, link.block_hash)
        if block is None:
            continue
        blocks_out.append(
            PlugSummaryBlockOut(
                hash=block.hash,
                block_type=block.block_type,
                tokens=block.token_count,
            )
        )
        total += block.token_count
    return SessionPlugSummaryOut(
        total_tokens=total,
        status=SessionPlugSummaryOut.compute_status(total),
        blocks=blocks_out,
    )


# ---------------------------------------------------------------------------
# §9.3 Action endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/analytics/plug-blocks/{hash}/promote-to-tag-memory",
    response_model=PromoteToTagMemoryOut,
    operation_id="analytics-promote-plug-block-to-tag-memory",
)
async def create_tag_memory_from_plug_block(
    request: Request,
    hash: str,
    body: PromoteToTagMemoryIn,
) -> PromoteToTagMemoryOut:
    """Create a tag memory from a plug block's content (spec §9.3).

    Looks up ``hash`` (404 if missing), then looks up the tag by name
    (404 if missing).  Creates a ``tag_memories`` row with
    ``body.memory_content`` as the body.

    ``auto_apply_to_next_session`` is recorded in the response for
    the UI to act on — the backend does not yet implement the
    automatic-tag-apply hook (that is a session-creation hook, Phase 5+).
    """
    db = _db(request)
    block = await get_plug_block(db, hash)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"plug_block {hash!r} not found",
        )
    tag = await tags_db.get_by_name(db, body.tag)
    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"tag {body.tag!r} not found",
        )
    title = f"Promoted from plug block {hash[:8]}"
    # Idempotency: if a memory with this exact title already exists for
    # the tag, return it rather than creating a duplicate (spec §11).
    existing = await memories_db.list_for_tag(db, tag.id)
    for mem in existing:
        if mem.title == title:
            return PromoteToTagMemoryOut(memory_id=mem.id, tag=tag.name)
    memory = await memories_db.create(
        db,
        tag_id=tag.id,
        title=title,
        body=body.memory_content,
        enabled=True,
    )
    return PromoteToTagMemoryOut(memory_id=memory.id, tag=tag.name)


@router.post(
    "/api/analytics/plug-blocks/{hash}/promote-to-on-open",
    response_model=PromoteToOnOpenOut,
    operation_id="analytics-promote-plug-block-to-on-open",
)
async def create_on_open_from_plug_block(
    request: Request,
    hash: str,
    body: PromoteToOnOpenIn,
) -> PromoteToOnOpenOut:
    """Write a shell snippet into ``<working_directory>/.bearings/on_open.sh`` (spec §9.3).

    Creates ``.bearings/`` if it doesn't exist.  Appends the snippet to
    any existing ``on_open.sh`` (newline-separated) so multiple promotes
    accumulate rather than overwrite each other.

    404 when ``hash`` is unknown.
    422 when ``working_directory`` is not an existing directory on disk.
    """
    db = _db(request)
    block = await get_plug_block(db, hash)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"plug_block {hash!r} not found",
        )
    work_dir = Path(body.working_directory)
    is_dir = await asyncio.to_thread(work_dir.is_dir)
    if not is_dir:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"working_directory {body.working_directory!r} is not an existing directory",
        )
    bearings_dir = work_dir / _BEARINGS_ON_OPEN_DIR
    await asyncio.to_thread(bearings_dir.mkdir, parents=True, exist_ok=True)
    on_open_path = bearings_dir / _BEARINGS_ON_OPEN_FILENAME
    snippet = body.snippet
    if not snippet.endswith("\n"):
        snippet += "\n"

    def _write_snippet_idempotent() -> None:
        # Idempotency: read existing content and skip the write if the
        # snippet is already present (spec §11).
        existing = ""
        if on_open_path.exists():
            existing = on_open_path.read_text(encoding="utf-8")
        if snippet not in existing:
            with on_open_path.open("a", encoding="utf-8") as fh:
                fh.write(snippet)

    await asyncio.to_thread(_write_snippet_idempotent)
    return PromoteToOnOpenOut(on_open_sh_path=str(on_open_path))


@router.post(
    "/api/analytics/draft-new-session",
    response_model=DraftNewSessionOut,
    operation_id="analytics-draft-new-session",
)
async def preview_session_draft(
    request: Request,
    body: DraftNewSessionIn,
) -> DraftNewSessionOut:
    """Generate a draft plug for a new session continuing from a source session (spec §9.3).

    Pulls the source session's title, description, and tag set to build a
    compact plug template.  Full LLM-generated drafts require agent
    infrastructure wired in a later phase; this implementation returns a
    deterministic template so the route surface is complete.

    404 when ``source_session_id`` does not exist.
    """
    db = _db(request)
    source = await sessions_db.get(db, body.source_session_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {body.source_session_id!r} not found",
        )
    tag_names = body.carry_tags or []
    tag_line = f"Tags: {', '.join(tag_names)}" if tag_names else ""
    desc_line = f"Context: {source.description}" if source.description else ""
    parts = [
        f"Continuing from: {source.title}",
        desc_line,
        tag_line,
        "",
        "# Session context",
        "Pick up where the prior session left off.",
        "Keep this plug under 500 tokens.",
    ]
    draft = "\n".join(p for p in parts if p is not None)
    estimated = max(1, len(draft) // 4)
    return DraftNewSessionOut(
        draft_plug=draft,
        estimated_tokens=estimated,
        draft_cost_tokens={"input": 0, "output": 0},
    )


@router.post(
    "/api/analytics/sessions/from-draft",
    response_model=SessionFromDraftOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="analytics-create-session-from-draft",
)
async def create_session_from_draft(
    request: Request,
    body: SessionFromDraftIn,
) -> SessionFromDraftOut:
    """Create a new chat session from a user-reviewed plug draft (spec §9.3).

    ``draft_plug`` becomes the ``session_instructions`` on the new session.
    ``tags`` must reference existing tag names — 404 if any are absent.
    ``working_directory`` must be a non-empty path (it is stored as-is; no
    filesystem check here, matching ``POST /api/sessions`` behaviour).
    """
    db = _db(request)
    tag_ids: list[int] = []
    for tag_name in body.tags:
        tag = await tags_db.get_by_name(db, tag_name)
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"tag {tag_name!r} not found",
            )
        tag_ids.append(tag.id)
    new_session = await sessions_db.create(
        db,
        kind="chat",
        title="New session from draft plug",
        working_dir=body.working_directory,
        model="sonnet",
        session_instructions=body.draft_plug,
    )
    if tag_ids:
        await tags_db.set_for_session(
            db,
            session_id=new_session.id,
            tag_ids=tuple(tag_ids),
        )
        await db.commit()
    return SessionFromDraftOut(session_id=new_session.id)


@router.post(
    "/api/analytics/warnings/suppress",
    operation_id="analytics-suppress-warning",
)
async def create_warning_suppression(
    request: Request,
    body: SuppressWarningIn,
) -> dict[str, str]:
    """Record that the user dismissed a plug-length warning (spec §9.3).

    Idempotent — double-clicking "don't show again" is a safe no-op.
    Returns ``{"status": "ok"}`` on success.

    422 when ``warning_type`` is not a known analytics warning type.
    """
    if body.warning_type not in KNOWN_ANALYTICS_WARNING_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"warning_type {body.warning_type!r} not in {sorted(KNOWN_ANALYTICS_WARNING_TYPES)}"
            ),
        )
    db = _db(request)
    already = await is_warning_suppressed(db, body.block_hash, body.warning_type)
    if not already:
        await suppress_warning(db, block_hash=body.block_hash, warning_type=body.warning_type)
    return {"status": "ok"}


__all__ = ["router"]
