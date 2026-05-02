"""Cross-system consistency lint for Bearings v1 (master item 3.1).

Verifies four conventions that span backend + DB + frontend, none of which
existing per-language tools (ruff, mypy, eslint, svelte-check, knip) catch:

1. **Route function naming** — every FastAPI handler in
   ``src/bearings/web/routes/*.py`` must be ``snake_case`` and must start
   with one of an approved verb-prefix vocabulary. Architecture doc
   §1.1.5 pins handler bodies to "argument parsing, single domain call,
   response formatting"; the verb prefix telegraphs which of those
   shapes the handler is, so a glance at the function list previews the
   API surface without reading the decorators.

2. **Error response shape** — every ``HTTPException(...)`` call must
   pass ``detail=<string-shaped expression>``. Behavior doc
   ``docs/behavior/prompt-endpoint.md`` §"Failure responses" promises
   ``{"detail": "<message>"}`` so a curl user can read failures without
   parsing structure; a ``detail={...}`` would silently break that
   contract for some endpoints while leaving others compliant.

3. **SQL column ordering** — every ``CREATE TABLE`` in
   ``src/bearings/db/schema.sql`` must declare ``id`` as its first
   column (the schema header conventions block calls this out
   verbatim). Every ``FOREIGN KEY (...)`` must include ``ON DELETE``.
   Every ``CREATE INDEX`` name must match
   ``idx_<table>_<...>`` against its target table.

4. **Svelte component prop conventions** — every component file under
   ``frontend/src/lib/components/**/*.svelte`` that calls ``$props()``
   must declare a ``Props`` interface (or ``type Props``) and annotate
   the ``$props()`` call site with ``: Props``. The legacy Svelte-4
   ``export let`` syntax is rejected anywhere under ``frontend/src/``.

Exits 0 on a clean repo and 1 with one finding per line on stdout when
any rule fires. The CI workflow + local pre-commit hook both consume
this exit code.

The script is hermetic: no network, no environment lookups, no
subprocess. It walks the repo from ``--repo-root`` (defaulting to the
repository root resolved from ``__file__``) and emits findings as
``[rule] <relative-path>:<line>: <message>``.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Constants — every literal lives here per the project rule
# (~/.claude/coding-standards.md §"No inline literals"). Tests in
# ``tests/test_consistency_lint.py`` import these so a future tweak
# touches one place.
# ---------------------------------------------------------------------------

#: Default repo root — two levels up from ``scripts/consistency_lint.py``.
REPO_ROOT_DEFAULT: Final[Path] = Path(__file__).resolve().parents[1]

#: Subtree containing every FastAPI route module.
ROUTES_REL_DIR: Final[str] = "src/bearings/web/routes"

#: Schema file relative path.
SCHEMA_REL_PATH: Final[str] = "src/bearings/db/schema.sql"

#: Subtree containing every Svelte component.
SVELTE_COMPONENTS_REL_DIR: Final[str] = "frontend/src/lib/components"

#: Subtree the ``export let`` ban applies to.
SVELTE_SOURCES_REL_DIR: Final[str] = "frontend/src"

# --- Rule 1: route handler naming -------------------------------------------

#: Approved handler-name verb prefixes. Every public handler must split
#: on ``_`` and have its first token in this set. Adding to this set is
#: a deliberate API-shape decision — keep it small.
ROUTE_HANDLER_VERB_VOCAB: Final[frozenset[str]] = frozenset(
    {
        "attach",
        "block",
        "by",
        "check",
        "close",
        "create",
        "delete",
        "detach",
        "get",
        "indent",
        "link",
        "list",
        "move",
        "outdent",
        "override",
        "patch",
        "pause",
        "post",
        "preview",
        "prompt",
        "put",
        "refresh",
        "regenerate",
        "reopen",
        "reorder",
        "resolve",
        "resume",
        "run",
        "search",
        "skip",
        "spawn",
        "start",
        "stop",
        "uncheck",
        "unblock",
        "unlink",
        "update",
    }
)

#: Snake_case identifier shape — no camelCase, no leading underscore
#: (private helpers are not registered with ``@router``).
ROUTE_HANDLER_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*[a-z0-9]$")

#: ``@router.<verb>(...)`` decorators that mark a function as a route.
ROUTE_DECORATOR_VERBS: Final[frozenset[str]] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)

# --- Rule 2: HTTPException detail shape -------------------------------------

#: The exception class name we audit.
HTTP_EXCEPTION_NAME: Final[str] = "HTTPException"

#: The keyword whose value MUST be a string-typed expression.
HTTP_EXCEPTION_DETAIL_KW: Final[str] = "detail"

# --- Rule 3: SQL conventions ------------------------------------------------

#: Columns named here are the table's natural primary key in v1.
SQL_PRIMARY_KEY_COLUMN: Final[str] = "id"

#: ``CREATE TABLE`` regex. Captures table name + body up to the matching
#: ``);``. Multiline + DOTALL so the body can span lines.
SQL_CREATE_TABLE_RE: Final[re.Pattern[str]] = re.compile(
    r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([a-z_][a-z0-9_]*)\s*\((?P<body>.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)

#: ``CREATE INDEX`` regex. Captures index name + table name.
SQL_CREATE_INDEX_RE: Final[re.Pattern[str]] = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+"
    r"([a-z_][a-z0-9_]*)\s+ON\s+([a-z_][a-z0-9_]*)\s*\(",
    re.IGNORECASE,
)

#: ``FOREIGN KEY (col) REFERENCES other(col)`` line — captures the rest
#: of the line so we can scan for ``ON DELETE``.
SQL_FOREIGN_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+[a-z_][a-z0-9_]*\s*\([^)]*\)([^,\n]*)",
    re.IGNORECASE,
)

#: ``ON DELETE`` clause inside a foreign-key tail.
SQL_ON_DELETE_RE: Final[re.Pattern[str]] = re.compile(r"ON\s+DELETE", re.IGNORECASE)

#: Composite primary key constraint — ``PRIMARY KEY (col1, col2, ...)``.
#: Tables that declare one are join tables (e.g. ``session_tags``) and
#: are exempt from the ``id``-first column rule because they have no
#: single id column. Single-column ``PRIMARY KEY`` declarations are
#: usually inline on the column itself (``id INTEGER PRIMARY KEY``)
#: rather than as a constraint, so a constraint-form match implies
#: composite.
SQL_COMPOSITE_PK_RE: Final[re.Pattern[str]] = re.compile(
    r"PRIMARY\s+KEY\s*\(\s*[a-z_][a-z0-9_]*\s*,\s*[a-z_]",
    re.IGNORECASE,
)

#: Index-name shape. The leading ``idx_<table>_`` segment must match the
#: ``ON <table>(...)`` table; anything after it is the column-list slug.
SQL_INDEX_NAME_PREFIX: Final[str] = "idx_"

# --- Rule 4: Svelte prop conventions ----------------------------------------

#: Detects ``$props()`` usage anywhere in a component script.
SVELTE_USES_PROPS_RE: Final[re.Pattern[str]] = re.compile(r"\$props\s*\(")

#: Detects an ``interface Props`` or ``type Props =`` declaration.
SVELTE_PROPS_TYPE_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:interface|type)\s+Props\b")

#: Detects a ``: Props = $props(`` annotation (covers both destructured
#: ``const { ... }: Props = $props()`` and named ``const props: Props =
#: $props()`` shapes).
SVELTE_PROPS_ANNOTATED_RE: Final[re.Pattern[str]] = re.compile(r":\s*Props\s*=\s*\$props\s*\(")

#: Legacy Svelte-4 prop syntax — rejected codebase-wide.
SVELTE_LEGACY_EXPORT_LET_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*export\s+let\s+\w+", re.MULTILINE
)

# --- Rule keys --------------------------------------------------------------

RULE_ROUTE_NAMING: Final[str] = "route-naming"
RULE_ERROR_SHAPE: Final[str] = "error-shape"
RULE_SQL_ORDERING: Final[str] = "sql-ordering"
RULE_SVELTE_PROPS: Final[str] = "svelte-props"

ALL_RULES: Final[tuple[str, ...]] = (
    RULE_ROUTE_NAMING,
    RULE_ERROR_SHAPE,
    RULE_SQL_ORDERING,
    RULE_SVELTE_PROPS,
)

EXIT_OK: Final[int] = 0
EXIT_FINDINGS: Final[int] = 1


# ---------------------------------------------------------------------------
# Finding shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One rule violation. Rendered to stdout one per line."""

    rule: str
    path: Path
    line: int
    message: str

    def render(self, repo_root: Path) -> str:
        """Format the finding as ``[rule] <rel>:<line>: <message>``."""
        try:
            rel = self.path.relative_to(repo_root)
        except ValueError:
            rel = self.path
        return f"[{self.rule}] {rel}:{self.line}: {self.message}"


