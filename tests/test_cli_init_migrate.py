"""Tests for ``bearings init`` and ``bearings migrate`` subcommands.

Acceptance criteria (F13-rr-12):
1. ``bearings init`` exists and runs successfully.
2. ``bearings init`` is idempotent (second call is a no-op, exits 0).
3. ``bearings migrate`` exists and runs successfully against an initialised DB.
4. ``bearings migrate`` is idempotent (second call is a no-op, exits 0).
5. ``bearings migrate`` exits 1 when the DB does not exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bearings.cli.app import main
from bearings.config.constants import (
    CLI_EXIT_OK,
    CLI_EXIT_OPERATION_FAILURE,
)

# ---------------------------------------------------------------------------
# bearings init
# ---------------------------------------------------------------------------


def test_init_creates_data_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``bearings init`` creates the data-directory tree and initialises the DB."""
    db = tmp_path / "data" / "sessions.db"
    uploads = tmp_path / "data" / "uploads"
    avatars = tmp_path / "data" / "avatars"

    rc = main(
        [
            "init",
            "--db",
            str(db),
            "--uploads-root",
            str(uploads),
            "--avatars-root",
            str(avatars),
        ]
    )

    assert rc == CLI_EXIT_OK
    assert db.exists(), "DB file must be created"
    assert uploads.is_dir(), "uploads dir must be created"
    assert avatars.is_dir(), "avatars dir must be created"
    out = capsys.readouterr().out
    assert "initialised" in out
    assert str(db.parent) in out


def test_init_is_idempotent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running ``bearings init`` twice exits 0 both times (no-op on second call)."""
    db = tmp_path / "data" / "sessions.db"
    uploads = tmp_path / "data" / "uploads"
    avatars = tmp_path / "data" / "avatars"

    argv = [
        "init",
        "--db",
        str(db),
        "--uploads-root",
        str(uploads),
        "--avatars-root",
        str(avatars),
    ]

    rc1 = main(argv)
    assert rc1 == CLI_EXIT_OK

    rc2 = main(argv)
    assert rc2 == CLI_EXIT_OK

    # Second call should report no-op
    out2 = capsys.readouterr().out
    assert "no-op" in out2 or "already present" in out2


def test_init_help_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    """``bearings init --help`` exits 0 and surfaces the path arguments."""
    rc = main(["init", "--help"])
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    assert "--db" in captured.out
    assert "--uploads-root" in captured.out
    assert "--avatars-root" in captured.out


# ---------------------------------------------------------------------------
# bearings migrate
# ---------------------------------------------------------------------------


def test_migrate_on_initialised_db_exits_0(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``bearings migrate`` exits 0 against a DB that was created by ``bearings init``."""
    db = tmp_path / "data" / "sessions.db"
    uploads = tmp_path / "data" / "uploads"
    avatars = tmp_path / "data" / "avatars"

    # Initialise first
    rc_init = main(
        [
            "init",
            "--db",
            str(db),
            "--uploads-root",
            str(uploads),
            "--avatars-root",
            str(avatars),
        ]
    )
    assert rc_init == CLI_EXIT_OK

    capsys.readouterr()  # clear init output

    rc = main(["migrate", "--db", str(db)])
    assert rc == CLI_EXIT_OK
    out = capsys.readouterr().out
    # Fresh DB has all columns already; migrate reports up-to-date.
    assert "up to date" in out


def test_migrate_is_idempotent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running ``bearings migrate`` twice exits 0 both times."""
    db = tmp_path / "data" / "sessions.db"

    main(
        [
            "init",
            "--db",
            str(db),
            "--uploads-root",
            str(tmp_path / "uploads"),
            "--avatars-root",
            str(tmp_path / "avatars"),
        ]
    )
    capsys.readouterr()

    rc1 = main(["migrate", "--db", str(db)])
    assert rc1 == CLI_EXIT_OK

    rc2 = main(["migrate", "--db", str(db)])
    assert rc2 == CLI_EXIT_OK


def test_migrate_missing_db_exits_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``bearings migrate`` exits 1 with a useful stderr message when the DB is absent."""
    absent = tmp_path / "nonexistent.db"

    rc = main(["migrate", "--db", str(absent)])

    assert rc == CLI_EXIT_OPERATION_FAILURE
    err = capsys.readouterr().err
    assert "bearings init" in err  # should hint at the fix


def test_migrate_help_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    """``bearings migrate --help`` exits 0 and surfaces the --db argument."""
    rc = main(["migrate", "--help"])
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_OK
    assert "--db" in captured.out
