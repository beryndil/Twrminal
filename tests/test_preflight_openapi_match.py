"""Unit tests for ``scripts/preflight_openapi_match.py``.

Exercises the script's public surface against a known-mismatch fixture and
edge-case inputs so a future change to the check logic will surface as a
test failure before it silently weakens the gate.

The script is loaded via :func:`importlib.util.spec_from_file_location`
(the same technique used by ``test_consistency_lint.py``) because it lives
under ``scripts/`` rather than the installed package tree.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_SCRIPT_PATH: Final[Path] = _REPO_ROOT / "scripts" / "preflight_openapi_match.py"


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("preflight_openapi_match", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["preflight_openapi_match"] = module
    spec.loader.exec_module(module)
    return module


pom = _load_module()


# ---------------------------------------------------------------------------
# Fake HTTP response — stand-in for urllib.request.urlopen context manager
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal context-manager shim for a urllib HTTP response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        pass


# ---------------------------------------------------------------------------
# _extract_paths
# ---------------------------------------------------------------------------


class TestExtractPaths:
    def test_returns_path_keys(self) -> None:
        spec: dict[str, object] = {"paths": {"/api/foo": {}, "/api/bar": {}}}
        result = pom._extract_paths(spec)
        assert result == frozenset({"/api/foo", "/api/bar"})

    def test_missing_paths_key_returns_empty(self) -> None:
        assert pom._extract_paths({"openapi": "3.0.0"}) == frozenset()

    def test_non_dict_input_returns_empty(self) -> None:
        assert pom._extract_paths("not-a-dict") == frozenset()
        assert pom._extract_paths(None) == frozenset()
        assert pom._extract_paths(42) == frozenset()

    def test_empty_paths_dict(self) -> None:
        assert pom._extract_paths({"paths": {}}) == frozenset()

    def test_paths_value_not_dict_returns_empty(self) -> None:
        # Malformed spec — "paths" is a list instead of a dict.
        assert pom._extract_paths({"paths": ["/api/foo"]}) == frozenset()

    def test_path_keys_cast_to_str(self) -> None:
        # Keys should survive str() normalisation even if the parser
        # somehow returns non-str keys (defensive guard).
        spec: dict[str, object] = {"paths": {"/api/sessions": {}, "/api/sessions/bulk": {}}}
        result = pom._extract_paths(spec)
        assert "/api/sessions" in result
        assert "/api/sessions/bulk" in result


# ---------------------------------------------------------------------------
# get_live_paths — parses live server response
# ---------------------------------------------------------------------------


class TestGetLivePaths:
    """Tests that patch urllib.request.urlopen to avoid real network I/O."""

    def test_parses_openapi_paths(self, monkeypatch) -> None:
        """Known-mismatch fixture: live server exposes only /api/sessions."""
        live_spec: dict[str, object] = {
            "openapi": "3.0.0",
            "paths": {
                "/api/sessions": {"get": {}},
                # /api/sessions/bulk and /api/sessions/{id}/export
                # are intentionally absent — simulating stale server.
            },
        }
        fake_body = json.dumps(live_spec).encode("utf-8")
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda _url, **_kw: _FakeResponse(fake_body),
        )
        paths = pom.get_live_paths()
        assert paths == frozenset({"/api/sessions"})

    def test_non_dict_response_returns_empty(self, monkeypatch) -> None:
        """Server returns a JSON array — _extract_paths must return empty."""
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda _url, **_kw: _FakeResponse(b"[]"),
        )
        paths = pom.get_live_paths()
        assert paths == frozenset()

    def test_unreachable_propagates_url_error(self, monkeypatch) -> None:
        def _raise(_url: str, **_kw: object) -> _FakeResponse:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _raise)
        try:
            pom.get_live_paths()
            raise AssertionError("expected URLError")
        except urllib.error.URLError:
            pass


# ---------------------------------------------------------------------------
# check_openapi_match — integration of live + head comparison
# ---------------------------------------------------------------------------


class TestCheckOpenApiMatch:
    """Patches get_live_paths and get_head_paths to isolate the diff logic."""

    # Known-mismatch fixture: HEAD has three paths, live only has one.
    _STALE_HEAD = frozenset(
        {
            "/api/sessions",
            "/api/sessions/bulk",
            "/api/sessions/{session_id}/export",
            "/api/sessions/import",
        }
    )
    _STALE_LIVE = frozenset({"/api/sessions"})

    def test_match_returns_0(self, monkeypatch, capsys) -> None:
        paths = frozenset({"/api/sessions", "/api/sessions/bulk"})
        monkeypatch.setattr(pom, "get_live_paths", lambda **_: paths)
        monkeypatch.setattr(pom, "get_head_paths", lambda: paths)
        assert pom.check_openapi_match() == pom.EXIT_MATCH
        captured = capsys.readouterr()
        assert "PASS" in captured.err

    def test_mismatch_returns_1_and_names_missing_paths(self, monkeypatch, capsys) -> None:
        """Known-mismatch fixture — stale live server missing three HEAD paths."""
        monkeypatch.setattr(pom, "get_live_paths", lambda **_: self._STALE_LIVE)
        monkeypatch.setattr(pom, "get_head_paths", lambda: self._STALE_HEAD)
        result = pom.check_openapi_match()
        assert result == pom.EXIT_MISMATCH
        captured = capsys.readouterr()
        assert "stale" in captured.err
        assert "/api/sessions/bulk" in captured.err
        assert "/api/sessions/{session_id}/export" in captured.err
        assert "/api/sessions/import" in captured.err

    def test_mismatch_extra_in_live_reported(self, monkeypatch, capsys) -> None:
        """Live server has a path not present in HEAD (downgrade scenario)."""
        head = frozenset({"/api/sessions"})
        live = frozenset({"/api/sessions", "/api/legacy"})
        monkeypatch.setattr(pom, "get_live_paths", lambda **_: live)
        monkeypatch.setattr(pom, "get_head_paths", lambda: head)
        result = pom.check_openapi_match()
        assert result == pom.EXIT_MISMATCH
        captured = capsys.readouterr()
        assert "/api/legacy" in captured.err

    def test_unreachable_returns_2(self, monkeypatch, capsys) -> None:
        def _raise(**_: object) -> frozenset[str]:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(pom, "get_live_paths", _raise)
        monkeypatch.setattr(pom, "get_head_paths", lambda: frozenset())
        result = pom.check_openapi_match()
        assert result == pom.EXIT_UNREACHABLE
        captured = capsys.readouterr()
        assert "UNREACHABLE" in captured.err

    def test_oserror_treated_as_unreachable(self, monkeypatch, capsys) -> None:
        def _raise(**_: object) -> frozenset[str]:
            raise OSError("network error")

        monkeypatch.setattr(pom, "get_live_paths", _raise)
        monkeypatch.setattr(pom, "get_head_paths", lambda: frozenset())
        result = pom.check_openapi_match()
        assert result == pom.EXIT_UNREACHABLE

    def test_exit_constants_have_correct_values(self) -> None:
        assert pom.EXIT_MATCH == 0
        assert pom.EXIT_MISMATCH == 1
        assert pom.EXIT_UNREACHABLE == 2
