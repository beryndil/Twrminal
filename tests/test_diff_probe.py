"""Tests for the item B.2 differential probe (``scripts/diff_probe``).

The script's HTTP transport layer is exercised end-to-end by the live
cutover-window run (where 8787 is the v0.17.x dogfood instance and
8788 is the v1 service). What this file covers is the pure-function
diff layer — shape extraction, JSON-shape diff, OpenAPI path-set diff,
Prometheus metric-name diff, log serialisation. Those are the parts
that other items would silently break if a refactor renamed a key or
flipped a comparison.

Coverage:

* :func:`extract_shape` collapses primitives, dicts, and lists per the
  module-docstring rules (bool before int; list-of-dict union-of-keys;
  empty-list sentinel).
* :func:`diff_shapes` reports missing keys on either side and type
  mismatches with stable, sorted output.
* :func:`diff_openapi` compares ``(METHOD, path)`` sets, ignores
  OPTIONS / HEAD, and tolerates a missing ``paths`` key.
* :func:`extract_metric_names` parses ``# HELP <name>`` lines and
  ignores everything else.
* :func:`diff_metrics` reports missing-on-either-side over the parsed
  name set.
* :func:`_result_to_jsonl` produces well-formed JSON for a fixed
  :class:`DiffResult` fixture (covers the dataclass-to-payload
  serialisation path).
* :func:`run_probe` orchestrates one end-to-end probe against a fake
  HTTP transport (monkeypatched ``_execute_side``), exercising the
  ``shape_match`` flag through the json_shape mode.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final

import pytest

# Load the script as a module via spec — same loader pattern
# tests/test_cutover_smoke.py uses for its script-under-test.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_SCRIPT_PATH: Final[Path] = _REPO_ROOT / "scripts" / "diff_probe.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("diff_probe", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["diff_probe"] = module
    spec.loader.exec_module(module)
    return module


_M: Final[ModuleType] = _load_script_module()

if TYPE_CHECKING:  # pragma: no cover — type-only branch
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from diff_probe import (
        PROBE_LOG_RETENTION_DAYS_DEFAULT,
        PROBES,
        DiffProbe,
        DiffResult,
        SideResult,
        diff_metrics,
        diff_openapi,
        diff_shapes,
        extract_metric_names,
        extract_shape,
        prune_old_logs,
        run_probe,
    )
else:
    PROBE_LOG_RETENTION_DAYS_DEFAULT = _M.PROBE_LOG_RETENTION_DAYS_DEFAULT
    PROBES = _M.PROBES
    DiffProbe = _M.DiffProbe
    DiffResult = _M.DiffResult
    SideResult = _M.SideResult
    diff_metrics = _M.diff_metrics
    diff_openapi = _M.diff_openapi
    diff_shapes = _M.diff_shapes
    extract_metric_names = _M.extract_metric_names
    extract_shape = _M.extract_shape
    prune_old_logs = _M.prune_old_logs
    run_probe = _M.run_probe


# ---------------------------------------------------------------------------
# extract_shape
# ---------------------------------------------------------------------------


def test_extract_shape_primitives() -> None:
    assert extract_shape(None) == "null"
    assert extract_shape(True) == "bool"
    assert extract_shape(False) == "bool"
    # bool-before-int: True is an int subclass; the order in
    # extract_shape matters.
    assert extract_shape(1) == "int"
    assert extract_shape(1.5) == "float"
    assert extract_shape("hello") == "str"


def test_extract_shape_dict_keys_sorted() -> None:
    shape = extract_shape({"b": 1, "a": "x"})
    # Skeleton itself is a dict; its iteration order is the sorted
    # insertion order from extract_shape.
    assert shape == {"a": "str", "b": "int"}
    assert isinstance(shape, dict)
    assert list(shape.keys()) == ["a", "b"]


def test_extract_shape_empty_list_sentinel() -> None:
    assert extract_shape([]) == "<empty list>"


def test_extract_shape_list_of_primitives() -> None:
    assert extract_shape([1, 2, 3]) == ["int"]
    assert extract_shape(["a"]) == ["str"]


def test_extract_shape_list_of_dicts_unions_keys() -> None:
    rows = [
        {"id": "abc", "title": "first"},
        {"id": "def", "title": "second", "closed_at": "2026-05-01T00:00:00Z"},
        {"id": "ghi", "title": "third"},
    ]
    shape = extract_shape(rows)
    assert shape == [{"closed_at": "str", "id": "str", "title": "str"}]


def test_extract_shape_nested() -> None:
    payload = {
        "session": {"id": "abc", "tags": [{"id": 1, "label": "x"}]},
        "count": 3,
    }
    shape = extract_shape(payload)
    assert shape == {
        "count": "int",
        "session": {
            "id": "str",
            "tags": [{"id": "int", "label": "str"}],
        },
    }


# ---------------------------------------------------------------------------
# diff_shapes
# ---------------------------------------------------------------------------


def test_diff_shapes_identical_returns_no_deltas() -> None:
    deltas = diff_shapes({"a": "str"}, {"a": "str"})
    assert deltas == {
        "missing_in_v017": [],
        "missing_in_v1": [],
        "type_mismatches": [],
    }


def test_diff_shapes_missing_keys_reported_on_correct_side() -> None:
    left = {"a": "str", "b": "int"}
    right = {"a": "str", "c": "bool"}
    deltas = diff_shapes(left, right)
    # b is on v017 only → missing on v1.
    assert deltas["missing_in_v1"] == ["$.b"]
    # c is on v1 only → missing on v017.
    assert deltas["missing_in_v017"] == ["$.c"]
    assert deltas["type_mismatches"] == []


def test_diff_shapes_type_mismatch_reported() -> None:
    deltas = diff_shapes({"a": "str"}, {"a": "int"})
    assert deltas["missing_in_v017"] == []
    assert deltas["missing_in_v1"] == []
    assert len(deltas["type_mismatches"]) == 1
    assert "$.a" in deltas["type_mismatches"][0]


def test_diff_shapes_recurses_into_nested_dicts() -> None:
    left = {"outer": {"a": "str"}}
    right = {"outer": {"a": "int"}}
    deltas = diff_shapes(left, right)
    assert any("$.outer.a" in m for m in deltas["type_mismatches"])


def test_diff_shapes_recurses_into_list_elements() -> None:
    left = [{"id": "str"}]
    right = [{"id": "int"}]
    deltas = diff_shapes(left, right)
    assert any("$[].id" in m for m in deltas["type_mismatches"])


def test_diff_shapes_output_lists_are_sorted() -> None:
    left = {"z": "str", "a": "str"}
    right = {"m": "str"}
    deltas = diff_shapes(left, right)
    # Both "z" and "a" missing on v1 — order must be alphabetical.
    assert deltas["missing_in_v1"] == ["$.a", "$.z"]


# ---------------------------------------------------------------------------
# diff_openapi
# ---------------------------------------------------------------------------


def test_diff_openapi_identical_paths_no_deltas() -> None:
    doc: dict[str, object] = {
        "paths": {
            "/api/health": {"get": {}},
            "/api/sessions": {"get": {}, "post": {}},
        },
    }
    result = diff_openapi(doc, doc)
    assert result["missing_in_v017"] == []
    assert result["missing_in_v1"] == []
    assert result["common_count"] == 3
    assert result["v017_total"] == 3
    assert result["v1_total"] == 3


def test_diff_openapi_added_endpoint_in_v1() -> None:
    left: dict[str, object] = {"paths": {"/api/health": {"get": {}}}}
    right: dict[str, object] = {
        "paths": {
            "/api/health": {"get": {}},
            "/api/quota/current": {"get": {}},
        },
    }
    result = diff_openapi(left, right)
    assert result["missing_in_v017"] == ["GET /api/quota/current"]
    assert result["missing_in_v1"] == []


def test_diff_openapi_removed_endpoint_in_v1() -> None:
    left: dict[str, object] = {
        "paths": {
            "/api/health": {"get": {}},
            "/api/legacy": {"get": {}},
        },
    }
    right: dict[str, object] = {"paths": {"/api/health": {"get": {}}}}
    result = diff_openapi(left, right)
    assert result["missing_in_v017"] == []
    assert result["missing_in_v1"] == ["GET /api/legacy"]


def test_diff_openapi_ignores_options_and_head() -> None:
    doc: dict[str, object] = {
        "paths": {
            "/api/x": {
                "get": {},
                "options": {},  # FastAPI auto-registers — must ignore.
                "head": {},  # ditto.
            },
        },
    }
    routes = _M._openapi_routes(doc)
    assert routes == {("GET", "/api/x")}


def test_diff_openapi_tolerates_missing_paths_key() -> None:
    result = diff_openapi({}, {"paths": {"/api/x": {"get": {}}}})
    assert result["missing_in_v017"] == ["GET /api/x"]
    assert result["v017_total"] == 0


def test_diff_openapi_tolerates_non_dict_input() -> None:
    # A busted spec (e.g. ``[]``) yields an empty route set, not a
    # raised exception — observational tool, not a validator.
    result = diff_openapi([], [])
    assert result["common_count"] == 0
    assert result["v017_total"] == 0
    assert result["v1_total"] == 0


# ---------------------------------------------------------------------------
# extract_metric_names + diff_metrics
# ---------------------------------------------------------------------------


def test_extract_metric_names_parses_help_lines() -> None:
    exposition = (
        "# HELP bearings_sessions_total Total session count.\n"
        "# TYPE bearings_sessions_total counter\n"
        "bearings_sessions_total 42\n"
        "# HELP bearings_quota_pct Quota usage percentage.\n"
        "# TYPE bearings_quota_pct gauge\n"
        "bearings_quota_pct 0.73\n"
    )
    names = extract_metric_names(exposition)
    assert names == {"bearings_sessions_total", "bearings_quota_pct"}


def test_extract_metric_names_empty_exposition() -> None:
    assert extract_metric_names("") == set()


def test_extract_metric_names_ignores_non_help_lines() -> None:
    # Comments, type lines, and blank lines all skip.
    exposition = "# A comment\n# TYPE foo counter\n\nsome_metric 1\n"
    assert extract_metric_names(exposition) == set()


def test_diff_metrics_reports_missing_on_either_side() -> None:
    left = "# HELP a Description.\n# HELP b Description.\n"
    right = "# HELP b Description.\n# HELP c Description.\n"
    result = diff_metrics(left, right)
    assert result["missing_in_v1"] == ["a"]
    assert result["missing_in_v017"] == ["c"]
    assert result["common_count"] == 1
    assert result["v017_total"] == 2
    assert result["v1_total"] == 2


# ---------------------------------------------------------------------------
# _result_to_jsonl serialisation
# ---------------------------------------------------------------------------


def test_result_to_jsonl_roundtrips() -> None:
    probe = DiffProbe(
        name="health",
        path="/api/health",
        diff_mode="json_shape",
    )
    v017 = SideResult(
        base_url="http://127.0.0.1:8787",
        status_code=200,
        elapsed_ms=12,
        body='{"ok": true}',
        detail="ok status=200",
    )
    v1 = SideResult(
        base_url="http://127.0.0.1:8788",
        status_code=200,
        elapsed_ms=8,
        body='{"ok": true}',
        detail="ok status=200",
    )
    result = DiffResult(probe=probe, v017=v017, v1=v1, shape_match=True, deltas={})
    now = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)

    line = _M._result_to_jsonl(result, now=now)
    payload = json.loads(line)
    assert payload["probe"] == "health"
    assert payload["path"] == "/api/health"
    assert payload["diff_mode"] == "json_shape"
    assert payload["accepted"] == [200]
    assert payload["v017"]["status"] == 200
    assert payload["v1"]["status"] == 200
    assert payload["shape_match"] is True
    assert payload["passed"] is True
    assert payload["ts"] == "2026-05-01T12:00:00+00:00"


# ---------------------------------------------------------------------------
# run_probe orchestration (against a fake transport)
# ---------------------------------------------------------------------------


def test_run_probe_match_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end probe against a fake transport — both sides match."""
    probe = DiffProbe(
        name="health",
        path="/api/health",
        diff_mode="json_shape",
    )

    def fake_execute_side(
        p: object,
        *,
        base_url: str,
        timeout_s: float,
    ) -> object:
        del p, timeout_s
        return SideResult(
            base_url=base_url,
            status_code=200,
            elapsed_ms=5,
            body='{"status": "ok", "version": "1.0.0"}',
            detail="ok status=200",
        )

    monkeypatch.setattr(_M, "_execute_side", fake_execute_side)
    result = run_probe(
        probe,
        v017_base_url="http://127.0.0.1:8787",
        v1_base_url="http://127.0.0.1:8788",
        timeout_s=1.0,
    )
    assert result.passed is True
    assert result.shape_match is True
    assert result.deltas == {
        "missing_in_v017": [],
        "missing_in_v1": [],
        "type_mismatches": [],
    }


