"""Frontend `package.json` must stay in lockstep with `pyproject.toml`.

Bearings ships as a Python wheel — the SvelteKit bundle is consumed by the
FastAPI app, not published as a standalone npm package. SemVer requires one
canonical version per deliverable (~/.claude/coding-standards.md §10), so
`pyproject.toml` is the source of truth and `frontend/package.json` is
kept in sync via `scripts/stamp-frontend-version.mjs` at build time.

This test catches drift even when the build hasn't been run yet — e.g. a
contributor bumps `pyproject.toml`, runs `pytest`, and forgets to rebuild
the frontend. CI fails fast instead of merging a mismatched bundle.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
FRONTEND_PACKAGE = REPO_ROOT / "frontend" / "package.json"


def _pyproject_version() -> str:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return str(data["project"]["version"])


def _frontend_version() -> str:
    return str(json.loads(FRONTEND_PACKAGE.read_text())["version"])


def test_frontend_version_matches_pyproject() -> None:
    """`frontend/package.json` version must equal `pyproject.toml` version.

    If this fails after a backend bump, run `cd frontend && npm run build`
    (which invokes `scripts/stamp-frontend-version.mjs` and auto-syncs)
    or hand-edit `frontend/package.json` to match.
    """
    assert _frontend_version() == _pyproject_version(), (
        f"frontend/package.json version {_frontend_version()!r} does not "
        f"match pyproject.toml version {_pyproject_version()!r}. "
        "Run `cd frontend && npm run build` to auto-sync, or edit "
        "frontend/package.json manually."
    )


def test_pyproject_version_is_semver() -> None:
    """Sanity check: the canonical version itself must be SemVer-shaped.

    `frontend/package.json` validates this implicitly via npm's parser, but
    `pyproject.toml` accepts anything in the version field — and a malformed
    backend version would be propagated by the stamp script. Catch it here.
    """
    semver_re = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
    version = _pyproject_version()
    assert semver_re.match(version), f"pyproject.toml version {version!r} is not valid SemVer 2.0.0"
