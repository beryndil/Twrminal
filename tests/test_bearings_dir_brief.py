"""Tests for the per-turn directory-context brief renderer (v0.6.1).

Covers:
  - returns None when `.bearings/manifest.toml` is missing
  - manifest header includes name, language, path
  - state line surfaces branch + dirty + lockfile-fresh status
  - pending ops sorted oldest-first; stale 30-day flag prefix
  - history tail rendered with start-only marker as "likely crashed"
  - whole-brief char budget honored
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from bearings.bearings_dir.brief import (
    format_directory_brief,
    has_stale_pending_ops,
)
from bearings.bearings_dir.io import (
    HISTORY_FILE,
    MANIFEST_FILE,
    PENDING_FILE,
    STATE_FILE,
    append_history,
    bearings_path,
    ensure_bearings_dir,
    write_toml_model,
)
from bearings.bearings_dir.schema import (
    EnvironmentBlock,
    HistoryEntry,
    Manifest,
    Pending,
    PendingOperation,
    State,
)


def _seed_manifest(directory: Path, **overrides: object) -> None:
    ensure_bearings_dir(directory)
    defaults = {
        "name": "Bearings",
        "path": str(directory),
        "description": "localhost UI",
        "language": "python 3.12",
    }
    defaults.update(overrides)
    write_toml_model(
        bearings_path(directory) / MANIFEST_FILE,
        Manifest(**defaults),  # type: ignore[arg-type]
    )


def test_no_manifest_returns_none(tmp_path: Path) -> None:
    """Pre-onboarding directory: brief returns None so the prompt
    layer is silently skipped."""
    assert format_directory_brief(tmp_path) is None


def test_manifest_header_renders_identity(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    assert "**Bearings**" in brief
    assert "(python 3.12)" in brief
    assert str(tmp_path) in brief
    assert "localhost UI" in brief


def test_state_line_surfaces_branch_and_lockfile(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    state = State(
        branch="main",
        dirty=True,
        environment=EnvironmentBlock(lockfile_fresh=False),
    )
    write_toml_model(bearings_path(tmp_path) / STATE_FILE, state)
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    assert "branch `main` (dirty)" in brief
    assert "lockfile STALE" in brief


def test_pending_ops_sorted_and_stale_flagged(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    now = datetime.now(UTC)
    pending = Pending(
        operations=[
            PendingOperation(
                name="recent-op",
                description="just noticed",
                started=now - timedelta(hours=2),
            ),
            PendingOperation(
                name="ancient-op",
                description="from before vacation",
                started=now - timedelta(days=45),
            ),
        ]
    )
    write_toml_model(bearings_path(tmp_path) / PENDING_FILE, pending)
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    # Oldest first → ancient-op above recent-op.
    ancient_idx = brief.index("ancient-op")
    recent_idx = brief.index("recent-op")
    assert ancient_idx < recent_idx
    # Stale prefix on the >30d op only.
    assert "STALE `ancient-op`" in brief
    assert "STALE `recent-op`" not in brief


def test_history_start_without_end_renders_as_crashed(tmp_path: Path) -> None:
    """A start marker without a matching end-marker should render as
    'likely crashed' so the next session sees the prior one ended
    unclean."""
    _seed_manifest(tmp_path)
    history_path = bearings_path(tmp_path) / HISTORY_FILE
    append_history(
        history_path,
        HistoryEntry(
            session_id="abandoned1234",
            branch="feat/x",
            status="in_progress",
        ),
    )
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    assert "likely crashed" in brief
    # The brief renders the first 8 chars of session_id.
    assert "abandone" in brief


def test_history_clean_close_renders_status(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    history_path = bearings_path(tmp_path) / HISTORY_FILE
    started = datetime.now(UTC) - timedelta(minutes=30)
    ended = datetime.now(UTC)
    append_history(
        history_path,
        HistoryEntry(
            session_id="completed1234",
            started=started,
            ended=ended,
            branch="main",
            commits=["abc1234", "def5678"],
            status="clean",
        ),
    )
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    # The brief renders the first 8 chars of session_id.
    assert "complete" in brief
    assert "clean" in brief
    assert "2 commits" in brief


def test_brief_respects_char_budget(tmp_path: Path) -> None:
    """A pathologically-large pending list should not blow past the
    rendering budget."""
    _seed_manifest(tmp_path)
    # Cram pending up to the 64-op schema cap with long descriptions.
    long_desc = "x" * 400
    pending = Pending(
        operations=[PendingOperation(name=f"op-{i:03d}", description=long_desc) for i in range(64)]
    )
    write_toml_model(bearings_path(tmp_path) / PENDING_FILE, pending)
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    # Generous slack — the cap is 3200 chars but the truncation marker
    # adds a few; assert well under double the budget.
    assert len(brief) <= 3300


def test_on_open_result_renders_in_brief(tmp_path: Path) -> None:
    """A persisted `last_on_open.json` must surface in the per-turn
    brief so the agent sees the user's health-probe verdict. Failing
    runs include the stderr tail; passing runs collapse to a single
    headline line."""
    from datetime import UTC
    from datetime import datetime as _dt

    from bearings.bearings_dir.on_open import OnOpenResult, persist_on_open

    _seed_manifest(tmp_path)
    persist_on_open(
        tmp_path,
        OnOpenResult(
            ran_at=_dt.now(UTC),
            duration_ms=123,
            exit_code=2,
            stdout_snippet="",
            stderr_snippet="lockfile drift detected",
            timed_out=False,
        ),
    )
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    assert "on_open.sh" in brief
    assert "FAIL exit 2" in brief
    assert "lockfile drift detected" in brief


def test_on_open_passing_collapses_to_headline(tmp_path: Path) -> None:
    """An `exit 0` run must NOT spill stderr/stdout into the brief —
    the headline alone tells the agent the probe is happy. Saves the
    char budget for sections that actually need the bytes."""
    from datetime import UTC
    from datetime import datetime as _dt

    from bearings.bearings_dir.on_open import OnOpenResult, persist_on_open

    _seed_manifest(tmp_path)
    persist_on_open(
        tmp_path,
        OnOpenResult(
            ran_at=_dt.now(UTC),
            duration_ms=10,
            exit_code=0,
            stdout_snippet="(banner that should be omitted)",
            stderr_snippet="",
        ),
    )
    brief = format_directory_brief(tmp_path)
    assert brief is not None
    assert "OK (exit 0" in brief
    assert "banner that should be omitted" not in brief


def test_has_stale_pending_ops_true_when_any_old(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    pending = Pending(
        operations=[
            PendingOperation(name="fresh", started=datetime.now(UTC)),
            PendingOperation(
                name="aged",
                started=datetime.now(UTC) - timedelta(days=40),
            ),
        ]
    )
    write_toml_model(bearings_path(tmp_path) / PENDING_FILE, pending)
    assert has_stale_pending_ops(tmp_path) is True


def test_has_stale_pending_ops_false_on_empty(tmp_path: Path) -> None:
    _seed_manifest(tmp_path)
    assert has_stale_pending_ops(tmp_path) is False