# ---------------------------------------------------------------------------
# Rule 1 — route handler naming
# ---------------------------------------------------------------------------


def _iter_route_files(repo_root: Path) -> Iterator[Path]:
    """Yield every Python module under the routes subtree."""
    routes_dir = repo_root / ROUTES_REL_DIR
    if not routes_dir.is_dir():
        return
    for path in sorted(routes_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        yield path


def _is_route_decorator(decorator: ast.expr) -> bool:
    """``True`` for ``@router.<http-verb>(...)`` decorators."""
    call = decorator
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in ROUTE_DECORATOR_VERBS:
        return False
    target = func.value
    return isinstance(target, ast.Name) and target.id == "router"


def _route_handlers(tree: ast.AST) -> Iterator[ast.AsyncFunctionDef | ast.FunctionDef]:
    """Yield every function decorated as a FastAPI route handler."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and any(
            _is_route_decorator(dec) for dec in node.decorator_list
        ):
            yield node


def check_route_handler_naming(repo_root: Path) -> list[Finding]:
    """Run rule 1 against every routes module and return findings."""
    findings: list[Finding] = []
    for path in _iter_route_files(repo_root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(
                Finding(
                    rule=RULE_ROUTE_NAMING,
                    path=path,
                    line=exc.lineno or 1,
                    message=f"unparsable: {exc.msg}",
                )
            )
            continue
        for handler in _route_handlers(tree):
            name = handler.name
            if not ROUTE_HANDLER_NAME_RE.fullmatch(name):
                findings.append(
                    Finding(
                        rule=RULE_ROUTE_NAMING,
                        path=path,
                        line=handler.lineno,
                        message=(
                            f"handler {name!r} not snake_case "
                            "(required shape: lowercase letters + digits + "
                            "underscores, must start with a letter)"
                        ),
                    )
                )
                continue
            verb = name.split("_", maxsplit=1)[0]
            if verb not in ROUTE_HANDLER_VERB_VOCAB:
                findings.append(
                    Finding(
                        rule=RULE_ROUTE_NAMING,
                        path=path,
                        line=handler.lineno,
                        message=(
                            f"handler {name!r} starts with {verb!r}, "
                            f"not in approved verb vocabulary "
                            f"{sorted(ROUTE_HANDLER_VERB_VOCAB)}"
                        ),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Rule 2 — HTTPException detail shape
# ---------------------------------------------------------------------------


def _is_string_typed(node: ast.expr) -> bool:
    """Return ``True`` when ``node`` is an expression that must be a str.

    The check is intentionally narrow:
    * ``"literal"`` and ``f"interp"`` are strings.
    * ``str(...)`` always returns a string.
    * A bare ``Name`` could be anything, but the codebase pattern is
      ``detail=str(exc)`` for exception messages and ``detail=<f-string>``
      otherwise — so an undecorated ``Name`` is rejected to keep the
      detail-shape contract explicit.
    """
    if isinstance(node, (ast.Constant, ast.JoinedStr)):
        return isinstance(node, ast.JoinedStr) or isinstance(node.value, str)
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "str":
            return True
    if isinstance(node, ast.IfExp):
        return _is_string_typed(node.body) and _is_string_typed(node.orelse)
    if isinstance(node, ast.BinOp):
        return _is_string_typed(node.left) and _is_string_typed(node.right)
    if isinstance(node, ast.BoolOp):
        # ``a or "fallback"`` — at least one operand must be string-typed.
        # The pattern in the codebase is ``result.detail or "<message>"``
        # where the LHS is ``str | None``; if it's None the fallback
        # string runs; if it's a string the LHS does. Either way the
        # detail wire value is a string.
        return any(_is_string_typed(value) for value in node.values)
    return False


def _http_exception_calls(tree: ast.AST) -> Iterator[ast.Call]:
    """Yield every ``HTTPException(...)`` call in ``tree``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == HTTP_EXCEPTION_NAME:
            yield node


def _detail_value(call: ast.Call) -> ast.expr | None:
    """Return the ``detail=`` keyword's value or ``None`` if missing."""
    for kw in call.keywords:
        if kw.arg == HTTP_EXCEPTION_DETAIL_KW:
            return kw.value
    return None


def check_error_shape(repo_root: Path) -> list[Finding]:
    """Run rule 2 against every routes module."""
    findings: list[Finding] = []
    for path in _iter_route_files(repo_root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(
                Finding(
                    rule=RULE_ERROR_SHAPE,
                    path=path,
                    line=exc.lineno or 1,
                    message=f"unparsable: {exc.msg}",
                )
            )
            continue
        for call in _http_exception_calls(tree):
            detail = _detail_value(call)
            if detail is None:
                findings.append(
                    Finding(
                        rule=RULE_ERROR_SHAPE,
                        path=path,
                        line=call.lineno,
                        message=(
                            f"{HTTP_EXCEPTION_NAME}(...) missing "
                            f"{HTTP_EXCEPTION_DETAIL_KW}= keyword "
                            "(behavior contract: every error returns "
                            "{'detail': '<message>'})"
                        ),
                    )
                )
                continue
            if not _is_string_typed(detail):
                findings.append(
                    Finding(
                        rule=RULE_ERROR_SHAPE,
                        path=path,
                        line=detail.lineno,
                        message=(
                            f"{HTTP_EXCEPTION_NAME} {HTTP_EXCEPTION_DETAIL_KW}="
                            " must be a string-typed expression "
                            "(literal, f-string, str(...), or string-typed "
                            "ternary). Detail is the contract surface a curl "
                            "user reads — don't pass dicts/lists/objects."
                        ),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Rule 3 — SQL conventions
# ---------------------------------------------------------------------------


def _line_of_offset(text: str, offset: int) -> int:
    """1-based line number of ``offset`` in ``text``."""
    return text.count("\n", 0, offset) + 1


def _table_columns_first_token(body: str) -> tuple[str, int] | None:
    """Return (first column name, line offset within body) or ``None``.

    Skips comment-only lines so a leading ``-- comment`` doesn't shadow
    the actual first column.
    """
    line_offset = 0
    for raw_line in body.splitlines(keepends=True):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("--"):
            line_offset += raw_line.count("\n")
            continue
        match = re.match(r"^([a-z_][a-z0-9_]*)\b", stripped, re.IGNORECASE)
        if match:
            return match.group(1), line_offset
        line_offset += raw_line.count("\n")
    return None


def check_sql_conventions(repo_root: Path) -> list[Finding]:
    """Run rule 3 against the canonical schema file."""
    findings: list[Finding] = []
    schema = repo_root / SCHEMA_REL_PATH
    if not schema.is_file():
        return findings
    text = schema.read_text(encoding="utf-8")

    # 3a — every CREATE TABLE has `id` as its first column UNLESS the
    # table declares a composite ``PRIMARY KEY (a, b, ...)`` constraint
    # (join tables don't have a single id).
    for match in SQL_CREATE_TABLE_RE.finditer(text):
        table = match.group(1)
        body = match.group("body")
        head_line = _line_of_offset(text, match.start())
        first = _table_columns_first_token(body)
        if first is None:
            findings.append(
                Finding(
                    rule=RULE_SQL_ORDERING,
                    path=schema,
                    line=head_line,
                    message=f"table {table!r}: empty body — could not parse first column",
                )
            )
            continue
        column_name, _ = first
        is_join_table = SQL_COMPOSITE_PK_RE.search(body) is not None
        if column_name.lower() != SQL_PRIMARY_KEY_COLUMN and not is_join_table:
            findings.append(
                Finding(
                    rule=RULE_SQL_ORDERING,
                    path=schema,
                    line=head_line,
                    message=(
                        f"table {table!r}: first column is {column_name!r}; "
                        f"convention is {SQL_PRIMARY_KEY_COLUMN!r} as PRIMARY KEY"
                    ),
                )
            )

        # 3b — every FOREIGN KEY has ON DELETE.
        body_start = match.start("body")
        for fk in SQL_FOREIGN_KEY_RE.finditer(body):
            tail = fk.group(1)
            if not SQL_ON_DELETE_RE.search(tail):
                findings.append(
                    Finding(
                        rule=RULE_SQL_ORDERING,
                        path=schema,
                        line=_line_of_offset(text, body_start + fk.start()),
                        message=(
                            f"table {table!r}: FOREIGN KEY missing ON DELETE clause "
                            "(every FK must declare its cascade behavior)"
                        ),
                    )
                )

    # 3c — every CREATE INDEX has the `idx_<table>_<...>` shape.
    for match in SQL_CREATE_INDEX_RE.finditer(text):
        index_name, table = match.group(1), match.group(2)
        head_line = _line_of_offset(text, match.start())
        expected_prefix = f"{SQL_INDEX_NAME_PREFIX}{table}_"
        if not index_name.startswith(expected_prefix):
            findings.append(
                Finding(
                    rule=RULE_SQL_ORDERING,
                    path=schema,
                    line=head_line,
                    message=(
                        f"index {index_name!r} on {table!r}: name must start "
                        f"with {expected_prefix!r} per schema convention"
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Rule 4 — Svelte component prop conventions
# ---------------------------------------------------------------------------


def _iter_svelte_components(repo_root: Path) -> Iterator[Path]:
    """Yield every component-tree Svelte file."""
    components_dir = repo_root / SVELTE_COMPONENTS_REL_DIR
    if not components_dir.is_dir():
        return
    yield from sorted(components_dir.rglob("*.svelte"))


def _iter_svelte_sources(repo_root: Path) -> Iterator[Path]:
    """Yield every Svelte file the export-let ban applies to."""
    sources_dir = repo_root / SVELTE_SOURCES_REL_DIR
    if not sources_dir.is_dir():
        return
    yield from sorted(sources_dir.rglob("*.svelte"))


def _line_of_match(text: str, match: re.Match[str]) -> int:
    """1-based line number of ``match.start()`` in ``text``."""
    return _line_of_offset(text, match.start())


def check_svelte_props(repo_root: Path) -> list[Finding]:
    """Run rule 4 against every component + source Svelte file."""
    findings: list[Finding] = []

    # 4a — components that consume props must use the typed shape.
    for path in _iter_svelte_components(repo_root):
        text = path.read_text(encoding="utf-8")
        usage = SVELTE_USES_PROPS_RE.search(text)
        if usage is None:
            continue
        if not SVELTE_PROPS_TYPE_RE.search(text):
            findings.append(
                Finding(
                    rule=RULE_SVELTE_PROPS,
                    path=path,
                    line=_line_of_match(text, usage),
                    message=(
                        "component calls $props() but does not declare "
                        "`interface Props { ... }` or `type Props = ...` "
                        "(Svelte-5 typing convention)"
                    ),
                )
            )
        if not SVELTE_PROPS_ANNOTATED_RE.search(text):
            findings.append(
                Finding(
                    rule=RULE_SVELTE_PROPS,
                    path=path,
                    line=_line_of_match(text, usage),
                    message=(
                        "$props() call site missing `: Props` annotation "
                        "(use `const { ... }: Props = $props()` or "
                        "`const props: Props = $props()`)"
                    ),
                )
            )

    # 4b — `export let` is rejected codebase-wide.
    for path in _iter_svelte_sources(repo_root):
        text = path.read_text(encoding="utf-8")
        for match in SVELTE_LEGACY_EXPORT_LET_RE.finditer(text):
            findings.append(
                Finding(
                    rule=RULE_SVELTE_PROPS,
                    path=path,
                    line=_line_of_match(text, match),
                    message=(
                        "legacy `export let` syntax is forbidden; "
                        "use the Svelte-5 `interface Props` + $props() shape"
                    ),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


RuleRunner = Callable[[Path], list[Finding]]

_RULE_RUNNERS: Final[dict[str, RuleRunner]] = {
    RULE_ROUTE_NAMING: check_route_handler_naming,
    RULE_ERROR_SHAPE: check_error_shape,
    RULE_SQL_ORDERING: check_sql_conventions,
    RULE_SVELTE_PROPS: check_svelte_props,
}


def run_rules(repo_root: Path, rules: Iterable[str]) -> list[Finding]:
    """Execute the named rules in declaration order, return all findings."""
    selected = [r for r in ALL_RULES if r in set(rules)]
    findings: list[Finding] = []
    for rule_key in selected:
        findings.extend(_RULE_RUNNERS[rule_key](repo_root))
    return findings


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser. Separated for the test surface."""
    parser = argparse.ArgumentParser(
        prog="consistency_lint",
        description=(
            "Cross-system consistency lint for the Bearings v1 rebuild. "
            "Audits route naming, error shape, SQL conventions, and "
            "Svelte prop shape. Exits 0 on clean, 1 on findings."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT_DEFAULT,
        help="repository root to lint (default: parent of scripts/)",
    )
    parser.add_argument(
        "--rule",
        action="append",
        choices=ALL_RULES,
        default=None,
        help=(
            "restrict to one or more named rules "
            "(default: every rule). May be passed multiple times."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns the process exit code."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    rules: tuple[str, ...] = tuple(args.rule) if args.rule else ALL_RULES
    findings = run_rules(args.repo_root, rules)
    for finding in findings:
        print(finding.render(args.repo_root))
    if findings:
        print(
            f"\nconsistency_lint: {len(findings)} finding(s) across {len(rules)} rule(s)",
            file=sys.stderr,
        )
        return EXIT_FINDINGS
    print(
        f"consistency_lint: clean ({len(rules)} rule(s) passed)",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — argv plumbing
    sys.exit(main())
