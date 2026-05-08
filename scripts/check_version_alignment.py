"""Version-alignment gate for Bearings v1.

Asserts that the ``[project].version`` in ``pyproject.toml`` equals the
``info.version`` in ``docs/openapi.json``.  The two strings must be
identical; a semantic-version subset check would silently accept a stale
spec paired with a bumped package version, which is the exact drift the
check is designed to catch.

Typical drift scenario: a developer bumps ``pyproject.toml`` for a
release but forgets to regenerate ``docs/openapi.json`` (or vice versa).
Running this check in CI and as a pre-commit hook ensures the mismatch
surfaces before merge.

Exit codes
----------
0 — versions agree.
1 — versions disagree; a clear message naming both values is printed to
    stdout so the CI log is actionable without scrolling through context.

Usage::

    uv run python scripts/check_version_alignment.py
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Repository root — two directories up from ``scripts/``.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: ``pyproject.toml`` source of the package version.
PYPROJECT_PATH: Final[Path] = REPO_ROOT / "pyproject.toml"

#: Committed OpenAPI spec whose ``info.version`` must match.
OPENAPI_PATH: Final[Path] = REPO_ROOT / "docs" / "openapi.json"

EXIT_OK: Final[int] = 0
EXIT_MISMATCH: Final[int] = 1


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------


def check_version_alignment() -> int:
    """Compare pyproject.toml version to docs/openapi.json info.version.

    Prints a descriptive message and returns 1 on mismatch, 0 on match.
    """
    with PYPROJECT_PATH.open("rb") as fh:
        pyproject = tomllib.load(fh)

    pkg_version: str = pyproject["project"]["version"]

    with OPENAPI_PATH.open(encoding="utf-8") as fh:
        openapi = json.load(fh)

    api_version: str = openapi["info"]["version"]

    if pkg_version == api_version:
        print(
            f"check_version_alignment: OK — both at {pkg_version!r}",
            file=sys.stderr,
        )
        return EXIT_OK

    print(
        f"check_version_alignment: MISMATCH\n"
        f"  pyproject.toml [project].version = {pkg_version!r}\n"
        f"  docs/openapi.json info.version   = {api_version!r}\n"
        "  Fix: bump the lagging file or re-run "
        "'uv run python scripts/regen_openapi.py' then commit both."
    )
    return EXIT_MISMATCH


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(check_version_alignment())
