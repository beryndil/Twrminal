"""``bearings gc`` subcommand — garbage-collect stale upload artefacts.

Per ``docs/architecture-v1.md`` §1.1.1 the handler stays thin: arg
parsing, a single ``asyncio.run`` call into the domain helper, output
formatting.  No business logic lives here — all of it is in
:func:`_do_gc_uploads`.

Per ``docs/behavior/bearings-cli.md`` §"bearings gc uploads" the
implementation is a **two-direction mark-and-sweep** against the
content-addressed upload store:

* **Forward pass**: walk on-disk shard subdirectories under
  :data:`bearings.config.constants.DEFAULT_UPLOADS_STORAGE_ROOT`; any
  sha256-named file whose digest is absent from the ``uploads`` DB
  table and whose mtime predates the ``--retention-days`` cutoff is an
  *orphan* and will be deleted.
* **Reverse pass**: walk the ``uploads`` DB table; any row whose
  on-disk body is absent and whose ``created_at`` predates the cutoff
  is a *missing-body* entry whose DB row will be removed.

Stdout / stderr / exit-code shapes must match the behavior doc exactly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from bearings.agent.uploads import body_path
from bearings.config.constants import (
    CLI_EXIT_OK,
    CLI_EXIT_OPERATION_FAILURE,
    CLI_EXIT_USAGE_ERROR,
    DEFAULT_DB_PATH,
    DEFAULT_UPLOADS_STORAGE_ROOT,
    GC_UPLOADS_DEFAULT_RETENTION_DAYS,
)
from bearings.db import uploads as db_uploads

# ---------------------------------------------------------------------------
# Internal data shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GcCandidate:
    """One item eligible for garbage collection.

    * ``kind == 'orphan'``: the content file exists on disk but its
      sha256 is absent from the DB (the insert failed or the row was
      deleted without cleaning up the file).
    * ``kind == 'missing'``: a DB row exists but the on-disk body is
      gone (partial or out-of-order deletion).
    """

    path: Path
    """Absolute path of the content file (may not exist for 'missing')."""
    size: int
    """Body size in bytes (from ``stat`` for orphans; from DB for missing)."""
    age_days: int
    """Whole days elapsed since the file mtime or the DB ``created_at``."""
    sha256: str
    """SHA-256 hex digest — the content-file's name on disk."""
    kind: str
    """``'orphan'`` or ``'missing'``."""
    db_id: int | None
    """DB row id; ``None`` for orphan kind, always set for missing kind."""


# ---------------------------------------------------------------------------
# Public subparser registration
# ---------------------------------------------------------------------------


