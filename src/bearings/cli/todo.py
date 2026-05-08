"""``bearings todo`` subcommand surface.

Per ``docs/behavior/bearings-cli.md`` §"bearings todo" the user sees
four sub-subcommands:

* ``open`` — list every Open / In Progress entry across every TODO.md
  in scope.
* ``check`` — lint every TODO.md for format and staleness.
* ``add`` — append a properly-formatted stub entry.
* ``recent`` — list entries that changed in the last N days.

Each surfaces stdout for human-readable / JSON output and stderr for
error paths; exit codes per
:data:`bearings.config.constants.CLI_EXIT_OK` /
:data:`bearings.config.constants.CLI_EXIT_OPERATION_FAILURE` /
:data:`bearings.config.constants.CLI_EXIT_USAGE_ERROR`.

Per arch §1.1.1 the subcommand body stays thin: parsing the per-
sub-subcommand args, calling into :mod:`bearings.cli._todo_io`,
formatting the output. No business logic.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from bearings.cli._todo_io import (
    DEFAULT_TODO_STATUS,
    KNOWN_TODO_STATUSES,
    TodoEntry,
    filter_by_area,
    filter_by_status,
    parse_all,
    walk_todo_files,
)
from bearings.config.constants import (
    BEARINGS_TODO_CHECK_DEFAULT_MAX_AGE_DAYS,
    BEARINGS_TODO_FILENAME,
    BEARINGS_TODO_RECENT_DEFAULT_DAYS,
    CLI_EXIT_OK,
    CLI_EXIT_OPERATION_FAILURE,
    CLI_EXIT_USAGE_ERROR,
)

# Default status filter for ``bearings todo open`` — the doc-mandated
# "Open,In Progress" pair. Stored as a tuple so a future addition is
# one edit and the CLI argument default reads naturally.
_OPEN_DEFAULT_STATUSES: tuple[str, ...] = ("Open", "In Progress")

# Output format alphabet for ``open`` / ``recent`` subcommands per
# behavior doc — "text" (human-readable) or "json" (one JSON array).
_FORMAT_TEXT: str = "text"
_FORMAT_JSON: str = "json"
_KNOWN_FORMATS: tuple[str, ...] = (_FORMAT_TEXT, _FORMAT_JSON)


def build_subparser(parent: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Wire the four ``todo`` sub-subcommands into ``parent``.

    The parent is the root ``bearings`` parser's subparsers action;
    this function adds ``todo`` and its own internal subparsers.
    """
    todo = parent.add_parser(
        "todo",
        help="TODO.md discipline tooling",
        description=(
            "Walk the project tree from CWD looking for TODO.md files; "
            "open / lint / add / recent operations per docs/behavior/bearings-cli.md."
        ),
    )
    todo_sub = todo.add_subparsers(
        dest="todo_subcommand",
        metavar="<todo-subcommand>",
        required=True,
    )
    _build_open_parser(todo_sub)
    _build_check_parser(todo_sub)
    _build_add_parser(todo_sub)
    _build_recent_parser(todo_sub)
    # The ``func`` attribute on the leaf parser is used by app.py's
    # dispatch — every leaf carries its own callable so the root
    # dispatch is one ``args.func(args)`` call.
    todo.set_defaults(func=_dispatch_unknown)


def _build_open_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``bearings todo open`` — list Open / In Progress entries."""
    parser = sub.add_parser(
        "open",
        help="list every Open / In Progress entry across every TODO.md in scope",
    )
    parser.add_argument(
        "--status",
        default=",".join(_OPEN_DEFAULT_STATUSES),
        help=(
            "comma-separated status filter; defaults to 'Open,In Progress'. "
            "Pass 'any' to drop the filter and surface every entry."
        ),
    )
    parser.add_argument(
        "--area",
        default=None,
        help="optional area filter; exact match against the entry's 'area:' line",
    )
    parser.add_argument(
        "--format",
        choices=_KNOWN_FORMATS,
        default=_FORMAT_TEXT,
        help="output shape (default: text)",
    )
    parser.set_defaults(func=_run_open)


def _build_check_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``bearings todo check`` — lint format + staleness."""
    parser = sub.add_parser(
        "check",
        help="lint every TODO.md for format and staleness",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=BEARINGS_TODO_CHECK_DEFAULT_MAX_AGE_DAYS,
        help=(
            "stale threshold in days; entries older than this are flagged "
            f"(default: {BEARINGS_TODO_CHECK_DEFAULT_MAX_AGE_DAYS})"
        ),
    )
    parser.add_argument(
        "--format",
        choices=_KNOWN_FORMATS,
        default=_FORMAT_TEXT,
        help="output shape (default: text)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress per-finding text lines; print summary only",
    )
    parser.set_defaults(func=_run_check)


