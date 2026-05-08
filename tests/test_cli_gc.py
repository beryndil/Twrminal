"""Tests for the ``bearings gc uploads`` subcommand.

Acceptance criteria covered (per feature-10-002 finding):

1. Orphan-on-disk pruned: a file present on disk but absent from the DB
   and older than retention window is deleted.
2. DB-row-missing-file flagged: a DB row whose on-disk body is gone and
   older than the retention window has its row removed from the DB.
3. Dry-run leaves disk untouched: a qualifying orphan is listed but not
   deleted when ``--dry-run`` is supplied.
4. Negative ``--retention-days`` exits 2 with the exact stderr message
   from docs/behavior/bearings-cli.md line 156.
5. No-match path prints the documented footer with ``nothing to prune``
   header and ``retention: N days, scanned <dir>`` second line.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.uploads import store_bytes
from bearings.cli.app import main
from bearings.cli.gc import _human_bytes
from bearings.config.constants import (
    CLI_EXIT_OK,
    CLI_EXIT_OPERATION_FAILURE,
    CLI_EXIT_USAGE_ERROR,
    GC_UPLOADS_DEFAULT_RETENTION_DAYS,
)
from bearings.db.connection import load_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Temporary SQLite DB with the Bearings schema applied."""
    path = tmp_path / "test.db"
    asyncio.run(_bootstrap_db(path))
    return path


