"""Schema-drift gate for Bearings v1.

Applies ``src/bearings/db/schema.sql`` to a fresh in-memory SQLite
database, dumps the resulting schema via ``sqlite_schema``, and compares
the set of objects (tables, indexes, views, triggers) and their
normalised DDL to what the source file declares.  Any mismatch — a
missing object, an extra object, or a DDL text that differs after
normalisation — is printed to stdout and the script exits 1.

Normalisation strips SQL line and block comments, removes the optional
``IF NOT EXISTS`` clause (SQLite omits it from the stored DDL), and
collapses all runs of whitespace to a single space so cosmetic
reformatting never produces false positives.

Run locally::

    uv run python scripts/check_schema_drift.py

Pre-commit: wired as the ``schema-drift`` hook so local commits catch
drift before push.
CI: wired as the ``schema.sql drift`` step in the backend job.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Final

import aiosqlite

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Repository root — two directories up from ``scripts/``.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Canonical schema source relative to the repository root.
SCHEMA_PATH: Final[Path] = REPO_ROOT / "src" / "bearings" / "db" / "schema.sql"

#: SQLite-internal name prefix excluded from user-object comparisons.
_SQLITE_INTERNAL_PREFIX: Final[str] = "sqlite_"

#: Regex to extract the object name from a CREATE statement.
#: Handles TABLE, VIRTUAL TABLE, UNIQUE INDEX, INDEX, VIEW, TRIGGER
#: with optional ``IF NOT EXISTS``.
_CREATE_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?(?:VIRTUAL\s+)?(?:TABLE|INDEX|VIEW|TRIGGER)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([a-z_]\w*)",
    re.IGNORECASE,
)

#: Strip SQL line comments (``-- ...`` to end-of-line).
_LINE_COMMENT_RE: Final[re.Pattern[str]] = re.compile(r"--[^\n]*")

#: Strip SQL block comments (``/* ... */``).
_BLOCK_COMMENT_RE: Final[re.Pattern[str]] = re.compile(r"/\*.*?\*/", re.DOTALL)

#: Remove the optional ``IF NOT EXISTS`` clause that SQLite strips when
#: storing DDL text in ``sqlite_schema``.
_IF_NOT_EXISTS_RE: Final[re.Pattern[str]] = re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.IGNORECASE)

#: Collapse runs of whitespace to a single space.
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

EXIT_OK: Final[int] = 0
EXIT_FINDINGS: Final[int] = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_sql(sql: str) -> str:
    """Return a canonical form of *sql* suitable for equality comparison.

    Strips block and line comments, removes ``IF NOT EXISTS``, collapses
    whitespace, and strips any trailing semicolon.
    """
    text = _BLOCK_COMMENT_RE.sub("", sql)
    text = _LINE_COMMENT_RE.sub("", text)
    text = _IF_NOT_EXISTS_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip().rstrip(";").strip()


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split *sql_text* into individual statements, respecting BEGIN...END blocks.

    A naive semicolon split breaks trigger DDL because trigger bodies
    contain embedded semicolons inside ``BEGIN ... END``.  This tokeniser
    tracks nesting depth and only splits at a semicolon when depth is 0.
    Single-quoted string literals are consumed whole so a semicolon inside
    a string value does not act as a statement boundary.
    """
    statements: list[str] = []
    buf: list[str] = []
    depth = 0

    # Match: single-quoted strings (with '' escapes), BEGIN/END keywords,
    # or bare semicolons.  Everything else is consumed as plain text
    # between matches.
    _TOKEN_RE: re.Pattern[str] = re.compile(
        r"'(?:''|[^'])*'"  # single-quoted string literal
        r"|\bBEGIN\b"  # BEGIN keyword (depth +1)
        r"|\bEND\b"  # END keyword (depth -1)
        r"|;",  # statement boundary at depth 0
        re.IGNORECASE,
    )

    pos = 0
    for m in _TOKEN_RE.finditer(sql_text):
        buf.append(sql_text[pos : m.start()])
        tok = m.group()
        pos = m.end()
        upper = tok.upper()
        if upper == "BEGIN":
            depth += 1
            buf.append(tok)
        elif upper == "END":
            depth -= 1
            buf.append(tok)
        elif tok == ";" and depth == 0:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(tok)  # string literal or non-keyword token

    buf.append(sql_text[pos:])
    last = "".join(buf).strip()
    if last:
        statements.append(last)

    return statements