def build_subparser(
    parent: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Wire the ``gc`` subcommand and its ``uploads`` sub-subcommand into ``parent``.

    ``parent`` is the root ``bearings`` subparsers action; this function
    adds ``gc`` and its own internal ``uploads`` sub-subcommand.
    """
    gc = parent.add_parser(
        "gc",
        help="garbage-collect stale on-disk artefacts",
        description=(
            "Two-direction mark-and-sweep against the content-addressed "
            "upload store. "
            "Forward pass: orphan on-disk files not tracked in the DB. "
            "Reverse pass: DB rows whose on-disk bodies are missing. "
            "See docs/behavior/bearings-cli.md §'bearings gc uploads'."
        ),
    )
    gc_sub = gc.add_subparsers(
        dest="gc_subcommand",
        metavar="<gc-subcommand>",
        required=True,
    )
    _build_uploads_parser(gc_sub)
    gc.set_defaults(func=_dispatch_no_subcommand)


def _build_uploads_parser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """``bearings gc uploads`` — prune orphaned and stale upload artefacts."""
    parser = sub.add_parser(
        "uploads",
        help="prune stale or orphaned upload artefacts",
        description=(
            "Sweep the upload store for orphaned on-disk files (not in DB) "
            "and DB rows with missing bodies, subject to the "
            "--retention-days age gate."
        ),
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=GC_UPLOADS_DEFAULT_RETENTION_DAYS,
        dest="retention_days",
        metavar="N",
        help=(
            f"only prune items older than N days "
            f"(default: {GC_UPLOADS_DEFAULT_RETENTION_DAYS}; "
            "0 = prune everything regardless of age)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="report what would be pruned without touching disk or DB",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=DEFAULT_UPLOADS_STORAGE_ROOT,
        dest="storage_root",
        help=f"upload on-disk storage root (default: {DEFAULT_UPLOADS_STORAGE_ROOT})",
    )
    parser.set_defaults(func=_cmd_uploads)


# ---------------------------------------------------------------------------
# Sync handlers
# ---------------------------------------------------------------------------


def _dispatch_no_subcommand(args: argparse.Namespace) -> int:
    """Fallback invoked when ``bearings gc`` receives no sub-subcommand."""
    sys.stderr.write("bearings gc: a sub-subcommand is required (e.g. uploads)\n")
    return CLI_EXIT_USAGE_ERROR


def _cmd_uploads(args: argparse.Namespace) -> int:
    """Thin dispatch for ``bearings gc uploads``.

    Validates ``--retention-days`` synchronously (fast-exit on bad
    input), then delegates all I/O to the async domain helper via
    ``asyncio.run``.
    """
    retention_days: int = args.retention_days
    if retention_days < 0:
        sys.stderr.write(
            f"bearings gc uploads: --retention-days must be ≥ 0 (got {retention_days}).\n"
        )
        return CLI_EXIT_USAGE_ERROR
    return asyncio.run(
        _do_gc_uploads(
            db_path=args.db,
            storage_root=args.storage_root,
            retention_days=retention_days,
            dry_run=args.dry_run,
        )
    )


# ---------------------------------------------------------------------------
# Async domain logic
# ---------------------------------------------------------------------------


async def _do_gc_uploads(
    *,
    db_path: Path,
    storage_root: Path,
    retention_days: int,
    dry_run: bool,
) -> int:
    """Mark-and-sweep the upload store; return the CLI exit code.

    Opens a single DB connection for the full operation (reads then
    optional writes).  All candidate collection happens before any
    output is emitted so the header count and the per-item lines are
    always consistent.
    """
    now = time.time()
    cutoff_ts = now - retention_days * 86400.0

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")

        sha256_in_db: frozenset[str] = await db_uploads.list_all_sha256s(conn)
        all_rows = await db_uploads.list_all_rows_for_gc(conn)

        candidates = _collect_candidates(
            sha256_in_db=sha256_in_db,
            all_rows=all_rows,
            storage_root=storage_root,
            cutoff_ts=cutoff_ts,
            now=now,
        )

        if not candidates:
            sys.stdout.write(
                f"bearings gc uploads: nothing to prune under {storage_root}\n"
                f"  retention: {retention_days} days, scanned {storage_root}\n"
            )
            return CLI_EXIT_OK

        verb = "would prune" if dry_run else "pruning"
        sys.stdout.write(
            f"bearings gc uploads: {verb} {len(candidates)} subdir(s) under {storage_root}\n"
        )
        for c in candidates:
            sys.stdout.write(f"  {c.path}  ({_human_bytes(c.size)}, {c.age_days}d old)\n")

        if dry_run:
            total_size = sum(c.size for c in candidates)
            sys.stdout.write(
                f"  total: {len(candidates)} subdir(s), {_human_bytes(total_size)}"
                " (dry-run, nothing removed)\n"
            )
            return CLI_EXIT_OK

        # Live deletion.
        removed, freed, failed = await _execute_deletions(conn, candidates)

    sys.stdout.write(f"  removed: {removed} subdir(s), freed {_human_bytes(freed)}\n")
    return CLI_EXIT_OPERATION_FAILURE if failed > 0 else CLI_EXIT_OK


def _collect_candidates(
    *,
    sha256_in_db: frozenset[str],
    all_rows: list[db_uploads.UploadRow],
    storage_root: Path,
    cutoff_ts: float,
    now: float,
) -> list[_GcCandidate]:
    """Build the candidate list from the forward and reverse passes.

    Pure computation — no I/O except filesystem stat calls during the
    forward pass.
    """
    candidates: list[_GcCandidate] = []

    # --- Forward pass: on-disk files not tracked in DB -----------------
    if storage_root.exists():
        for shard_dir in sorted(storage_root.iterdir()):
            if not shard_dir.is_dir():
                continue
            for content_file in sorted(shard_dir.iterdir()):
                sha256 = content_file.name
                if sha256 in sha256_in_db:
                    continue  # valid entry — skip
                try:
                    st = content_file.stat()
                except OSError:
                    continue  # race: file already gone
                if st.st_mtime >= cutoff_ts:
                    continue  # too young — outside the retention window
                candidates.append(
                    _GcCandidate(
                        path=content_file,
                        size=st.st_size,
                        age_days=int((now - st.st_mtime) / 86400),
                        sha256=sha256,
                        kind="orphan",
                        db_id=None,
                    )
                )

    # --- Reverse pass: DB rows whose on-disk body is absent ------------
    for row in all_rows:
        if float(row.created_at) >= cutoff_ts:
            continue  # too young
        expected = body_path(storage_root, row.sha256)
        if expected.exists():
            continue  # body is present — not a missing-body case
        candidates.append(
            _GcCandidate(
                path=expected,
                size=row.size,
                age_days=int((now - row.created_at) / 86400),
                sha256=row.sha256,
                kind="missing",
                db_id=row.id,
            )
        )

    return candidates


async def _execute_deletions(
    conn: aiosqlite.Connection,
    candidates: list[_GcCandidate],
) -> tuple[int, int, int]:
    """Execute deletions for all candidates; return (removed, freed, failed).

    * ``removed`` — count of successfully processed items.
    * ``freed`` — bytes actually freed from disk (orphan deletes only).
    * ``failed`` — count of items that could not be removed (I/O errors
      on orphan files; DB errors are not counted as failures — they are
      idempotent by design).
    """
    removed = 0
    freed = 0
    failed = 0

    for c in candidates:
        if c.kind == "orphan":
            try:
                c.path.unlink()
                # Best-effort shard-dir cleanup (mirrors delete_bytes).
                with suppress(OSError):
                    c.path.parent.rmdir()
                removed += 1
                freed += c.size
            except OSError as exc:
                sys.stderr.write(f"failed to remove {c.path}: {exc}\n")
                failed += 1
        else:  # kind == "missing": remove the stale DB row
            db_id = c.db_id
            if db_id is not None:
                await db_uploads.delete(conn, db_id)
            removed += 1
            # No disk space freed for missing-body rows (file is already gone).

    return removed, freed, failed


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _human_bytes(n: int) -> str:
    """Format ``n`` bytes as a human-readable string (e.g. ``'1.2 KB'``)."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


__all__ = ["build_subparser"]
