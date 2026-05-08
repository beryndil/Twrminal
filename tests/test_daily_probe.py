"""Tests for the daily health probe (``scripts/daily_probe``).

The probe's HTTP transport layer is exercised end-to-end by the live
timer run (``bearings-v1-probe.timer``). This file covers the
pure-function surface — probe orchestration, log serialisation, human
rendering — the parts that a refactor would silently break if a key
was renamed or a status-code contract drifted.

Coverage:

* :func:`run_probes` — all-pass, partial-fail, URLError/connection
  error (``status_code=None``), and the documented
  ``/api/quota/current`` 404-as-PASS multi-status branch.
* :func:`_result_to_jsonl` — payload shape (all 8 expected keys:
  ``ts``, ``probe``, ``path``, ``status``, ``accepted``,
  ``elapsed_ms``, ``passed``, ``detail``; correct types; sorted
  ``accepted`` list).
* :func:`write_log` — SUMMARY trailer format, append-on-same-day
  semantics (re-run accumulates rather than truncating), ``log_dir``
  creation at mode 0700, date-based filename.
* :func:`render_human` — empty-input sentinel, ``[PASS]`` / ``[FAIL]``
  markers, em-dash for ``None`` status, detail line on failure.
* ``PROBES`` table sanity (unique names, leading-slash paths,
  ``quota_current`` accepts ``{200, 404}``).

No test touches a live ``bearings-v1.service`` — ``_execute_probe``
is monkeypatched for all network tests; ``tmp_path`` is used for all
filesystem tests.
"""

from __future__ import annotations

import datetime as dt
import http.client
import importlib.util
import json
import os
import stat
import sys
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final

import pytest

# ---------------------------------------------------------------------------
# Module loader — same importlib.spec pattern as test_diff_probe.py
# ---------------------------------------------------------------------------

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_SCRIPT_PATH: Final[Path] = _REPO_ROOT / "scripts" / "daily_probe.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("daily_probe", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["daily_probe"] = module
    spec.loader.exec_module(module)
    return module


_M: Final[ModuleType] = _load_script_module()

if TYPE_CHECKING:  # pragma: no cover — type-only branch
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from daily_probe import (
        PROBE_LOG_RETENTION_DAYS_DEFAULT,
        PROBE_RETRY_ATTEMPTS,
        PROBE_RETRY_BACKOFF_S,
        PROBES,
        Probe,
        ProbeResult,
        _execute_probe,
        _result_to_jsonl,
        prune_old_logs,
        render_human,
        run_probes,
        write_log,
    )
else:
    PROBE_LOG_RETENTION_DAYS_DEFAULT = _M.PROBE_LOG_RETENTION_DAYS_DEFAULT
    PROBE_RETRY_ATTEMPTS = _M.PROBE_RETRY_ATTEMPTS
    PROBE_RETRY_BACKOFF_S = _M.PROBE_RETRY_BACKOFF_S
    PROBES = _M.PROBES
    Probe = _M.Probe
    ProbeResult = _M.ProbeResult
    _execute_probe = _M._execute_probe
    _result_to_jsonl = _M._result_to_jsonl
    prune_old_logs = _M.prune_old_logs
    render_human = _M.render_human
    run_probes = _M.run_probes
    write_log = _M.write_log


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_NOW: Final[dt.datetime] = dt.datetime(2026, 5, 8, 6, 0, 0, tzinfo=dt.UTC)


