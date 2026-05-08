"""Differential probe v0.17.x vs v1 (master item B.2).

Calls equivalent HTTP endpoints on the live v0.17.x service (loopback,
port 8787) and the v1 service (loopback, port 8788), diffs structural
shape, and logs the deltas. Designed to run alongside
``scripts/daily_probe.py`` during the dogfood cutover window so a
silent shape regression in either build surfaces in
``~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log`` rather than
in the UI.

Probe surface
-------------

Three diff modes cover the heterogeneous response shapes:

* ``json_shape`` — the default. The probe issues ``GET <path>`` against
  both base URLs, parses the JSON, extracts a recursive type skeleton
  (dict keys + primitive type names; lists collapse to a single
  element with merged keys), and reports dotted-path deltas:
  ``missing_in_v017``, ``missing_in_v1``, ``type_mismatches``.

* ``openapi_paths`` — for ``/openapi.json``. Computes the set of
  ``(METHOD, path)`` tuples on each side and reports the symmetric
  difference. Highest-leverage probe of the surface — a stable v0.17
  reference plus the v1 export pin every endpoint rename / removal /
  addition.

* ``metric_names`` — for ``/metrics``. Parses the Prometheus exposition
  format (lines beginning ``# HELP <name> ...``) and diffs the set of
  metric names. The metric *values* are runtime-noisy and not part of
  the structural contract; only the registered names matter for shape
  equivalence.

Probes intentionally excluded:

* ``/api/quota/*`` — v1-only surface (the quota guard subsystem is new
  in v1; v0.17.x has no analogue). ``TODO.md`` carries the rationale
  on the daily-probe ``headroom`` swap.
* ``/api/checklists/*``, ``/api/uploads``, ``/api/vault`` etc. — these
  may exist on both sides but their query surfaces require known IDs
  the probe doesn't have. The diff probe stays on the unauthenticated,
  ID-free liveness surface; deeper differential coverage is the
  cutover-smoke harness's job (item 3.4).

Shape extraction rules
----------------------

* ``dict`` → ``{key: shape(value)}`` with keys sorted (so JSON output
  is reproducible).
* ``list`` → if non-empty and every element is a ``dict``, the
  skeleton is the *union* of element keys (so a list of three
  ``SessionRow`` objects with optional fields produces one merged
  skeleton). If non-empty otherwise, the first element's skeleton.
  If empty, the literal ``"<empty list>"``.
* primitives → ``type(value).__name__`` (``"str"``, ``"int"``,
  ``"float"``, ``"bool"``).
* ``None`` → ``"null"``.

The skeleton is intentionally type-only; values are discarded. Two
servers returning ``{"status": "ok"}`` and ``{"status": "OK"}`` are
shape-equivalent. Two servers returning ``{"status": "ok"}`` and
``{"status": 200}`` are not.

Exit codes
----------

* ``0`` — every probe reached both sides with an accepted status. Shape
  deltas may still be present in the log; they are informational.
* ``1`` — at least one probe failed to reach v0.17.x or v1, or the
  status code was outside the accepted set.

Shape divergence does NOT fail the run. Observing divergence is the
point: a green run with deltas is a working differential probe; a red
run means the v0.17.x or v1 service is down.

Implementation choices
----------------------

* **Stdlib only.** Same rationale as ``daily_probe.py``: must survive a
  wiped venv. ``urllib.request`` for HTTP, ``json`` for parsing, ``re``
  for the Prometheus parse.
* **Append-mode log.** JSONL records (one per probe, per side, plus
  the diff record) followed by a one-line ``SUMMARY ...`` trailer.
* **No reads of v0.17.x source.** Per ``CLAUDE.md`` §"Reference-read
  protocol", v0.17.x's API surface is discovered via the running
  service only. ``/openapi.json`` is the canonical surface listing.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal

# ---------------------------------------------------------------------------
# Probe configuration
# ---------------------------------------------------------------------------

V017_BASE_URL: Final[str] = "http://127.0.0.1:8787"
V1_BASE_URL: Final[str] = "http://127.0.0.1:8788"
PROBE_TIMEOUT_S: Final[float] = 10.0
PROBE_USER_AGENT: Final[str] = "bearings-diff-probe/1"

LOG_DIR: Final[Path] = Path("~/.local/share/bearings-v1/diff-probes").expanduser()
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d"
PROBE_LOG_RETENTION_DAYS_DEFAULT: Final[int] = 30

# Matches log filenames of the form ``YYYY-MM-DD.log`` — the only
# filenames that prune_old_logs considers for deletion.
_LOG_FILENAME_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{4}-\d{2}-\d{2})\.log$")

EXIT_SUCCESS: Final[int] = 0
EXIT_FAILURE: Final[int] = 1

LOG: Final[logging.Logger] = logging.getLogger("bearings.diff_probe")

DiffMode = Literal["json_shape", "openapi_paths", "metric_names"]


# ---------------------------------------------------------------------------
# Probe table
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DiffProbe:
    """One differential probe definition.

    ``accepted_status_codes`` is the same on both sides because the
    diff probe only fires against endpoints that should be live on
    both v0.17.x and v1. Endpoints that legitimately 404 on one side
    (e.g. ``/api/quota/current`` is v1-only) are excluded from the
    probe set rather than special-cased.
    """

    name: str
    path: str
    diff_mode: DiffMode
    accepted_status_codes: frozenset[int] = dataclasses.field(
        default_factory=lambda: frozenset({200}),
    )


PROBES: Final[tuple[DiffProbe, ...]] = (
    DiffProbe("health", "/api/health", "json_shape"),
    DiffProbe("sessions_limit_5", "/api/sessions?limit=5", "json_shape"),
    DiffProbe("tags_list", "/api/tags", "json_shape"),
    DiffProbe("openapi", "/openapi.json", "openapi_paths"),
    DiffProbe("metrics", "/metrics", "metric_names"),
)


# ---------------------------------------------------------------------------
# Side-result + probe-result dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SideResult:
    """Outcome of one HTTP call against one side (v017 or v1).

    ``body`` is ``None`` when the request never produced a response or
    when the body is not relevant to the diff mode (none of the modes
    discard the body, so this is currently always populated on success
    — the field is kept ``None``-able to make the URLError /
    TimeoutError branches explicit).
    """

    base_url: str
    status_code: int | None  # None when the request itself errored.
    elapsed_ms: int
    body: str | None
    detail: str

    def reachable(self, accepted: frozenset[int]) -> bool:
        """True iff the request landed an accepted status code."""
        return self.status_code is not None and self.status_code in accepted


@dataclasses.dataclass(frozen=True)
class DiffResult:
    """Outcome of one differential probe (both sides + diff payload)."""

    probe: DiffProbe
    v017: SideResult
    v1: SideResult
    shape_match: bool
    deltas: dict[str, object]

    @property
    def both_reachable(self) -> bool:
        accepted = self.probe.accepted_status_codes
        return self.v017.reachable(accepted) and self.v1.reachable(accepted)

    @property
    def passed(self) -> bool:
        # Shape divergence does NOT fail the probe; reachability does.
        # A diff probe that exits 0 with deltas in the log is the
        # success case (we observed divergence cleanly). Reachability
        # failure means one of the services is actually down.
        return self.both_reachable


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


def _now_utc() -> dt.datetime:
    """Current wall clock in UTC. Wrapped so tests can monkeypatch."""
    return dt.datetime.now(dt.UTC)


def _monotonic_ms() -> int:
    """Monotonically-increasing millisecond counter."""
    import time

    return time.monotonic_ns() // 1_000_000


def _execute_side(
    probe: DiffProbe,
    *,
    base_url: str,
    timeout_s: float,
) -> SideResult:
    """Run one HTTP request against one base URL.

    Catches every exception ``urllib`` and the underlying socket layer
    can raise so the diff orchestrator can build a report without an
    unhandled exception escaping. ``status_code=None`` is the sentinel
    for "the request never produced an HTTP response".
    """
    url = base_url + probe.path
    request = urllib.request.Request(
        url=url,
        headers={"User-Agent": PROBE_USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    started_ms = _monotonic_ms()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status_code = int(response.status)
            body_bytes = response.read()
    except urllib.error.HTTPError as exc:
        # >=400 — still a real HTTP response with a body. Read what's
        # available so the caller can surface server-side error shape
        # deltas if both sides happen to 4xx.
        elapsed_ms = _monotonic_ms() - started_ms
        try:
            body_bytes = exc.read()
        except (OSError, AttributeError):
            body_bytes = b""
        return SideResult(
            base_url=base_url,
            status_code=int(exc.code),
            elapsed_ms=elapsed_ms,
            body=body_bytes.decode("utf-8", errors="replace") if body_bytes else "",
            detail=f"http_error reason={exc.reason!r}",
        )
    except urllib.error.URLError as exc:
        elapsed_ms = _monotonic_ms() - started_ms
        return SideResult(
            base_url=base_url,
            status_code=None,
            elapsed_ms=elapsed_ms,
            body=None,
            detail=f"url_error reason={exc.reason!r}",
        )
    except TimeoutError as exc:
        elapsed_ms = _monotonic_ms() - started_ms
        return SideResult(
            base_url=base_url,
            status_code=None,
            elapsed_ms=elapsed_ms,
            body=None,
            detail=f"timeout after {timeout_s}s ({exc!r})",
        )
    except OSError as exc:
        elapsed_ms = _monotonic_ms() - started_ms
        return SideResult(
            base_url=base_url,
            status_code=None,
            elapsed_ms=elapsed_ms,
            body=None,
            detail=f"os_error {exc!r}",
        )

    elapsed_ms = _monotonic_ms() - started_ms
    detail = (
        f"ok status={status_code}"
        if status_code in probe.accepted_status_codes
        else f"unexpected status={status_code}"
    )
    return SideResult(
        base_url=base_url,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        body=body_bytes.decode("utf-8", errors="replace"),
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Shape extraction + diff (json_shape mode)
# ---------------------------------------------------------------------------


# Recursive JSON type. ``object`` is the practical recursion bound here;
# ``dict[str, "Shape"] | list["Shape"] | str`` would be more precise but
# mypy --strict refuses recursive type aliases in this form without a
# TypeAlias dance, and the leaf is always a str-name regardless.
Shape = object


def extract_shape(value: object) -> Shape:
    """Recursively extract a type-only skeleton.

    See module docstring §"Shape extraction rules" for the full ruleset.
    Output is intentionally JSON-serialisable so the skeleton can be
    persisted into the JSONL log alongside the probe record.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        # bool is a subclass of int — check first so True doesn't get
        # stamped as "int".
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        # Sort keys so the skeleton is reproducible across runs.
        return {str(k): extract_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        if not value:
            return "<empty list>"
        if all(isinstance(item, dict) for item in value):
            # Merge keys across every element — handles list[Row] where
            # later rows have optional fields the first row lacks.
            merged: dict[str, Shape] = {}
            for item in value:
                # ``all(isinstance(item, dict) ...)`` above pins the
                # element type for the type-checker.
                assert isinstance(item, dict)
                for k, v in sorted(item.items()):
                    if k not in merged:
                        merged[str(k)] = extract_shape(v)
            return [merged]
        return [extract_shape(value[0])]
    # Fallback for any JSON-foreign type (shouldn't happen via stdlib
    # json.loads; defensive only).
    return type(value).__name__


def diff_shapes(
    left: Shape,
    right: Shape,
    *,
    path: str = "$",
) -> dict[str, list[str]]:
    """Walk two skeletons and return the dotted-path deltas.

    The return shape is::

        {
          "missing_in_v017": [<path>, ...],   # present in v1 but not v017
          "missing_in_v1":   [<path>, ...],   # present in v017 but not v1
          "type_mismatches": [<path>: <l> vs <r>, ...],
        }

    Lists are sorted for reproducibility. The ``path`` argument is the
    JSON-pointer-ish location the recursion is currently visiting;
    callers pass ``$`` for the root.
    """
    deltas: dict[str, list[str]] = {
        "missing_in_v017": [],
        "missing_in_v1": [],
        "type_mismatches": [],
    }
    _walk_shape_diff(left, right, path=path, deltas=deltas)
    for key in deltas:
        deltas[key].sort()
    return deltas


def _walk_shape_diff(
    left: Shape,
    right: Shape,
    *,
    path: str,
    deltas: dict[str, list[str]],
) -> None:
    """In-place recursion helper for :func:`diff_shapes`."""
    if isinstance(left, dict) and isinstance(right, dict):
        # Use sorted union so output order is stable.
        all_keys = sorted(set(left.keys()) | set(right.keys()))
        for key in all_keys:
            sub_path = f"{path}.{key}"
            if key not in left:
                deltas["missing_in_v017"].append(sub_path)
            elif key not in right:
                deltas["missing_in_v1"].append(sub_path)
            else:
                _walk_shape_diff(left[key], right[key], path=sub_path, deltas=deltas)
        return
    # Lists in the skeleton always have <=1 element by construction
    # (extract_shape merges/collapses). If both are non-empty, recurse
    # on element 0. If one is "<empty list>" (a str sentinel after
    # extract_shape), the equality branch below handles it.
    if isinstance(left, list) and isinstance(right, list) and left and right:
        _walk_shape_diff(left[0], right[0], path=f"{path}[]", deltas=deltas)
        return
    if left != right:
        deltas["type_mismatches"].append(f"{path}: v017={left!r} v1={right!r}")


# ---------------------------------------------------------------------------
# OpenAPI paths diff (openapi_paths mode)
# ---------------------------------------------------------------------------


# Methods we consider "real" routes. OPTIONS / HEAD / TRACE are noise
# (FastAPI registers OPTIONS automatically; tracing them as deltas
# would drown the signal).
_OPENAPI_METHODS: Final[frozenset[str]] = frozenset(
    {"get", "post", "put", "patch", "delete"},
)


def _openapi_routes(doc: object) -> set[tuple[str, str]]:
    """Extract ``{(METHOD, path), ...}`` from an OpenAPI document.

    Tolerates a missing or non-dict ``paths`` key — a busted spec
    surfaces as an empty set, which the diff layer reports as
    "everything missing on this side". That's noisier than failing
    hard, but the diff probe is meant to be observational, not a
    schema validator.
    """
    if not isinstance(doc, dict):
        return set()
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return set()
    routes: set[tuple[str, str]] = set()
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method in methods:
            if isinstance(method, str) and method.lower() in _OPENAPI_METHODS:
                routes.add((method.upper(), str(path)))
    return routes


def diff_openapi(
    left_doc: object,
    right_doc: object,
) -> dict[str, object]:
    """Diff sets of ``(METHOD, path)`` tuples between two OpenAPI docs."""
    left_routes = _openapi_routes(left_doc)
    right_routes = _openapi_routes(right_doc)
    only_v017 = sorted(left_routes - right_routes)
    only_v1 = sorted(right_routes - left_routes)
    common = left_routes & right_routes
    return {
        "missing_in_v1": [f"{m} {p}" for m, p in only_v017],
        "missing_in_v017": [f"{m} {p}" for m, p in only_v1],
        "common_count": len(common),
        "v017_total": len(left_routes),
        "v1_total": len(right_routes),
    }


# ---------------------------------------------------------------------------
# Prometheus metric-name diff (metric_names mode)
# ---------------------------------------------------------------------------


_METRIC_HELP_LINE: Final[re.Pattern[str]] = re.compile(r"^# HELP (\S+)")


def extract_metric_names(exposition: str) -> set[str]:
    """Extract the set of metric names from a Prometheus exposition.

    Reads the ``# HELP <name> <description>`` lines, which the
    Prometheus client library emits exactly once per registered
    metric. Falls back to no-op if the exposition is empty or
    non-conformant — a malformed ``/metrics`` body shows up as an
    empty set, which the diff layer reports as everything missing.
    """
    names: set[str] = set()
    for line in exposition.splitlines():
        match = _METRIC_HELP_LINE.match(line)
        if match:
            names.add(match.group(1))
    return names


def diff_metrics(
    left_text: str,
    right_text: str,
) -> dict[str, object]:
    """Diff the metric-name sets in two Prometheus expositions."""
    left_names = extract_metric_names(left_text)
    right_names = extract_metric_names(right_text)
    return {
        "missing_in_v1": sorted(left_names - right_names),
        "missing_in_v017": sorted(right_names - left_names),
        "common_count": len(left_names & right_names),
        "v017_total": len(left_names),
        "v1_total": len(right_names),
    }


# ---------------------------------------------------------------------------
# Diff orchestration
# ---------------------------------------------------------------------------


def _build_deltas(
    probe: DiffProbe,
    v017: SideResult,
    v1: SideResult,
) -> tuple[bool, dict[str, object]]:
    """Compute the diff payload + match flag for one probe.

    ``shape_match`` is True iff both sides decoded successfully AND the
    diff payload contains no entries. If either side failed to decode
    (HTTP error, missing body, JSON parse error), ``shape_match`` is
    False and the deltas record carries the parse-failure detail so
    the log captures *why* the diff couldn't be computed.
    """
    accepted = probe.accepted_status_codes
    if not v017.reachable(accepted) or not v1.reachable(accepted):
        return False, {
            "skipped": "one or both sides unreachable",
            "v017_status": v017.status_code,
            "v1_status": v1.status_code,
        }

    if v017.body is None or v1.body is None:
        return False, {"skipped": "one or both bodies missing"}

    if probe.diff_mode == "json_shape":
        try:
            left_doc = json.loads(v017.body)
            right_doc = json.loads(v1.body)
        except json.JSONDecodeError as exc:
            return False, {"skipped": f"json_decode_error: {exc!r}"}
        deltas = diff_shapes(extract_shape(left_doc), extract_shape(right_doc))
        match = not any(deltas[key] for key in deltas)
        return match, dict(deltas)

    if probe.diff_mode == "openapi_paths":
        try:
            left_doc = json.loads(v017.body)
            right_doc = json.loads(v1.body)
        except json.JSONDecodeError as exc:
            return False, {"skipped": f"json_decode_error: {exc!r}"}
        deltas_openapi = diff_openapi(left_doc, right_doc)
        match = not deltas_openapi["missing_in_v017"] and not deltas_openapi["missing_in_v1"]
        return match, deltas_openapi

    # The ``DiffMode`` ``Literal`` exhausts the cases above + this
    # one; the type-checker treats the trailing return as unreachable,
    # which is the desired property.
    deltas_metrics = diff_metrics(v017.body, v1.body)
    match = not deltas_metrics["missing_in_v017"] and not deltas_metrics["missing_in_v1"]
    return match, deltas_metrics


def run_probe(
    probe: DiffProbe,
    *,
    v017_base_url: str,
    v1_base_url: str,
    timeout_s: float,
) -> DiffResult:
    """Run one differential probe end-to-end."""
    v017 = _execute_side(probe, base_url=v017_base_url, timeout_s=timeout_s)
    v1 = _execute_side(probe, base_url=v1_base_url, timeout_s=timeout_s)
    shape_match, deltas = _build_deltas(probe, v017, v1)
    return DiffResult(probe=probe, v017=v017, v1=v1, shape_match=shape_match, deltas=deltas)


def run_probes(
    *,
    v017_base_url: str,
    v1_base_url: str,
    timeout_s: float,
) -> tuple[DiffResult, ...]:
    """Run every probe in :data:`PROBES`."""
    return tuple(
        run_probe(
            probe,
            v017_base_url=v017_base_url,
            v1_base_url=v1_base_url,
            timeout_s=timeout_s,
        )
        for probe in PROBES
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log_path_for(now: dt.datetime, log_dir: Path) -> Path:
    return log_dir / f"{now.strftime(LOG_DATE_FORMAT)}.log"


def _result_to_jsonl(result: DiffResult, *, now: dt.datetime) -> str:
    """Serialise a :class:`DiffResult` to one JSONL record."""
    payload: dict[str, object] = {
        "ts": now.isoformat(),
        "probe": result.probe.name,
        "path": result.probe.path,
        "diff_mode": result.probe.diff_mode,
        "accepted": sorted(result.probe.accepted_status_codes),
        "v017": {
            "base_url": result.v017.base_url,
            "status": result.v017.status_code,
            "elapsed_ms": result.v017.elapsed_ms,
            "detail": result.v017.detail,
        },
        "v1": {
            "base_url": result.v1.base_url,
            "status": result.v1.status_code,
            "elapsed_ms": result.v1.elapsed_ms,
            "detail": result.v1.detail,
        },
        "shape_match": result.shape_match,
        "deltas": result.deltas,
        "passed": result.passed,
    }
    return json.dumps(payload, separators=(",", ":"))


def write_log(
    results: Sequence[DiffResult],
    *,
    now: dt.datetime,
    log_dir: Path,
) -> Path:
    """Append the per-probe JSONL records and SUMMARY trailer.

    Returns the log path. Creates ``log_dir`` if missing (mode 0700 —
    the diff probe's log records local URLs and is not meant to be
    world-readable). File opened in append mode so multiple
    invocations on the same day accumulate.
    """
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = _log_path_for(now, log_dir)

    pass_count = sum(1 for r in results if r.passed)
    fail_count = len(results) - pass_count
    match_count = sum(1 for r in results if r.shape_match)
    diverge_count = len(results) - match_count
    overall = "PASS" if fail_count == 0 else "FAIL"

    with log_path.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(_result_to_jsonl(result, now=now) + "\n")
        summary = (
            f"SUMMARY ts={now.isoformat()} overall={overall} "
            f"pass={pass_count} fail={fail_count} "
            f"match={match_count} diverge={diverge_count} "
            f"total={len(results)}"
        )
        handle.write(summary + "\n")

    return log_path


def prune_old_logs(log_dir: Path, max_age_days: int, now: dt.datetime) -> None:
    """Delete probe log files older than *max_age_days* in *log_dir*.

    Scans *log_dir* for files whose names match the ``YYYY-MM-DD.log``
    pattern and unlinks those whose date is strictly more than
    *max_age_days* before *now*.

    Special cases:

    * *max_age_days* == 0 → pruning disabled; returns immediately.
    * *log_dir* does not exist → returns without error (first run,
      dry-run, or log dir on a different mount).
    * Non-matching filenames → silently skipped (README, other logs).
    * :class:`OSError` on :func:`Path.unlink` → warning-logged and
      skipped (non-fatal; partial prune is better than a crashed probe).
    """
    if max_age_days == 0:
        return
    if not log_dir.exists():
        return
    cutoff = now.date() - dt.timedelta(days=max_age_days)
    for entry in log_dir.iterdir():
        match = _LOG_FILENAME_RE.match(entry.name)
        if match is None:
            continue
        try:
            file_date = dt.date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                entry.unlink()
                LOG.info("diff-probe log pruned: %s", entry)
            except OSError as exc:
                LOG.warning("failed to prune diff-probe log %s: %s", entry, exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def render_human(results: Sequence[DiffResult]) -> str:
    """Human-readable per-probe summary for stdout."""
    if not results:
        return "(no probes ran)"
    width = max(len(r.probe.name) for r in results)
    lines: list[str] = []
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        shape = "match" if result.shape_match else "DIVERGE"
        v017_status = "—" if result.v017.status_code is None else str(result.v017.status_code)
        v1_status = "—" if result.v1.status_code is None else str(result.v1.status_code)
        lines.append(
            f"  [{marker}] {result.probe.name:<{width}}  "
            f"v017={v017_status:>3} v1={v1_status:>3}  shape={shape:<7}  "
            f"{result.probe.path}"
        )
        if not result.passed:
            lines.append(f"         -> v017: {result.v017.detail}")
            lines.append(f"         -> v1:   {result.v1.detail}")
        elif not result.shape_match:
            lines.append(f"         -> deltas: {json.dumps(result.deltas, sort_keys=True)}")
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diff_probe",
        description=(
            "Differential probe v0.17.x vs v1. Hits equivalent "
            "endpoints on loopback:8787 and loopback:8788, diffs "
            "structural shape, and logs deltas to "
            "~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log."
        ),
    )
    parser.add_argument(
        "--v017-base-url",
        default=V017_BASE_URL,
        help=f"v0.17.x base URL (default: {V017_BASE_URL}).",
    )
    parser.add_argument(
        "--v1-base-url",
        default=V1_BASE_URL,
        help=f"v1 base URL (default: {V1_BASE_URL}).",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=LOG_DIR,
        help=f"Diff-probe log directory (default: {LOG_DIR}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=PROBE_TIMEOUT_S,
        help=f"Per-side HTTP timeout in seconds (default: {PROBE_TIMEOUT_S}).",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=PROBE_LOG_RETENTION_DAYS_DEFAULT,
        help=(
            f"Delete diff-probe logs older than this many days (default: "
            f"{PROBE_LOG_RETENTION_DAYS_DEFAULT}). "
            "Set to 0 to disable pruning entirely."
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Skip stdout output (the log file is still written).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    now = _now_utc()
    results = run_probes(
        v017_base_url=args.v017_base_url,
        v1_base_url=args.v1_base_url,
        timeout_s=args.timeout,
    )
    log_path = write_log(results, now=now, log_dir=args.log_dir)
    prune_old_logs(args.log_dir, args.max_age_days, now)

    if not args.quiet:
        print(f"bearings diff probe — {now.isoformat()}")
        print(f"v017_base_url: {args.v017_base_url}")
        print(f"v1_base_url:   {args.v1_base_url}")
        print(f"log:           {log_path}")
        print(render_human(results))

    all_passed = all(r.passed for r in results)
    return EXIT_SUCCESS if all_passed else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
