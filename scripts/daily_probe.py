"""Daily health probe for the running Bearings v1 instance.

Hits a small fixed set of endpoints on the live ``bearings-v1.service``
(loopback, port 8788) and writes a per-day log under
``~/.local/share/bearings-v1/probes/YYYY-MM-DD.log``. Designed to be
invoked by a systemd-user timer (``config/bearings-v1-probe.timer``)
or a cron entry — see ``CHANGELOG.md`` for the systemd install
sequence.

Probe surface
-------------

The done-when criteria for master item B.1 names five endpoints:

* ``/api/health``                — service liveness
* ``/api/sessions?limit=5``      — session-list smoke (the ``limit``
  param is currently a no-op — the sessions route returns the full
  list regardless of query params; the URL is preserved verbatim per
  the done-when text so a future ``limit`` implementation lights up
  the probe automatically)
* ``/api/usage/headroom``        — see swap below
* ``/openapi.json``              — schema exporter
* ``/metrics``                   — Prometheus exposition

``/api/usage/headroom`` does not exist in v1's route surface (verified
against the OpenAPI export at the time of writing). The closest
semantic equivalent is ``/api/quota/current`` (the "current quota
state" surface that the inspector's Usage subsection drives the 7-day
headroom chart from, alongside ``/api/quota/history``). We probe both
``/api/quota/current`` and ``/api/quota/history`` to cover the
headroom *intent* without inventing a new endpoint. ``/api/quota/current``
returns 404 when no quota snapshot has ever been recorded — that's
the documented "never polled" branch (per ``docs/behavior/routing.md``
§"Quota guard"), so we accept ``{200, 404}`` as PASS for that probe.
``TODO.md`` carries the entry to revisit if a literal ``headroom``
endpoint ever lands.

Implementation choices
----------------------

* **Stdlib only.** No httpx, no third-party deps. The probe must
  survive a venv that has been wiped, an interrupted ``uv sync``, or
  the project being checked out cold. ``urllib.request`` covers every
  call site; JSON parsing uses the stdlib ``json`` module.
* **Append-mode log.** Each invocation writes JSONL records (one per
  probe) followed by a one-line ``SUMMARY ...`` trailer. Re-running
  on the same day accumulates rather than truncating, so an ad-hoc
  manual probe doesn't erase the morning's scheduled run.
* **Exit code mirrors PASS/FAIL.** 0 if every probe returned an
  accepted status; 1 otherwise. The systemd unit's ``Restart=`` is
  off (it's a oneshot timer service), so a non-zero exit surfaces in
  ``journalctl --user -u bearings-v1-probe`` and the timer's
  ``LastTriggerUSec`` lineage without auto-retrying.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Probe configuration
# ---------------------------------------------------------------------------

PROBE_HOST: Final[str] = "127.0.0.1"
PROBE_PORT: Final[int] = 8788
PROBE_BASE_URL: Final[str] = f"http://{PROBE_HOST}:{PROBE_PORT}"
PROBE_TIMEOUT_S: Final[float] = 10.0
PROBE_RETRY_ATTEMPTS: Final[int] = 3
PROBE_RETRY_BACKOFF_S: Final[float] = 1.0
PROBE_USER_AGENT: Final[str] = "bearings-v1-daily-probe/1"

LOG_DIR: Final[Path] = Path("~/.local/share/bearings-v1/probes").expanduser()
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d"

EXIT_SUCCESS: Final[int] = 0
EXIT_FAILURE: Final[int] = 1

LOG: Final[logging.Logger] = logging.getLogger("bearings.daily_probe")


# ---------------------------------------------------------------------------
# Probe table
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Probe:
    """One GET probe.

    ``accepted_status_codes`` is a frozenset so a probe with more than
    one well-defined PASS shape (e.g. ``/api/quota/current`` returns
    404 before the first snapshot is recorded) can declare every
    accepted code.
    """

    name: str
    path: str
    accepted_status_codes: frozenset[int]


PROBES: Final[tuple[Probe, ...]] = (
    Probe("health", "/api/health", frozenset({200})),
    Probe("sessions_limit_5", "/api/sessions?limit=5", frozenset({200})),
    # /api/usage/headroom does not exist; /api/quota/current +
    # /api/quota/history together cover the headroom-conceptual
    # surface (the inspector's 7-day headroom chart reads from
    # /api/quota/history). See module docstring "Probe surface" for
    # the swap rationale.
    Probe("quota_current", "/api/quota/current", frozenset({200, 404})),
    Probe("quota_history", "/api/quota/history", frozenset({200})),
    Probe("openapi", "/openapi.json", frozenset({200})),
    Probe("metrics", "/metrics", frozenset({200})),
)


# ---------------------------------------------------------------------------
# Probe execution
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ProbeResult:
    """Outcome of one probe."""

    probe: Probe
    status_code: int | None  # None when the request itself errored.
    elapsed_ms: int
    detail: str

    @property
    def passed(self) -> bool:
        return self.status_code is not None and self.status_code in self.probe.accepted_status_codes


def _now_utc() -> dt.datetime:
    """Return the current wall clock in UTC. Wrapped so tests can monkeypatch."""
    return dt.datetime.now(dt.UTC)


def _monotonic_ms() -> int:
    """Return a monotonically-increasing millisecond counter."""
    # time.monotonic_ns avoids float precision loss; we round to ms.
    return time.monotonic_ns() // 1_000_000


def _attempt_probe(
    probe: Probe,
    request: urllib.request.Request,
    *,
    timeout_s: float,
    attempt: int,
    max_attempts: int,
) -> tuple[ProbeResult, bool]:
    """Execute one HTTP request for *probe*; return ``(result, retriable)``.

    ``retriable`` is ``True`` when the failure should trigger a retry:
    URLError, TimeoutError, OSError, or HTTPError whose status code is
    **outside** ``probe.accepted_status_codes`` (e.g. HTTP 503 during a
    graceful service restart). An accepted HTTPError (e.g. 404 for the
    never-polled ``/api/quota/current``) is a PASS and sets
    ``retriable=False``.
    """
    sfx = f" (attempt {attempt}/{max_attempts})" if attempt > 1 else ""
    started_ms = _monotonic_ms()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status_code: int = int(response.status)
            # Read+discard body so the connection is released cleanly.
            response.read()
    except urllib.error.HTTPError as exc:
        elapsed_ms = _monotonic_ms() - started_ms
        code = int(exc.code)
        base_detail = f"http_error reason={exc.reason!r}"
        if code in probe.accepted_status_codes:
            return ProbeResult(
                probe=probe,
                status_code=code,
                elapsed_ms=elapsed_ms,
                detail=f"{base_detail}{sfx}",
            ), False
        return ProbeResult(
            probe=probe,
            status_code=code,
            elapsed_ms=elapsed_ms,
            detail=base_detail,
        ), True
    except urllib.error.URLError as exc:
        elapsed_ms = _monotonic_ms() - started_ms
        return ProbeResult(
            probe=probe,
            status_code=None,
            elapsed_ms=elapsed_ms,
            detail=f"url_error reason={exc.reason!r}",
        ), True
    except TimeoutError as exc:
        elapsed_ms = _monotonic_ms() - started_ms
        return ProbeResult(
            probe=probe,
            status_code=None,
            elapsed_ms=elapsed_ms,
            detail=f"timeout after {timeout_s}s ({exc!r})",
        ), True
    except OSError as exc:
        elapsed_ms = _monotonic_ms() - started_ms
        return ProbeResult(
            probe=probe,
            status_code=None,
            elapsed_ms=elapsed_ms,
            detail=f"os_error {exc!r}",
        ), True
    elapsed_ms = _monotonic_ms() - started_ms
    detail = (
        f"ok status={status_code}{sfx}"
        if status_code in probe.accepted_status_codes
        else f"unexpected status={status_code}{sfx}"
    )
    return ProbeResult(
        probe=probe,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        detail=detail,
    ), False


def _execute_probe(
    probe: Probe,
    *,
    base_url: str,
    timeout_s: float,
    retry_attempts: int = PROBE_RETRY_ATTEMPTS,
    retry_backoff_s: float = PROBE_RETRY_BACKOFF_S,
) -> ProbeResult:
    """Run one probe via ``urllib.request`` with retry-before-FAIL semantics.

    Attempts the probe up to *retry_attempts* times, sleeping
    *retry_backoff_s* seconds between each attempt. Retriable conditions:
    URLError, TimeoutError, OSError, and HTTPError outside
    ``probe.accepted_status_codes``. ``status_code=None`` is the sentinel
    for "the request never produced an HTTP response".
    """
    url = base_url + probe.path
    request = urllib.request.Request(
        url=url,
        headers={"User-Agent": PROBE_USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    last_failure: ProbeResult | None = None
    for attempt in range(1, retry_attempts + 1):
        result, retriable = _attempt_probe(
            probe,
            request,
            timeout_s=timeout_s,
            attempt=attempt,
            max_attempts=retry_attempts,
        )
        if not retriable:
            return result
        last_failure = result
        if attempt < retry_attempts:
            time.sleep(retry_backoff_s)
    assert last_failure is not None
    return dataclasses.replace(
        last_failure,
        detail=f"{last_failure.detail} (exhausted {retry_attempts}/{retry_attempts} attempts)",
    )


def run_probes(
    *,
    base_url: str,
    timeout_s: float,
    retry_attempts: int = PROBE_RETRY_ATTEMPTS,
    retry_backoff_s: float = PROBE_RETRY_BACKOFF_S,
) -> tuple[ProbeResult, ...]:
    """Run every probe in :data:`PROBES` and return the results."""
    return tuple(
        _execute_probe(
            p,
            base_url=base_url,
            timeout_s=timeout_s,
            retry_attempts=retry_attempts,
            retry_backoff_s=retry_backoff_s,
        )
        for p in PROBES
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log_path_for(now: dt.datetime, log_dir: Path) -> Path:
    return log_dir / f"{now.strftime(LOG_DATE_FORMAT)}.log"


def _result_to_jsonl(result: ProbeResult, *, now: dt.datetime) -> str:
    """Serialise a :class:`ProbeResult` to one JSONL record."""
    payload: dict[str, object] = {
        "ts": now.isoformat(),
        "probe": result.probe.name,
        "path": result.probe.path,
        "status": result.status_code,
        "accepted": sorted(result.probe.accepted_status_codes),
        "elapsed_ms": result.elapsed_ms,
        "passed": result.passed,
        "detail": result.detail,
    }
    return json.dumps(payload, separators=(",", ":"))


def write_log(
    results: Sequence[ProbeResult],
    *,
    now: dt.datetime,
    log_dir: Path,
) -> Path:
    """Append the per-probe JSONL records and the SUMMARY trailer.

    Returns the log path that was written. Creates ``log_dir`` if it
    doesn't exist (mode 0700 — the probe log records local URLs and
    is not meant to be world-readable). The file is opened in append
    mode so multiple invocations on the same day accumulate.
    """
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = _log_path_for(now, log_dir)

    pass_count = sum(1 for r in results if r.passed)
    fail_count = len(results) - pass_count
    overall = "PASS" if fail_count == 0 else "FAIL"

    with log_path.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(_result_to_jsonl(result, now=now) + "\n")
        summary = (
            f"SUMMARY ts={now.isoformat()} overall={overall} "
            f"pass={pass_count} fail={fail_count} total={len(results)}"
        )
        handle.write(summary + "\n")

    return log_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def render_human(results: Sequence[ProbeResult]) -> str:
    """Human-readable per-probe summary for stdout."""
    if not results:
        return "(no probes ran)"
    width = max(len(r.probe.name) for r in results)
    lines: list[str] = []
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        status = "—" if result.status_code is None else str(result.status_code)
        lines.append(
            f"  [{marker}] {result.probe.name:<{width}}  "
            f"status={status:>3}  {result.elapsed_ms:>4}ms  {result.probe.path}"
        )
        if not result.passed:
            lines.append(f"         -> {result.detail}")
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily_probe",
        description=(
            "Daily health probe for the running bearings-v1.service. "
            "Hits a fixed set of endpoints on loopback:8788 and logs "
            "the result to ~/.local/share/bearings-v1/probes/YYYY-MM-DD.log."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=PROBE_BASE_URL,
        help=f"Base URL to probe (default: {PROBE_BASE_URL}).",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=LOG_DIR,
        help=f"Probe log directory (default: {LOG_DIR}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=PROBE_TIMEOUT_S,
        help=f"Per-probe HTTP timeout in seconds (default: {PROBE_TIMEOUT_S}).",
    )
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=PROBE_RETRY_ATTEMPTS,
        help=(f"Number of probe attempts before recording FAIL (default: {PROBE_RETRY_ATTEMPTS})."),
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=PROBE_RETRY_BACKOFF_S,
        help=(f"Seconds to sleep between retry attempts (default: {PROBE_RETRY_BACKOFF_S})."),
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
        base_url=args.base_url,
        timeout_s=args.timeout,
        retry_attempts=args.retry_attempts,
        retry_backoff_s=args.retry_backoff,
    )
    log_path = write_log(results, now=now, log_dir=args.log_dir)

    if not args.quiet:
        print(f"bearings-v1 daily probe — {now.isoformat()}")
        print(f"base_url: {args.base_url}")
        print(f"log:      {log_path}")
        print(render_human(results))

    all_passed = all(r.passed for r in results)
    return EXIT_SUCCESS if all_passed else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