def _make_result(
    *,
    name: str = "health",
    path: str = "/api/health",
    accepted: frozenset[int] = frozenset({200}),
    status_code: int | None = 200,
    elapsed_ms: int = 15,
    detail: str = "ok status=200",
) -> ProbeResult:
    """Construct a :class:`ProbeResult` fixture without hitting the network."""
    probe = Probe(name=name, path=path, accepted_status_codes=accepted)
    return ProbeResult(
        probe=probe,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# run_probes — monkeypatched _execute_probe
# ---------------------------------------------------------------------------


def test_run_probes_all_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every probe returns an accepted status code → every result passes."""
    probe_iter = iter(PROBES)

    def fake_execute(
        probe: object, *, base_url: str, timeout_s: float, **_kwargs: object
    ) -> object:
        del probe, base_url, timeout_s
        current = next(probe_iter)
        return ProbeResult(
            probe=current,
            status_code=min(current.accepted_status_codes),
            elapsed_ms=10,
            detail="ok",
        )

    monkeypatch.setattr(_M, "_execute_probe", fake_execute)
    results = run_probes(base_url="http://127.0.0.1:8788", timeout_s=1.0)
    assert len(results) == len(PROBES)
    assert all(r.passed for r in results)


def test_run_probes_partial_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probes returning an unaccepted status code are marked FAIL."""
    probe_iter = iter(PROBES)

    def fake_execute(
        probe: object, *, base_url: str, timeout_s: float, **_kwargs: object
    ) -> object:
        del probe, base_url, timeout_s
        current = next(probe_iter)
        # 503 is not in any probe's accepted set.
        return ProbeResult(
            probe=current,
            status_code=503,
            elapsed_ms=5,
            detail="unexpected status=503",
        )

    monkeypatch.setattr(_M, "_execute_probe", fake_execute)
    results = run_probes(base_url="http://127.0.0.1:8788", timeout_s=1.0)
    assert len(results) == len(PROBES)
    assert all(not r.passed for r in results)


def test_run_probes_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection error → status_code=None and every probe fails."""
    probe_iter = iter(PROBES)

    def fake_execute(
        probe: object, *, base_url: str, timeout_s: float, **_kwargs: object
    ) -> object:
        del probe, base_url, timeout_s
        current = next(probe_iter)
        return ProbeResult(
            probe=current,
            status_code=None,
            elapsed_ms=1,
            detail="url_error reason='Connection refused'",
        )

    monkeypatch.setattr(_M, "_execute_probe", fake_execute)
    results = run_probes(base_url="http://127.0.0.1:8788", timeout_s=1.0)
    assert all(r.status_code is None for r in results)
    assert all(not r.passed for r in results)


def test_run_probes_quota_current_404_is_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """/api/quota/current returning 404 is the documented PASS branch.

    The module docstring explains that ``/api/quota/current`` returns
    404 when no quota snapshot has been recorded yet.  Accepting 404
    for that probe is the intended behaviour; this test locks it in.
    """
    probe_iter = iter(PROBES)

    def fake_execute(
        probe: object, *, base_url: str, timeout_s: float, **_kwargs: object
    ) -> object:
        del probe, base_url, timeout_s
        current = next(probe_iter)
        if current.name == "quota_current":
            return ProbeResult(
                probe=current,
                status_code=404,
                elapsed_ms=3,
                detail="http_error reason='Not Found'",
            )
        return ProbeResult(
            probe=current,
            status_code=min(current.accepted_status_codes),
            elapsed_ms=10,
            detail="ok",
        )

    monkeypatch.setattr(_M, "_execute_probe", fake_execute)
    results = run_probes(base_url="http://127.0.0.1:8788", timeout_s=1.0)
    quota_result = next(r for r in results if r.probe.name == "quota_current")
    assert quota_result.status_code == 404
    assert quota_result.passed is True  # 404 ∈ {200, 404}


def test_run_probes_result_order_matches_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Results are returned in the same order as the PROBES table."""
    probe_iter = iter(PROBES)

    def fake_execute(
        probe: object, *, base_url: str, timeout_s: float, **_kwargs: object
    ) -> object:
        del probe, base_url, timeout_s
        current = next(probe_iter)
        return ProbeResult(probe=current, status_code=200, elapsed_ms=1, detail="ok")

    monkeypatch.setattr(_M, "_execute_probe", fake_execute)
    results = run_probes(base_url="http://127.0.0.1:8788", timeout_s=1.0)
    assert [r.probe.name for r in results] == [p.name for p in PROBES]


# ---------------------------------------------------------------------------
# _result_to_jsonl — payload shape and key contracts
# ---------------------------------------------------------------------------


def test_result_to_jsonl_all_keys_present() -> None:
    """Serialised record contains exactly the 8 specified keys."""
    line = _result_to_jsonl(_make_result(), now=_NOW)
    payload = json.loads(line)
    assert set(payload.keys()) == {
        "ts",
        "probe",
        "path",
        "status",
        "accepted",
        "elapsed_ms",
        "passed",
        "detail",
    }


def test_result_to_jsonl_passing_probe_values() -> None:
    """Passing probe: correct key values including passed=True and ts format."""
    line = _result_to_jsonl(_make_result(status_code=200), now=_NOW)
    payload = json.loads(line)
    assert payload["probe"] == "health"
    assert payload["path"] == "/api/health"
    assert payload["status"] == 200
    assert payload["accepted"] == [200]
    assert payload["elapsed_ms"] == 15
    assert payload["passed"] is True
    assert payload["detail"] == "ok status=200"
    assert payload["ts"] == "2026-05-08T06:00:00+00:00"


def test_result_to_jsonl_url_error_status_is_null() -> None:
    """status_code=None serialises as JSON null; passed=False."""
    line = _result_to_jsonl(
        _make_result(status_code=None, detail="url_error reason='Connection refused'"),
        now=_NOW,
    )
    payload = json.loads(line)
    assert payload["status"] is None
    assert payload["passed"] is False


def test_result_to_jsonl_multi_status_accepted_sorted() -> None:
    """Multi-status accepted set serialises as a sorted list (deterministic)."""
    line = _result_to_jsonl(
        _make_result(
            name="quota_current",
            path="/api/quota/current",
            accepted=frozenset({200, 404}),
            status_code=404,
            detail="http_error reason='Not Found'",
        ),
        now=_NOW,
    )
    payload = json.loads(line)
    assert payload["accepted"] == [200, 404]
    assert payload["passed"] is True


def test_result_to_jsonl_output_is_single_line() -> None:
    """Output must be a single line (no embedded newlines) for JSONL format."""
    line = _result_to_jsonl(_make_result(), now=_NOW)
    assert "\n" not in line


# ---------------------------------------------------------------------------
# write_log — SUMMARY, append semantics, directory creation
# ---------------------------------------------------------------------------


def test_write_log_returns_log_path(tmp_path: Path) -> None:
    """write_log returns the path of the file it wrote."""
    log_path = write_log([_make_result()], now=_NOW, log_dir=tmp_path)
    assert log_path.exists()
    assert log_path.parent == tmp_path
    assert log_path.suffix == ".log"


def test_write_log_date_in_filename(tmp_path: Path) -> None:
    """Log filename encodes the probe date as YYYY-MM-DD.log."""
    now = dt.datetime(2025, 12, 31, 23, 59, 0, tzinfo=dt.UTC)
    write_log([_make_result()], now=now, log_dir=tmp_path)
    assert (tmp_path / "2025-12-31.log").exists()


def test_write_log_summary_trailer_present(tmp_path: Path) -> None:
    """SUMMARY trailer is the last line and contains overall/pass/fail/total."""
    results = [
        _make_result(status_code=200),
        _make_result(name="metrics", path="/metrics"),
    ]
    write_log(results, now=_NOW, log_dir=tmp_path)
    lines = (tmp_path / "2026-05-08.log").read_text().splitlines()
    last = lines[-1]
    assert last.startswith("SUMMARY ")
    assert "overall=PASS" in last
    assert "pass=2" in last
    assert "fail=0" in last
    assert "total=2" in last


def test_write_log_summary_reflects_failure(tmp_path: Path) -> None:
    """SUMMARY marks overall=FAIL and increments fail counter for a bad probe."""
    passing = _make_result(status_code=200)
    failing = _make_result(
        name="metrics",
        path="/metrics",
        status_code=None,
        detail="url_error reason='Connection refused'",
    )
    write_log([passing, failing], now=_NOW, log_dir=tmp_path)
    content = (tmp_path / "2026-05-08.log").read_text()
    assert "overall=FAIL" in content
    assert "fail=1" in content
    assert "pass=1" in content


def test_write_log_appends_on_same_day(tmp_path: Path) -> None:
    """Re-running on the same day accumulates records — does not truncate.

    Two runs with one probe each → 4 lines total (1 probe + 1 SUMMARY
    per run, two runs).
    """
    results = [_make_result()]
    write_log(results, now=_NOW, log_dir=tmp_path)
    write_log(results, now=_NOW, log_dir=tmp_path)
    lines = (tmp_path / "2026-05-08.log").read_text().splitlines()
    assert len(lines) == 4  # (1 probe record + 1 SUMMARY) * 2 runs
    summary_count = sum(1 for ln in lines if ln.startswith("SUMMARY "))
    assert summary_count == 2


def test_write_log_creates_log_dir_mode_0700(tmp_path: Path) -> None:
    """log_dir is created with mode 0700 when it does not yet exist."""
    log_dir = tmp_path / "probes_new"
    assert not log_dir.exists()
    write_log([_make_result()], now=_NOW, log_dir=log_dir)
    assert log_dir.exists()
    assert stat.S_IMODE(os.stat(log_dir).st_mode) == 0o700


def test_write_log_probe_lines_are_valid_jsonl(tmp_path: Path) -> None:
    """Every non-SUMMARY line in the log file is parseable JSON."""
    results = [
        _make_result(),
        _make_result(name="metrics", path="/metrics"),
    ]
    write_log(results, now=_NOW, log_dir=tmp_path)
    lines = (tmp_path / "2026-05-08.log").read_text().splitlines()
    json_lines = [ln for ln in lines if not ln.startswith("SUMMARY ")]
    for ln in json_lines:
        parsed = json.loads(ln)
        assert "probe" in parsed


# ---------------------------------------------------------------------------
# render_human — output formatting
# ---------------------------------------------------------------------------


def test_render_human_empty_list_returns_sentinel() -> None:
    """Empty result list → the '(no probes ran)' sentinel string."""
    assert render_human([]) == "(no probes ran)"


def test_render_human_pass_marker() -> None:
    """A passing probe line contains the [PASS] marker and the probe name."""
    output = render_human([_make_result(status_code=200)])
    assert "[PASS]" in output
    assert "health" in output


def test_render_human_fail_marker_with_detail_line() -> None:
    """A failing probe shows [FAIL] and the detail string on the next line."""
    result = _make_result(
        status_code=None,
        detail="url_error reason='Connection refused'",
    )
    output = render_human([result])
    assert "[FAIL]" in output
    assert "url_error" in output


def test_render_human_status_none_shows_em_dash() -> None:
    """status_code=None displays as '—' (em-dash) in the human table."""
    output = render_human([_make_result(status_code=None, detail="timeout")])
    assert "—" in output  # U+2014 EM DASH


def test_render_human_mixed_results_both_markers() -> None:
    """Mix of passing and failing probes → both [PASS] and [FAIL] appear."""
    passing = _make_result(status_code=200)
    failing = _make_result(
        name="metrics",
        path="/metrics",
        status_code=None,
        detail="url_error reason='Connection refused'",
    )
    output = render_human([passing, failing])
    assert "[PASS]" in output
    assert "[FAIL]" in output


def test_render_human_includes_probe_path() -> None:
    """Each result line contains the probe's path for quick cross-reference."""
    output = render_human([_make_result()])
    assert "/api/health" in output


# ---------------------------------------------------------------------------
# PROBES table sanity
# ---------------------------------------------------------------------------


def test_probes_table_non_empty() -> None:
    """PROBES is non-empty (would catch an accidental clear)."""
    assert len(PROBES) > 0


def test_probes_table_names_unique() -> None:
    """Probe names are unique — they drive SUMMARY counters and column widths."""
    names = [p.name for p in PROBES]
    assert len(names) == len(set(names))


def test_probes_table_paths_start_with_slash() -> None:
    """Every path starts with '/' so ``base_url + path`` concatenation is safe."""
    for probe in PROBES:
        assert probe.path.startswith("/"), (
            f"{probe.name!r} path {probe.path!r} missing leading slash"
        )


def test_probes_table_accepted_sets_nonempty() -> None:
    """Every probe has at least one accepted status code."""
    for probe in PROBES:
        assert probe.accepted_status_codes, f"{probe.name!r} has empty accepted_status_codes"


def test_probes_table_quota_current_accepts_200_and_404() -> None:
    """quota_current accepts {200, 404} — the documented 404 branch."""
    quota = next((p for p in PROBES if p.name == "quota_current"), None)
    assert quota is not None, "quota_current probe missing from PROBES table"
    assert quota.accepted_status_codes == frozenset({200, 404})


def test_probes_table_quota_current_path() -> None:
    """quota_current targets /api/quota/current (the headroom semantic swap)."""
    quota = next(p for p in PROBES if p.name == "quota_current")
    assert quota.path == "/api/quota/current"


# ---------------------------------------------------------------------------
# _execute_probe — retry semantics
#
# These tests exercise _execute_probe directly, monkeypatching
# urllib.request.urlopen (the transport layer) rather than _execute_probe
# itself, so the retry loop is exercised end-to-end.  retry_backoff_s=0.0
# avoids real sleeps without needing to monkeypatch time.sleep.
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal urlopen response stub: context manager + .status + .read()."""

    def __init__(self, status: int) -> None:
        self.status = status

    def read(self) -> bytes:
        return b""

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_execute_probe_retry_success_on_second_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection-refused on first attempt, succeeds on second → passed=True.

    The detail field includes the attempt counter when attempt > 1
    (e.g. "ok status=200 (attempt 2/3)").
    """
    probe = Probe(name="health", path="/api/health", accepted_status_codes=frozenset({200}))
    call_count = 0

    def fake_urlopen(_req: object, **_kw: object) -> _FakeResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise urllib.error.URLError("Connection refused")
        return _FakeResponse(200)

    monkeypatch.setattr(_M.urllib.request, "urlopen", fake_urlopen)
    result = _execute_probe(
        probe,
        base_url="http://127.0.0.1:8788",
        timeout_s=1.0,
        retry_attempts=3,
        retry_backoff_s=0.0,
    )
    assert result.passed is True
    assert result.status_code == 200
    assert "attempt 2/3" in result.detail
    assert call_count == 2


def test_execute_probe_retry_all_attempts_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 3 attempts fail → passed=False; detail notes exhausted retry budget."""
    probe = Probe(name="health", path="/api/health", accepted_status_codes=frozenset({200}))
    call_count = 0

    def fake_urlopen(_req: object, **_kw: object) -> _FakeResponse:
        nonlocal call_count
        call_count += 1
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(_M.urllib.request, "urlopen", fake_urlopen)
    result = _execute_probe(
        probe,
        base_url="http://127.0.0.1:8788",
        timeout_s=1.0,
        retry_attempts=3,
        retry_backoff_s=0.0,
    )
    assert result.passed is False
    assert result.status_code is None
    assert "exhausted 3/3" in result.detail
    assert call_count == 3


def test_execute_probe_retry_http_503_then_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTPError 503 on first attempt (retriable), 200 on second → passed=True.

    HTTP 503 is the canonical case for a graceful bearings-v1.service
    restart overlapping the probe window.
    """
    probe = Probe(name="health", path="/api/health", accepted_status_codes=frozenset({200}))
    call_count = 0

    def fake_urlopen(_req: object, **_kw: object) -> _FakeResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise urllib.error.HTTPError(
                "http://127.0.0.1:8788/api/health",
                503,
                "Service Unavailable",
                http.client.HTTPMessage(),
                None,
            )
        return _FakeResponse(200)

    monkeypatch.setattr(_M.urllib.request, "urlopen", fake_urlopen)
    result = _execute_probe(
        probe,
        base_url="http://127.0.0.1:8788",
        timeout_s=1.0,
        retry_attempts=3,
        retry_backoff_s=0.0,
    )
    assert result.passed is True
    assert result.status_code == 200
    assert "attempt 2/3" in result.detail
    assert call_count == 2


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
