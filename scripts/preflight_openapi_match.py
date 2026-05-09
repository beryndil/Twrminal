"""Preflight check — live OpenAPI surface vs HEAD router declarations.

Compares the set of paths exposed by the running server at
``http://127.0.0.1:8788/openapi.json`` against the paths generated from
the current source tree via :func:`bearings.web.app.create_app`.

A mismatch means the server is running a stale Python image (i.e. it was
launched before recent commits landed) and must be restarted.

Exit codes
----------
0  Paths match — live API is current with HEAD.
1  Paths differ — prints the symmetric diff and a ``live API stale vs
   HEAD`` diagnostic.  Restart the server and re-run to clear.
2  Server not reachable — prints the URL that failed.

Usage
-----
.. code-block:: console

    # From repo root (venv activated or prefixed with ``uv run``):
    python scripts/preflight_openapi_match.py

Wired into the Doctor preflight step per ``.v1-ship/runbooks/qa-loop.md``
§Doctor + §Tooling installs.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Final

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LIVE_BASE_URL: Final[str] = "http://127.0.0.1:8788"
REQUEST_TIMEOUT_S: Final[float] = 10.0

EXIT_MATCH: Final[int] = 0
EXIT_MISMATCH: Final[int] = 1
EXIT_UNREACHABLE: Final[int] = 2


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _extract_paths(spec: object) -> frozenset[str]:
    """Return the path key set from a parsed OpenAPI spec dict.

    Returns an empty frozenset when *spec* is not a dict or has no
    ``"paths"`` entry — callers treat that as "zero paths declared".
    """
    if not isinstance(spec, dict):
        return frozenset()
    paths_obj = spec.get("paths")
    if not isinstance(paths_obj, dict):
        return frozenset()
    return frozenset(str(k) for k in paths_obj)


def get_head_paths() -> frozenset[str]:
    """Return OpenAPI paths as declared by the current source tree (HEAD).

    Imports :func:`bearings.web.app.create_app` locally so the script
    remains importable before the package is installed (e.g. during the
    mypy analysis phase where only the script module is loaded).
    """
    from bearings.web.app import create_app  # local — keeps module importable pre-install

    spec: object = create_app().openapi()
    return _extract_paths(spec)


def get_live_paths(
    base_url: str = LIVE_BASE_URL,
    timeout: float = REQUEST_TIMEOUT_S,
) -> frozenset[str]:
    """Fetch and return OpenAPI paths from the running server.

    Raises :class:`urllib.error.URLError` or :class:`OSError` when the
    server is not reachable; callers are expected to handle those.
    """
    url = f"{base_url}/openapi.json"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw: object = json.loads(resp.read().decode("utf-8"))
    return _extract_paths(raw)


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------


def check_openapi_match(
    base_url: str = LIVE_BASE_URL,
    timeout: float = REQUEST_TIMEOUT_S,
) -> int:
    """Compare live paths to HEAD-generated paths.

    Returns an exit code:

    * ``EXIT_MATCH`` (0) — paths are identical.
    * ``EXIT_MISMATCH`` (1) — paths differ; diagnostics written to stderr.
    * ``EXIT_UNREACHABLE`` (2) — server not reachable; error written to
      stderr.
    """
    try:
        live = get_live_paths(base_url=base_url, timeout=timeout)
    except (urllib.error.URLError, OSError) as exc:
        print(
            f"preflight_openapi_match: UNREACHABLE — {base_url}/openapi.json\n  {exc}",
            file=sys.stderr,
        )
        return EXIT_UNREACHABLE

    head = get_head_paths()

    missing_in_live = head - live
    extra_in_live = live - head

    if not missing_in_live and not extra_in_live:
        print(
            "preflight_openapi_match: PASS — live API matches HEAD",
            file=sys.stderr,
        )
        return EXIT_MATCH

    print(
        "preflight_openapi_match: FAIL — live API stale vs HEAD\n"
        "  The running server does not expose all routes declared at HEAD.",
        file=sys.stderr,
    )
    if missing_in_live:
        print(
            f"  Missing from live ({len(missing_in_live)} path(s) — "
            "declared in source but absent in running server):",
            file=sys.stderr,
        )
        for path in sorted(missing_in_live):
            print(f"    - {path}", file=sys.stderr)
    if extra_in_live:
        print(
            f"  Extra in live ({len(extra_in_live)} path(s) — "
            "present in running server but absent in HEAD source):",
            file=sys.stderr,
        )
        for path in sorted(extra_in_live):
            print(f"    + {path}", file=sys.stderr)
    print(
        "  → Restart the server (`kill <PID>` then re-launch) to load current source.",
        file=sys.stderr,
    )
    return EXIT_MISMATCH


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry point — run the check and return an exit code."""
    return check_openapi_match()


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())