async def _bootstrap_db(path: Path) -> None:
    async with aiosqlite.connect(path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await load_schema(conn)


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    """Temporary upload storage root directory."""
    root = tmp_path / "uploads"
    root.mkdir()
    return root


def _make_old_orphan(storage_root: Path, sha256: str, content: bytes, age_days: int) -> Path:
    """Write a content file and backdate its mtime so it appears aged."""
    path = store_bytes(storage_root, sha256, content)
    old_mtime = time.time() - age_days * 86400 - 3600  # extra hour of margin
    import os

    os.utime(path, (old_mtime, old_mtime))
    return path


async def _insert_upload_row(
    db_path: Path,
    *,
    sha256: str,
    filename: str = "test.bin",
    size: int = 100,
    created_at: int | None = None,
) -> None:
    """Insert a row into the uploads table.  ``created_at`` defaults to 60 days ago."""
    if created_at is None:
        created_at = int(time.time()) - 60 * 86400
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(
            "INSERT INTO uploads (sha256, filename, mime_type, size, created_at) "
            "VALUES (?, ?, 'application/octet-stream', ?, ?)",
            (sha256, filename, size, created_at),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# _human_bytes unit
# ---------------------------------------------------------------------------


def test_human_bytes_bytes() -> None:
    assert _human_bytes(0) == "0 B"
    assert _human_bytes(500) == "500 B"
    assert _human_bytes(1023) == "1023 B"


def test_human_bytes_kb() -> None:
    assert _human_bytes(1024) == "1.0 KB"
    assert _human_bytes(1536) == "1.5 KB"


def test_human_bytes_mb() -> None:
    assert _human_bytes(1024 * 1024) == "1.0 MB"


def test_human_bytes_gb() -> None:
    assert _human_bytes(1024 * 1024 * 1024) == "1.0 GB"


# ---------------------------------------------------------------------------
# Acceptance criterion 4: negative --retention-days exits 2
# ---------------------------------------------------------------------------


def test_negative_retention_days_exits_2(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
) -> None:
    """Negative --retention-days → exit 2 with the behavior-doc-mandated message."""
    rc = main(
        [
            "gc",
            "uploads",
            "--retention-days",
            "-1",
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_USAGE_ERROR
    # Exact stderr from docs/behavior/bearings-cli.md line 156.
    assert "bearings gc uploads: --retention-days must be ≥ 0 (got -1)." in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Acceptance criterion 5: no-match prints the documented footer
# ---------------------------------------------------------------------------


def test_no_match_prints_documented_footer(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
) -> None:
    """Empty store → 'nothing to prune' header + retention/scanned footer."""
    rc = main(
        [
            "gc",
            "uploads",
            "--retention-days",
            str(GC_UPLOADS_DEFAULT_RETENTION_DAYS),
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    assert f"nothing to prune under {storage_root}" in captured.out
    assert f"retention: {GC_UPLOADS_DEFAULT_RETENTION_DAYS} days" in captured.out
    assert f"scanned {storage_root}" in captured.out


def test_recent_file_not_pruned(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
) -> None:
    """An orphan file younger than the retention window is not a candidate."""
    sha256 = "a" * 64
    content = b"hello"
    # Write file but do NOT backdate it — it is "new" (< retention-days old).
    store_bytes(storage_root, sha256, content)

    rc = main(
        [
            "gc",
            "uploads",
            "--retention-days",
            "30",
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    assert "nothing to prune" in captured.out


# ---------------------------------------------------------------------------
# Acceptance criterion 1: orphan-on-disk pruned
# ---------------------------------------------------------------------------


def test_orphan_on_disk_pruned(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
) -> None:
    """A file on disk not in the DB and older than retention → deleted."""
    sha256 = "b" * 64
    content = b"orphan content"
    orphan_path = _make_old_orphan(storage_root, sha256, content, age_days=60)
    assert orphan_path.exists()

    rc = main(
        [
            "gc",
            "uploads",
            "--retention-days",
            "30",
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    assert not orphan_path.exists(), "orphan file should have been deleted"
    # Header shows "pruning N subdir(s)"
    assert "pruning 1 subdir(s)" in captured.out
    # Per-item line shows the path
    assert str(orphan_path) in captured.out
    # Footer shows "removed: 1 subdir(s)"
    assert "removed: 1 subdir(s)" in captured.out


# ---------------------------------------------------------------------------
# Acceptance criterion 2: DB-row-missing-file flagged
# ---------------------------------------------------------------------------


def test_db_row_missing_file_removed(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
) -> None:
    """DB row with no on-disk body older than retention → row deleted from DB."""
    sha256 = "c" * 64
    # Insert a DB row but do NOT write any on-disk file.
    asyncio.run(
        _insert_upload_row(
            db_path,
            sha256=sha256,
            size=200,
        )
    )

    rc = main(
        [
            "gc",
            "uploads",
            "--retention-days",
            "30",
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    assert "pruning 1 subdir(s)" in captured.out
    assert "removed: 1 subdir(s)" in captured.out

    # Verify the DB row is gone.
    remaining = asyncio.run(_count_sha256(db_path, sha256))
    assert remaining == 0, "DB row should have been removed"


async def _count_sha256(db_path: Path, sha256: str) -> int:
    async with (
        aiosqlite.connect(db_path) as conn,
        conn.execute("SELECT COUNT(*) FROM uploads WHERE sha256 = ?", (sha256,)) as cur,
    ):
        row = await cur.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Acceptance criterion 3: dry-run leaves disk untouched
# ---------------------------------------------------------------------------


def test_dry_run_leaves_disk_untouched(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
) -> None:
    """--dry-run reports the candidate but does not delete it."""
    sha256 = "d" * 64
    content = b"dry run test"
    orphan_path = _make_old_orphan(storage_root, sha256, content, age_days=60)
    assert orphan_path.exists()

    rc = main(
        [
            "gc",
            "uploads",
            "--retention-days",
            "30",
            "--dry-run",
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    # File must still exist.
    assert orphan_path.exists(), "dry-run must not delete anything"
    # Header says "would prune"
    assert "would prune 1 subdir(s)" in captured.out
    # Footer says "(dry-run, nothing removed)"
    assert "dry-run, nothing removed" in captured.out
    # "removed:" line must NOT appear
    assert "removed:" not in captured.out


# ---------------------------------------------------------------------------
# Partial-failure exit code
# ---------------------------------------------------------------------------


def test_failed_removal_exits_1(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If any orphan file cannot be removed, exit code is 1."""
    sha256 = "e" * 64
    content = b"permission denied test"
    orphan_path = _make_old_orphan(storage_root, sha256, content, age_days=60)

    # Make the file non-deletable by making parent read-only.
    orphan_path.parent.chmod(0o555)
    try:
        rc = main(
            [
                "gc",
                "uploads",
                "--retention-days",
                "30",
                "--db",
                str(db_path),
                "--storage-root",
                str(storage_root),
            ]
        )
        captured = capsys.readouterr()
        assert rc == CLI_EXIT_OPERATION_FAILURE
        # Failure reported on stderr per behavior doc.
        assert "failed to remove" in captured.err
    finally:
        # Restore so tmp_path cleanup can proceed.
        orphan_path.parent.chmod(0o755)


# ---------------------------------------------------------------------------
# Both directions combined
# ---------------------------------------------------------------------------


def test_both_directions_pruned(
    capsys: pytest.CaptureFixture[str],
    db_path: Path,
    storage_root: Path,
) -> None:
    """Forward + reverse pass both contribute to the removal count."""
    # Orphan on disk (not in DB).
    orphan_sha256 = "f" * 64
    orphan_path = _make_old_orphan(storage_root, orphan_sha256, b"orphan", age_days=60)

    # DB row with missing file.
    missing_sha256 = "0" * 64
    asyncio.run(_insert_upload_row(db_path, sha256=missing_sha256, size=50))

    rc = main(
        [
            "gc",
            "uploads",
            "--retention-days",
            "30",
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    assert "pruning 2 subdir(s)" in captured.out
    assert "removed: 2 subdir(s)" in captured.out
    assert not orphan_path.exists()
    assert asyncio.run(_count_sha256(db_path, missing_sha256)) == 0