def _extract_source_map(schema_text: str) -> dict[str, str]:
    """Return ``{object_name: normalised_sql}`` for every CREATE statement.

    Uses :func:`_split_sql_statements` (which tracks ``BEGIN...END`` depth)
    rather than a naive semicolon split so that trigger DDL — whose bodies
    contain embedded semicolons — is captured as a single complete unit.
    Virtual-table DDL (``CREATE VIRTUAL TABLE``) is also captured because
    ``_CREATE_NAME_RE`` now includes the ``VIRTUAL`` modifier.

    Non-CREATE statements (``PRAGMA``, ``INSERT``, blank lines) are silently
    ignored.
    """
    # Strip comments before statement-splitting so comment text cannot
    # confuse the tokeniser.
    stripped = _BLOCK_COMMENT_RE.sub("", _LINE_COMMENT_RE.sub("", schema_text))
    result: dict[str, str] = {}
    for raw_stmt in _split_sql_statements(stripped):
        normalised = _normalize_sql(raw_stmt)
        if not normalised:
            continue
        m = _CREATE_NAME_RE.match(normalised)
        if m:
            result[m.group(1).lower()] = normalised
    return result


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------


async def _check_drift() -> int:
    """Apply schema.sql to a memory DB and compare against the source.

    Returns :data:`EXIT_OK` (0) when no drift is detected, or
    :data:`EXIT_FINDINGS` (1) when any mismatch is found.  Each finding is
    printed to stdout (one per line) with the offending object named.
    """
    if not SCHEMA_PATH.is_file():
        print(
            f"check_schema_drift: schema.sql not found at {SCHEMA_PATH}",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
    source_map = _extract_source_map(schema_text)

    async with aiosqlite.connect(":memory:") as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(schema_text)
        rows = await conn.execute_fetchall(
            "SELECT name, sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY name"
        )

    db_map: dict[str, str] = {}
    for row in rows:
        name = str(row[0])
        sql = str(row[1])
        if not name.startswith(_SQLITE_INTERNAL_PREFIX):
            db_map[name.lower()] = _normalize_sql(sql)

    source_names = set(source_map)
    db_names = set(db_map)

    # Identify virtual tables declared in source (DDL starts with
    # CREATE VIRTUAL TABLE after normalisation).  SQLite auto-creates
    # shadow tables for virtual table modules (e.g. FTS5's ``_data``,
    # ``_idx``, ``_config``, ``_docsize`` tables).  These shadow tables
    # appear in ``sqlite_schema`` but are NOT declared in ``schema.sql``
    # — exclude them from the "extra in db" check.
    vt_names = {
        name
        for name, sql in source_map.items()
        if re.match(r"CREATE\s+VIRTUAL\s+TABLE\b", sql, re.IGNORECASE)
    }
    vt_shadow_names = {
        name
        for name in db_names - source_names
        if any(name.startswith(vt + "_") for vt in vt_names)
    }

    findings: list[str] = []

    for obj in sorted(source_names - db_names):
        findings.append(
            f"check_schema_drift: {obj!r} declared in schema.sql "
            "but not found in sqlite_schema after apply"
        )
    for obj in sorted((db_names - source_names) - vt_shadow_names):
        findings.append(
            f"check_schema_drift: {obj!r} found in sqlite_schema but not declared in schema.sql"
        )

    # DDL-content comparison for objects present on both sides.
    for obj in sorted(source_names & db_names):
        src_sql = source_map[obj]
        db_sql = db_map[obj]
        if src_sql != db_sql:
            findings.append(
                f"check_schema_drift: DDL mismatch for {obj!r}\n"
                f"  source: {src_sql[:120]!r}\n"
                f"  db:     {db_sql[:120]!r}"
            )

    if findings:
        for finding in findings:
            print(finding)
        print(
            f"\ncheck_schema_drift: {len(findings)} finding(s) — "
            "update schema.sql to match the intended schema",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    print(
        f"check_schema_drift: {len(db_names)} objects consistent",
        file=sys.stderr,
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Synchronous entry point for pre-commit and CI."""
    return asyncio.run(_check_drift())


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())