def test_run_probe_diverge_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end probe — both sides reachable but shapes differ."""
    probe = DiffProbe(
        name="health",
        path="/api/health",
        diff_mode="json_shape",
    )

    def fake_execute_side(
        p: object,
        *,
        base_url: str,
        timeout_s: float,
    ) -> object:
        del p, timeout_s
        # v017 returns ``status: str``; v1 returns ``status: int``.
        body = '{"status": "ok"}' if base_url.endswith("8787") else '{"status": 200}'
        return SideResult(
            base_url=base_url,
            status_code=200,
            elapsed_ms=5,
            body=body,
            detail="ok status=200",
        )

    monkeypatch.setattr(_M, "_execute_side", fake_execute_side)
    result = run_probe(
        probe,
        v017_base_url="http://127.0.0.1:8787",
        v1_base_url="http://127.0.0.1:8788",
        timeout_s=1.0,
    )
    # passed is reachability-only; diverge does not flip it.
    assert result.passed is True
    assert result.shape_match is False
    type_mismatches = result.deltas["type_mismatches"]
    assert isinstance(type_mismatches, list)
    assert any("$.status" in m for m in type_mismatches)


def test_run_probe_unreachable_v017(monkeypatch: pytest.MonkeyPatch) -> None:
    """v017 down → ``passed`` False; deltas record the skip reason."""
    probe = DiffProbe(
        name="health",
        path="/api/health",
        diff_mode="json_shape",
    )

    def fake_execute_side(
        p: object,
        *,
        base_url: str,
        timeout_s: float,
    ) -> object:
        del p, timeout_s
        if base_url.endswith("8787"):
            return SideResult(
                base_url=base_url,
                status_code=None,
                elapsed_ms=10,
                body=None,
                detail="url_error reason='Connection refused'",
            )
        return SideResult(
            base_url=base_url,
            status_code=200,
            elapsed_ms=5,
            body='{"status": "ok"}',
            detail="ok status=200",
        )

    monkeypatch.setattr(_M, "_execute_side", fake_execute_side)
    result = run_probe(
        probe,
        v017_base_url="http://127.0.0.1:8787",
        v1_base_url="http://127.0.0.1:8788",
        timeout_s=1.0,
    )
    assert result.passed is False
    assert result.shape_match is False
    assert result.deltas["skipped"] == "one or both sides unreachable"


# ---------------------------------------------------------------------------
# PROBES table sanity
# ---------------------------------------------------------------------------


def test_probes_table_has_expected_diff_modes() -> None:
    """Every probe declares a known diff_mode and the surface is sane."""
    seen_modes = {p.diff_mode for p in PROBES}
    assert seen_modes <= {"json_shape", "openapi_paths", "metric_names"}
    # Every probe path starts with '/' so naive concatenation with the
    # base URL produces a valid URL.
    for probe in PROBES:
        assert probe.path.startswith("/")
        assert probe.name  # non-empty.
    # Probe names are unique (drives the SUMMARY counters and the
    # human-readable table column-widths).
    names = [p.name for p in PROBES]
    assert len(names) == len(set(names))


def test_probes_table_excludes_v1_only_quota_endpoints() -> None:
    """Per module docstring: quota/* is v1-only and must not be probed."""
    paths = {p.path for p in PROBES}
    assert not any(p.startswith("/api/quota/") for p in paths)


# ---------------------------------------------------------------------------
# prune_old_logs
# ---------------------------------------------------------------------------

# Frozen "now" for all pruning tests — 2026-05-08 00:00 UTC.
_PRUNE_NOW: Final[dt.datetime] = dt.datetime(2026, 5, 8, 0, 0, 0, tzinfo=dt.UTC)
_MAX_AGE: Final[int] = PROBE_LOG_RETENTION_DAYS_DEFAULT  # 30


def test_prune_old_logs_deletes_stale_retains_fresh(tmp_path: Path) -> None:
    """File from day -31 is deleted; file from day -29 is retained."""
    stale = tmp_path / "2026-04-07.log"  # 31 days before _PRUNE_NOW
    fresh = tmp_path / "2026-04-09.log"  # 29 days before _PRUNE_NOW
    stale.write_text("stale\n")
    fresh.write_text("fresh\n")

    prune_old_logs(tmp_path, _MAX_AGE, _PRUNE_NOW)

    assert not stale.exists(), "stale log (day -31) should have been deleted"
    assert fresh.exists(), "fresh log (day -29) should be retained"


def test_prune_old_logs_zero_disables_pruning(tmp_path: Path) -> None:
    """--max-age-days=0 skips pruning — even very old files are kept."""
    ancient = tmp_path / "2020-01-01.log"
    ancient.write_text("ancient\n")

    prune_old_logs(tmp_path, 0, _PRUNE_NOW)

    assert ancient.exists(), "max_age_days=0 must retain all logs"


def test_prune_old_logs_ignores_non_matching_names(tmp_path: Path) -> None:
    """Files that don't match YYYY-MM-DD.log are never deleted."""
    readme = tmp_path / "README"
    gzip_log = tmp_path / "2026-04-07.log.gz"
    partial = tmp_path / "2026-04-07"
    for f in (readme, gzip_log, partial):
        f.write_text("do not delete\n")

    prune_old_logs(tmp_path, _MAX_AGE, _PRUNE_NOW)

    for f in (readme, gzip_log, partial):
        assert f.exists(), f"{f.name} should not be deleted (non-matching name)"


def test_prune_old_logs_missing_log_dir_is_noop(tmp_path: Path) -> None:
    """A non-existent log_dir is silently tolerated — no exception raised."""
    missing = tmp_path / "nonexistent"
    # Must not raise:
    prune_old_logs(missing, _MAX_AGE, _PRUNE_NOW)


def test_prune_old_logs_default_constant_is_30() -> None:
    """The default retention window is 30 days per the spec contract."""
    assert PROBE_LOG_RETENTION_DAYS_DEFAULT == 30
