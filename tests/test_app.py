"""Tests for bearings.app and the ``python -m bearings`` entry."""

from pathlib import Path

import pytest

from bearings.app import _bootstrap, main
from bearings.config import Settings


def test_main_runs_without_error() -> None:
    """main() bootstraps the app end-to-end without raising.

    Covers config + logging + exception handler + DB migrations.
    The data_dir is redirected by the autouse ``_isolate_data_dir``
    fixture, so the SQLite file lands in a per-test tmp dir and the
    real ``~/.local/share/bearings`` is never touched.
    """
    main()


async def test_bootstrap_creates_db_file(tmp_path: Path) -> None:
    """Running the bootstrap creates the SQLite file under data_dir."""
    await _bootstrap()
    expected = Path(Settings().db_path)
    assert expected.exists(), f"db file not created at {expected}"


async def test_bootstrap_is_idempotent() -> None:
    """A second bootstrap on the same data_dir is a no-op (no errors)."""
    await _bootstrap()
    await _bootstrap()


def test_module_main_imports() -> None:
    """``python -m bearings`` is supported via __main__.py."""
    import bearings.__main__  # noqa: F401  - exercise the import for coverage


def test_main_respects_log_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production-style env (JSON logs) bootstraps without raising."""
    monkeypatch.setenv("BEARINGS_ENVIRONMENT", "production")
    monkeypatch.setenv("BEARINGS_LOG_JSON", "true")
    main()
