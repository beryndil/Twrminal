"""Tests for GET /api/history/jsonl — directory-context history.jsonl reader.

Acceptance criteria (feature-10-004):
- Read: returns entries from history.jsonl in the requested directory.
- Missing-file degrade: returns empty list when the file does not exist.
- Cap / limit: the ``limit`` query param slices the tail of the file.
- Malformed entry: a corrupt line in the JSONL is skipped, not 500'd.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bearings.bearings_dir.io import append_jsonl
from bearings.config.constants import BEARINGS_DIR_HISTORY_CAP, BEARINGS_DIR_SUBDIR
from bearings.web.app import create_app


@pytest.fixture
def history_client() -> Generator[TestClient, None, None]:
    """In-process app for history reader tests (no DB required)."""
    app = create_app()
    with TestClient(app) as client:
        yield client


def _history_path(directory: Path) -> Path:
    return directory / BEARINGS_DIR_SUBDIR / "history.jsonl"


def _write_entry(directory: Path, event: str, session_id: str, timestamp: str) -> None:
    append_jsonl(
        _history_path(directory),
        {"event": event, "session_id": session_id, "timestamp": timestamp},
    )


# ---------------------------------------------------------------------------
# Missing-file degrade
# ---------------------------------------------------------------------------


def test_missing_file_returns_empty_list(history_client: TestClient, tmp_path: Path) -> None:
    """No history.jsonl → empty list, not 404 or 500."""
    resp = history_client.get("/api/history/jsonl", params={"directory": str(tmp_path)})
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Read: basic round-trip
# ---------------------------------------------------------------------------


def test_read_returns_written_entries(history_client: TestClient, tmp_path: Path) -> None:
    """Entries written via append_jsonl are returned by the reader."""
    _write_entry(tmp_path, "context_start", "sess-1", "2026-01-01T00:00:00+00:00")
    _write_entry(tmp_path, "context_start", "sess-2", "2026-01-02T00:00:00+00:00")

    resp = history_client.get("/api/history/jsonl", params={"directory": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["event"] == "context_start"
    assert data[0]["session_id"] == "sess-1"
    assert data[1]["session_id"] == "sess-2"


def test_unknown_fields_are_stripped(history_client: TestClient, tmp_path: Path) -> None:
    """Extra fields in the JSONL (future event types) are silently ignored."""
    append_jsonl(
        _history_path(tmp_path),
        {
            "event": "context_start",
            "session_id": "sess-x",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "future_field": "should be dropped",
        },
    )
    resp = history_client.get("/api/history/jsonl", params={"directory": str(tmp_path)})
    assert resp.status_code == 200
    entry = resp.json()[0]
    assert "future_field" not in entry
    assert entry["event"] == "context_start"


# ---------------------------------------------------------------------------
# Cap / limit
# ---------------------------------------------------------------------------


def test_limit_slices_most_recent_entries(history_client: TestClient, tmp_path: Path) -> None:
    """limit=2 returns the two newest entries from a file with more."""
    for i in range(5):
        _write_entry(tmp_path, "context_start", f"sess-{i}", f"2026-01-0{i + 1}T00:00:00+00:00")

    resp = history_client.get("/api/history/jsonl", params={"directory": str(tmp_path), "limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # The two most-recent are sess-3 and sess-4 (last two written).
    assert data[0]["session_id"] == "sess-3"
    assert data[1]["session_id"] == "sess-4"


def test_limit_defaults_to_history_cap(history_client: TestClient, tmp_path: Path) -> None:
    """Default limit equals BEARINGS_DIR_HISTORY_CAP (verified by writing cap+1 entries)."""
    # Write one more than the cap directly so we can check the limit applies.
    history_file = _history_path(tmp_path)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        {"event": "context_start", "session_id": f"s{i}", "timestamp": "2026-01-01T00:00:00Z"}
        for i in range(BEARINGS_DIR_HISTORY_CAP + 1)
    ]
    history_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    resp = history_client.get("/api/history/jsonl", params={"directory": str(tmp_path)})
    assert resp.status_code == 200
    # Default limit == cap; file has cap+1 entries, so we get cap entries.
    assert len(resp.json()) == BEARINGS_DIR_HISTORY_CAP


def test_limit_above_cap_is_rejected(history_client: TestClient, tmp_path: Path) -> None:
    """limit > BEARINGS_DIR_HISTORY_CAP returns 422 (FastAPI validation)."""
    resp = history_client.get(
        "/api/history/jsonl",
        params={"directory": str(tmp_path), "limit": BEARINGS_DIR_HISTORY_CAP + 1},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Malformed entry degrade
# ---------------------------------------------------------------------------


def test_malformed_entry_is_skipped(history_client: TestClient, tmp_path: Path) -> None:
    """A corrupt JSONL line (missing required fields) is skipped; valid entries are returned."""
    history_file = _history_path(tmp_path)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    # Write one valid + one entry missing `event` (required field).
    valid = {"event": "context_start", "session_id": "ok", "timestamp": "2026-01-01T00:00:00Z"}
    invalid = {"session_id": "bad", "timestamp": "2026-01-02T00:00:00Z"}  # missing event
    lines = [json.dumps(valid), json.dumps(invalid)]
    history_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    resp = history_client.get("/api/history/jsonl", params={"directory": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.json()
    # Only the valid entry is returned.
    assert len(data) == 1
    assert data[0]["session_id"] == "ok"