def _build_add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``bearings todo add`` — append a properly-formatted stub."""
    parser = sub.add_parser(
        "add",
        help="append a properly-formatted stub entry",
    )
    parser.add_argument("title", help="entry title (becomes the H2 heading)")
    parser.add_argument(
        "--status",
        default=DEFAULT_TODO_STATUS,
        help=f"entry status (default: {DEFAULT_TODO_STATUS})",
    )
    parser.add_argument("--area", default=None, help="entry area classification")
    parser.add_argument("--body", default=None, help="entry body text")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("./" + BEARINGS_TODO_FILENAME),
        help=("target TODO.md path; default is ./TODO.md, created if absent"),
    )
    parser.set_defaults(func=_run_add)


def _build_recent_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """``bearings todo recent`` — entries changed in last N days."""
    parser = sub.add_parser(
        "recent",
        help="list entries that changed in the last N days",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=BEARINGS_TODO_RECENT_DEFAULT_DAYS,
        help=(f"lookback window in days (default: {BEARINGS_TODO_RECENT_DEFAULT_DAYS})"),
    )
    parser.add_argument(
        "--format",
        choices=_KNOWN_FORMATS,
        default=_FORMAT_TEXT,
        help="output shape (default: text)",
    )
    parser.set_defaults(func=_run_recent)


# --------------------------------------------------------------------------
# Sub-subcommand bodies
# --------------------------------------------------------------------------


def _run_open(args: argparse.Namespace) -> int:
    """Implement ``bearings todo open``.

    Returns the CLI exit code per behavior doc — always 0 for the
    list path (an empty list is success); the operation can only
    fail on an unreadable TODO.md, which surfaces as exit 1.
    """
    statuses = _resolve_statuses(args.status)
    try:
        entries = _gather_entries(Path.cwd())
    except OSError as exc:
        sys.stderr.write(f"bearings todo open: {exc}\n")
        return CLI_EXIT_OPERATION_FAILURE
    if statuses is not None:
        entries = filter_by_status(entries, statuses)
    if args.area is not None:
        entries = filter_by_area(entries, args.area)
    if args.format == _FORMAT_JSON:
        sys.stdout.write(_to_json(entries) + "\n")
    else:
        sys.stdout.write(_to_text(entries))
    return CLI_EXIT_OK


def _check_entries(
    entries: list[TodoEntry],
    cutoff: float,
) -> list[tuple[TodoEntry, str]]:
    """Return (entry, message) pairs for entries failing the lint rules."""
    findings: list[tuple[TodoEntry, str]] = []
    for entry in entries:
        if entry.status not in KNOWN_TODO_STATUSES:
            findings.append((entry, f"unknown status {entry.status!r}"))
        if entry.status in {"Open", "In Progress"} and entry.mtime < cutoff:
            age_days = int((time.time() - entry.mtime) // 86400)
            findings.append((entry, f"stale ({age_days} days old)"))
    return findings


def _emit_findings(findings: list[tuple[TodoEntry, str]], args: argparse.Namespace) -> None:
    """Write findings to stdout in JSON or human-readable format."""
    if args.format == _FORMAT_JSON:
        payload = [
            {
                "file": str(entry.file),
                "line": entry.line_number,
                "title": entry.title,
                "finding": message,
            }
            for entry, message in findings
        ]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        if not args.quiet:
            for entry, message in findings:
                sys.stdout.write(f"{entry.file}:{entry.line_number}: {entry.title!r} — {message}\n")
        sys.stdout.write(f"bearings todo check: {len(findings)} finding(s).\n")


def _run_check(args: argparse.Namespace) -> int:
    """Implement ``bearings todo check``.

    Lints:

    * Every entry's ``status`` is in :data:`KNOWN_TODO_STATUSES`.
    * Every Open / In Progress entry's ``mtime`` is within
      ``--max-age-days`` of now.

    Returns 0 when there are no findings; 1 when at least one finding
    surfaced (per behavior doc).
    """
    if args.max_age_days < 0:
        sys.stderr.write(
            f"bearings todo check: --max-age-days must be ≥ 0 (got {args.max_age_days})\n"
        )
        return CLI_EXIT_USAGE_ERROR
    try:
        entries = _gather_entries(Path.cwd())
    except OSError as exc:
        sys.stderr.write(f"bearings todo check: {exc}\n")
        return CLI_EXIT_OPERATION_FAILURE
    cutoff = time.time() - (args.max_age_days * 86400)
    findings = _check_entries(entries, cutoff)
    _emit_findings(findings, args)
    return CLI_EXIT_OPERATION_FAILURE if findings else CLI_EXIT_OK


def _run_add(args: argparse.Namespace) -> int:
    """Implement ``bearings todo add``.

    Appends an H2 entry to the target file (creating it if absent).
    Returns 0 on success; 1 if the target file is unwritable.
    """
    target: Path = args.file
    block = _format_stub_entry(
        title=args.title,
        status=args.status,
        area=args.area,
        body=args.body,
    )
    try:
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            # Ensure the existing file ends with a newline so the
            # appended H2 starts on its own line; pad with a blank
            # separator for readability.
            separator = "" if existing.endswith("\n") else "\n"
            target.write_text(existing + separator + "\n" + block, encoding="utf-8")
        else:
            target.write_text(f"# TODO\n\n{block}", encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"bearings todo add: {exc}\n")
        return CLI_EXIT_OPERATION_FAILURE
    sys.stdout.write(f"bearings todo add: appended to {target}: ## {args.title}\n")
    return CLI_EXIT_OK


def _run_recent(args: argparse.Namespace) -> int:
    """Implement ``bearings todo recent``.

    Lists entries whose mtime is within ``--days`` of now.
    """
    if args.days <= 0:
        sys.stderr.write(f"bearings todo recent: --days must be > 0 (got {args.days})\n")
        return CLI_EXIT_USAGE_ERROR
    try:
        entries = _gather_entries(Path.cwd())
    except OSError as exc:
        sys.stderr.write(f"bearings todo recent: {exc}\n")
        return CLI_EXIT_OPERATION_FAILURE
    cutoff = time.time() - (args.days * 86400)
    recent = [entry for entry in entries if entry.mtime >= cutoff]
    if args.format == _FORMAT_JSON:
        sys.stdout.write(_to_json(recent) + "\n")
    else:
        sys.stdout.write(_to_text(recent))
    return CLI_EXIT_OK


def _dispatch_unknown(args: argparse.Namespace) -> int:
    """Fallback when ``todo`` is invoked without a sub-subcommand.

    argparse's ``required=True`` on the subparsers prints the usage
    block to stderr automatically; this body should never be reached
    in production. Defensive return for the rare race where a
    handler attribute is missing.
    """
    del args
    sys.stderr.write("bearings todo: missing sub-subcommand\n")
    return CLI_EXIT_USAGE_ERROR


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _gather_entries(root: Path) -> list[TodoEntry]:
    """Walk + parse every TODO.md under ``root``.

    Wraps :func:`walk_todo_files` + :func:`parse_all` so the
    sub-subcommand bodies have one helper to call.
    """
    paths = walk_todo_files(root)
    return parse_all(paths)


def _resolve_statuses(arg: str) -> frozenset[str] | None:
    """Translate the ``--status`` argument into a filter set.

    ``"any"`` (case-insensitive) returns ``None`` — meaning "no
    filter, surface every status". A comma-separated list returns the
    frozenset of trimmed entries. An empty string is treated like
    ``"any"`` (defensive).
    """
    if not arg or arg.lower() == "any":
        return None
    parts = [piece.strip() for piece in arg.split(",") if piece.strip()]
    return frozenset(parts) if parts else None


def _to_json(entries: Sequence[TodoEntry]) -> str:
    """Serialise entries as a JSON array (one element per entry)."""
    payload = [
        {
            "file": str(entry.file),
            "line": entry.line_number,
            "title": entry.title,
            "status": entry.status,
            "area": entry.area,
            "summary": entry.summary,
            "mtime": entry.mtime,
        }
        for entry in entries
    ]
    return json.dumps(payload, indent=2)


def _to_text(entries: Sequence[TodoEntry]) -> str:
    """Serialise entries as one block per entry (human-readable)."""
    if not entries:
        return "(no matching TODO entries)\n"
    lines: list[str] = []
    for entry in entries:
        lines.append(f"{entry.file}:{entry.line_number}  [{entry.status}] {entry.title}")
        if entry.area:
            lines.append(f"  area: {entry.area}")
        if entry.summary:
            lines.append(f"  {entry.summary}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _format_stub_entry(
    *,
    title: str,
    status: str,
    area: str | None,
    body: str | None,
) -> str:
    """Render a stub H2 block ``## <title>`` + ``status:`` + body."""
    lines: list[str] = [f"## {title}", "", f"status: {status}"]
    if area is not None:
        lines.append(f"area: {area}")
    if body is not None:
        lines.append("")
        lines.append(body)
    lines.append("")
    return "\n".join(lines)


__all__ = ["build_subparser"]
