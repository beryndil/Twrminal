"""Unit tests for bearings_dir/io.py.

Acceptance-criteria coverage:

* AC-io-1  read_toml returns empty dict for absent file.
* AC-io-2  write_toml writes valid TOML and is readable back.
* AC-io-3  write_toml is atomic: no temp file left on success.
* AC-io-4  read_jsonl returns empty list for absent file.
* AC-io-5  append_jsonl creates file and appends the entry.
* AC-io-6  append_jsonl cap: oldest entries trimmed from head (key edge case).
* AC-io-7  append_jsonl skips malformed JSONL lines without crashing.
* AC-io-8  append_jsonl is atomic: no temp file left on success.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from bearings.bearings_dir.io import append_jsonl, read_jsonl, read_toml, write_toml

# ---------------------------------------------------------------------------
# AC-io-1  read_toml — absent file returns {}
# ---------------------------------------------------------------------------


def test_read_toml_returns_empty_dict_for_absent_file(tmp_path: Path) -> None:
    result = read_toml(tmp_path / "nonexistent.toml")
    assert result == {}


# ---------------------------------------------------------------------------
# AC-io-2  write_toml / read_toml round-trip
# ---------------------------------------------------------------------------


def test_write_toml_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "out.toml"
    data = {"name": "bearings", "count": 42, "enabled": True}
    write_toml(path, data)
    assert path.exists()
    with path.open("rb") as fh:
        loaded = tomllib.load(fh)
    assert loaded == data


def test_write_toml_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "subdir" / "nested" / "out.toml"
    write_toml(path, {"x": 1})
    assert path.exists()


def test_write_toml_overwrites_existing(tmp_path: Path) -> None:
    path = tmp_path / "out.toml"
    write_toml(path, {"v": 1})
    write_toml(path, {"v": 2})
    with path.open("rb") as fh:
        loaded = tomllib.load(fh)
    assert loaded["v"] == 2


# ---------------------------------------------------------------------------
# AC-io-3  write_toml atomicity — no .tmp file left on success
# ---------------------------------------------------------------------------


def test_write_toml_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "out.toml"
    write_toml(path, {"k": "v"})
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"stale temp files: {tmp_files}"


# ---------------------------------------------------------------------------
# AC-io-4  read_jsonl — absent file returns []
# ---------------------------------------------------------------------------


def test_read_jsonl_returns_empty_list_for_absent_file(tmp_path: Path) -> None:
    result = read_jsonl(tmp_path / "nonexistent.jsonl")
    assert result == []


# ---------------------------------------------------------------------------
# AC-io-5  append_jsonl — creates and appends
# ---------------------------------------------------------------------------


def test_append_jsonl_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "hist.jsonl"
    append_jsonl(path, {"event": "start", "session_id": "ses_1"})
    assert path.exists()
    entries = read_jsonl(path)
    assert len(entries) == 1
    assert entries[0]["event"] == "start"


def test_append_jsonl_accumulates_entries(tmp_path: Path) -> None:
    path = tmp_path / "hist.jsonl"
    for i in range(3):
        append_jsonl(path, {"n": i}, cap=100)
    entries = read_jsonl(path)
    assert [e["n"] for e in entries] == [0, 1, 2]


# ---------------------------------------------------------------------------
# AC-io-6  append_jsonl cap — oldest entries trimmed from the HEAD
# ---------------------------------------------------------------------------


def test_append_jsonl_trims_oldest_when_cap_exceeded(tmp_path: Path) -> None:
    path = tmp_path / "hist.jsonl"
    # Fill to cap=3, then add two more.
    for i in range(5):
        append_jsonl(path, {"n": i}, cap=3)
    entries = read_jsonl(path)
    # Only the last 3 survive; entries 0 and 1 are trimmed.
    assert len(entries) == 3
    assert [e["n"] for e in entries] == [2, 3, 4]


def test_append_jsonl_exact_cap_does_not_trim(tmp_path: Path) -> None:
    path = tmp_path / "hist.jsonl"
    for i in range(5):
        append_jsonl(path, {"n": i}, cap=5)
    entries = read_jsonl(path)
    assert len(entries) == 5


# ---------------------------------------------------------------------------
# AC-io-7  append_jsonl — malformed lines skipped
# ---------------------------------------------------------------------------


def test_append_jsonl_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "hist.jsonl"
    # Pre-seed with one valid and one malformed line.
    path.write_text(
        '{"event": "ok"}\nNOT VALID JSON\n',
        encoding="utf-8",
    )
    append_jsonl(path, {"event": "new"}, cap=100)
    entries = read_jsonl(path)
    events = [e.get("event") for e in entries]
    assert "ok" in events
    assert "new" in events
    # Malformed line is gone (never parsed, not re-written).


# ---------------------------------------------------------------------------
# AC-io-8  append_jsonl atomicity — no .tmp file left on success
# ---------------------------------------------------------------------------


def test_append_jsonl_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "hist.jsonl"
    append_jsonl(path, {"x": 1}, cap=100)
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"stale temp files: {tmp_files}"


# ---------------------------------------------------------------------------
# read_jsonl — non-dict lines skipped
# ---------------------------------------------------------------------------


def test_read_jsonl_skips_non_dict_lines(tmp_path: Path) -> None:
    path = tmp_path / "hist.jsonl"
    path.write_text(
        '[1, 2, 3]\n{"event": "ok"}\n42\n',
        encoding="utf-8",
    )
    entries = read_jsonl(path)
    assert len(entries) == 1
    assert entries[0]["event"] == "ok"
