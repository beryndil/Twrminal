"""Prompt-endpoint domain service.

Per ``docs/architecture-v1.md`` §1.1.4 the agent layer owns the glue
between the route handler (``web/routes/sessions.py``) and the storage
+ runner primitives. The route's job is parse-validate-format; this
module does the work:

1. Look up the session, distinguish missing (404) / wrong-kind (400) /
   closed (409).
2. Apply the per-session sliding-window rate limit (429 + ``Retry-After``).
3. Persist the user-role message row (durable before runner picks it up
   per ``docs/behavior/prompt-endpoint.md`` §"Observability of the
   queued prompt").
4. Enqueue on the runner via :meth:`SessionRunner.enqueue_prompt`.
5. Return a small ack the route turns into the JSON envelope.

Rate-limit semantics (decided-and-documented from the constants
module):

* :data:`bearings.config.constants.PROMPT_RATE_LIMIT_WINDOW_S` — 60s
  sliding window.
* :data:`bearings.config.constants.PROMPT_RATE_LIMIT_MAX_PER_WINDOW` —
  30 prompts per session per window.

Behavior doc is silent on the exact numbers; chosen to comfortably
absorb orchestrator-driver bursts while still throttling a runaway
loop. The retry-after value is the seconds-until-the-oldest-in-window
expires, surfaced verbatim to the client per behavior doc §"Rate-limit
observable behavior".
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum

import aiosqlite

from bearings.agent.runner import RunnerFactory
from bearings.config.constants import (
    KNOWN_SESSION_KINDS,
    PROMPT_CONTENT_MAX_CHARS,
    PROMPT_RATE_LIMIT_MAX_PER_WINDOW,
    PROMPT_RATE_LIMIT_WINDOW_S,
)
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db


class PromptDispatchOutcome(Enum):
    """Tri-state result alphabet for the route layer's status mapping."""

    QUEUED = "queued"
    NOT_FOUND = "not_found"
    BAD_KIND = "bad_kind"
    CLOSED = "closed"
    EMPTY_CONTENT = "empty_content"
    CONTENT_TOO_LARGE = "content_too_large"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True)
class PromptDispatchResult:
    """Frozen result the route handler turns into an HTTP response.

    Field semantics:

    * ``outcome`` — :class:`PromptDispatchOutcome` for the status code
      mapping (route layer maps QUEUED → 202, NOT_FOUND → 404, …).
    * ``message_id`` — the persisted row's id when ``outcome`` is
      QUEUED; ``None`` otherwise.
    * ``retry_after_s`` — seconds the client should wait when
      ``outcome`` is RATE_LIMITED; ``None`` otherwise. Per
      ``docs/behavior/prompt-endpoint.md`` §"Rate-limit observable
      behavior" — surfaced as the ``Retry-After`` HTTP header.
    * ``detail`` — human-readable explanation; matches the failure
      doc's exact wording where pinned.
    """

    outcome: PromptDispatchOutcome
    message_id: str | None = None
    retry_after_s: int | None = None
    detail: str | None = None


class RateLimiter:
    """Per-session sliding-window POST rate limiter.

    Uses a per-session :class:`collections.deque` of POST timestamps
    (monotonic seconds). On each :meth:`check_and_record` call the
    deque is pruned of entries older than the window; if the remaining
    count is at the cap, the call is denied and the seconds-until-
    oldest-expires is returned. Otherwise the new timestamp is
    appended.

    Per ``docs/behavior/prompt-endpoint.md`` §"Rate-limit observable
    behavior": "The 429 does NOT cancel previously-accepted prompts in
    the queue; it only refuses the over-limit one." This limiter is
    *advisory* — the runner queue is unaffected when a request is
    denied.
    """

    def __init__(
        self,
        *,
        window_s: int = PROMPT_RATE_LIMIT_WINDOW_S,
        max_per_window: int = PROMPT_RATE_LIMIT_MAX_PER_WINDOW,
    ) -> None:
        if window_s <= 0:
            raise ValueError(f"RateLimiter.window_s must be > 0 (got {window_s})")
        if max_per_window <= 0:
            raise ValueError(f"RateLimiter.max_per_window must be > 0 (got {max_per_window})")
        self._window_s = window_s
        self._max_per_window = max_per_window
        self._timestamps: dict[str, deque[float]] = defaultdict(deque)

    def check_and_record(self, session_id: str, *, now: float | None = None) -> int | None:
        """Record an attempt; return seconds-to-retry on deny, ``None`` on allow.

        ``now`` overrides the wall clock for tests; production callers
        leave it ``None`` and the limiter reads
        :func:`time.monotonic`.
        """
        if not session_id:
            raise ValueError("RateLimiter.check_and_record: session_id must be non-empty")
        current = time.monotonic() if now is None else now
        bucket = self._timestamps[session_id]
        cutoff = current - self._window_s
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._max_per_window:
            oldest = bucket[0]
            wait = self._window_s - (current - oldest)
            # Round up so the client never retries one millisecond
            # early; ``int(wait) + 1`` satisfies the contract that the
            # next POST after waiting Retry-After seconds succeeds.
            return max(1, int(wait) + 1)
        bucket.append(current)
        return None

    def reset(self, session_id: str | None = None) -> None:
        """Drop in-memory state for one session, or all sessions.

        Test-suite hook; production code never calls this. ``None``
        clears every bucket — used by the per-app shutdown teardown.
        """
        if session_id is None:
            self._timestamps.clear()
        else:
            self._timestamps.pop(session_id, None)


