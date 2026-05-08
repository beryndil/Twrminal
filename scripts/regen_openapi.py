"""Regenerate docs/openapi.json from the live FastAPI application.

Run this script (or let CI run it) after any route, request body, or
response-model change. The CI backend job calls this script and fails if
the committed file is stale. Pre-commit wires the same check so drift is
caught before push.

Behaviour
---------

1. Imports :func:`bearings.web.app.create_app`, calls ``.openapi()``,
   and serialises the result with ``indent=2`` plus a trailing newline —
   the canonical format prescribed in CLAUDE.md §"OpenAPI export".
2. Compares the serialised spec to the committed ``docs/openapi.json``
   via string equality (no subprocess required).
3. **Exit 0**: file is already up to date.
4. **Exit 1**: spec has drifted — the script overwrites ``docs/openapi.json``
   with the fresh content and emits a message instructing the contributor
   to commit the updated file.

The output is bit-for-bit reproducible: identical application code
always produces identical JSON bytes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

#: Repository root — two directories up from ``scripts/``.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Target path for the committed spec.
OPENAPI_OUTPUT_PATH: Final[Path] = REPO_ROOT / "docs" / "openapi.json"

EXIT_OK: Final[int] = 0
EXIT_DRIFT: Final[int] = 1


def regen_openapi() -> int:
    """Check docs/openapi.json for drift and regenerate if stale.

    Returns 0 when the file is already current, 1 when drift was
    detected (file is rewritten in place so the contributor can
    ``git add`` it and recommit).
    """
    try:
        # Local import keeps the script importable without the package
        # installed (e.g. during mypy analysis of the module header).
        from bearings.web.app import create_app

        spec = create_app().openapi()
        fresh = json.dumps(spec, indent=2) + "\n"
    except Exception as exc:
        print(f"regen_openapi: ERROR generating spec — {exc}", file=sys.stderr)
        return EXIT_DRIFT

    existing = (
        OPENAPI_OUTPUT_PATH.read_text(encoding="utf-8") if OPENAPI_OUTPUT_PATH.exists() else ""
    )

    if fresh == existing:
        print("regen_openapi: docs/openapi.json is up to date", file=sys.stderr)
        return EXIT_OK

    OPENAPI_OUTPUT_PATH.write_text(fresh, encoding="utf-8")
    print(
        "regen_openapi: docs/openapi.json was stale — regenerated.\n"
        "  Commit the updated file with: git add docs/openapi.json",
        file=sys.stderr,
    )
    return EXIT_DRIFT


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(regen_openapi())