async def dispatch_prompt(
    connection: aiosqlite.Connection,
    runner_factory: RunnerFactory,
    rate_limiter: RateLimiter,
    *,
    session_id: str,
    content: str,
    force_advisor: bool = False,
) -> PromptDispatchResult:
    """Apply the full prompt-endpoint pipeline.

    Steps (each surfaced as a distinct :class:`PromptDispatchOutcome`):

    1. Strip the content; reject empty.
    2. Reject content over :data:`PROMPT_CONTENT_MAX_CHARS`.
    3. Look up the session — distinguish missing / wrong-kind / closed.
    4. Rate-limit gate — per-session sliding window.
    5. Persist the user-role message row.
    6. Materialise the runner via the injected factory.
    7. Enqueue on the runner.
    8. Return :data:`PromptDispatchOutcome.QUEUED` with the persisted
       message id.

    Args:
        connection: Open aiosqlite connection.
        runner_factory: The injected
            :class:`bearings.agent.runner.RunnerFactory` Protocol.
        rate_limiter: Per-app :class:`RateLimiter` instance from
            ``app.state``.
        session_id: Target session id.
        content: User-role prompt text (raw — this function strips).
        force_advisor: When ``True``, the SDK loop prepends
            :data:`bearings.config.constants.FORCE_ADVISOR_INSTRUCTION`
            to the content it sends to ``client.query`` — but only
            when the session's routing decision has an advisor model
            configured (G9 ``/advisor`` per-turn override).

    Returns:
        :class:`PromptDispatchResult` carrying the outcome enum + the
        relevant payload fields.
    """
    stripped = content.strip()
    if not stripped:
        return PromptDispatchResult(
            outcome=PromptDispatchOutcome.EMPTY_CONTENT,
            detail="content is empty after stripping whitespace",
        )
    if len(stripped) > PROMPT_CONTENT_MAX_CHARS:
        return PromptDispatchResult(
            outcome=PromptDispatchOutcome.CONTENT_TOO_LARGE,
            detail=(
                f"content exceeds the {PROMPT_CONTENT_MAX_CHARS}-character cap "
                f"(got {len(stripped)})"
            ),
        )
    kind = await sessions_db.get_kind(connection, session_id)
    if kind is None:
        return PromptDispatchResult(
            outcome=PromptDispatchOutcome.NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    if kind not in KNOWN_SESSION_KINDS:  # pragma: no cover — schema CHECK
        return PromptDispatchResult(
            outcome=PromptDispatchOutcome.BAD_KIND,
            detail=f"session kind {kind!r} does not support prompts",
        )
    closed = await sessions_db.is_closed(connection, session_id)
    if closed:
        # Verbatim wording from behavior doc §"Failure responses".
        return PromptDispatchResult(
            outcome=PromptDispatchOutcome.CLOSED,
            detail="session is closed; reopen it before injecting a prompt.",
        )
    retry_after = rate_limiter.check_and_record(session_id)
    if retry_after is not None:
        return PromptDispatchResult(
            outcome=PromptDispatchOutcome.RATE_LIMITED,
            retry_after_s=retry_after,
            detail=(f"rate limit exceeded for this session — retry after {retry_after}s"),
        )
    message = await messages_db.insert_user(connection, session_id=session_id, content=stripped)
    runner = await runner_factory(session_id)
    runner.enqueue_prompt(message_id=message.id, content=stripped, force_advisor=force_advisor)
    return PromptDispatchResult(
        outcome=PromptDispatchOutcome.QUEUED,
        message_id=message.id,
    )


__all__ = [
    "PromptDispatchOutcome",
    "PromptDispatchResult",
    "RateLimiter",
    "dispatch_prompt",
]
