"""Wire types and tunables for `SessionRunner`.

Lives in its own module so `runner.py` keeps to coordination logic and
this module captures the shapes the worker queue, ring buffer, and
keepalive cadence agree on. Nothing here imports the runner — these
types are leaves.

Public surface re-exports through `bearings.agent.runner` for backwards
compatibility (tests + `ws_agent` import `_Envelope`, `RING_MAX`, and
friends from there).
"""

from __future__ import annotations

from typing import Any, Literal

import orjson

# How many recent events to keep for reconnect replay. Five thousand
# comfortably covers a long multi-tool turn where each token is a
# separate event; old entries roll off the front. If a client is away
# longer than this buffer's window, it misses intermediate tokens but
# still catches the final `message_complete` (and the completed
# assistant message is in the DB either way).
RING_MAX = 5000

# Per-subscriber WS queue cap. A live WebSocket sender drains this in
# real time, so the queue normally sits at 0-1 events. The cap exists
# to keep memory bounded if a subscriber stalls (network back-pressure,
# malicious slow-loris client). 500 matches `SessionsBroker
# .SUBSCRIBER_QUEUE_MAX`; at ~2 KB/event the worst-case per-subscriber
# footprint is ~1 MB — small enough that a stalled tab (or a hostile
# slow-loris) can't balloon runner memory. On overflow the subscriber
# is evicted and its WebSocket handler will notice the closure on the
# next send; the client reconnects with `since_seq` and replays the
# missed window from the runner's `RING_MAX` ring buffer (which is
# 10x larger so reconnect-replay still covers a long tool-heavy turn).
SUBSCRIBER_QUEUE_MAX = 500

# Cadence for `ToolProgress` keepalive events emitted while a tool call
# is still running. Covers the "SDK surfaces nothing for tens of
# seconds during a Task/Agent sub-agent" class of silence that would
# otherwise read as a dead spinner. At 3s per tick per in-flight tool,
# a turn with up to ~3 concurrent tools stays under 1 msg/sec fan-out
# — comfortably below anything the WS + reducer have to worry about.
# Events are fan-out only (never persisted to the ring buffer), so
# this cadence does not eat the 5000-entry replay window either.
TOOL_PROGRESS_INTERVAL_S = 3.0


# Sentinel queued into `_prompts` by `shutdown()` so the worker exits
# its blocking `get()` and winds down cleanly.
class _Shutdown:
    pass


_SHUTDOWN = _Shutdown()


class _Replay:
    """Queue marker for a prompt that was recovered from a prior
    runner's unfinished turn. The difference from a plain string: the
    user row is already in the `messages` table — `_execute_turn` must
    NOT insert it a second time or history will show the user's prompt
    twice after a restart-mid-turn event."""

    __slots__ = ("prompt", "attachments")

    def __init__(self, prompt: str, attachments: list[dict[str, Any]] | None) -> None:
        self.prompt = prompt
        # Parsed list (or None) — the replay row carries the same
        # token→path mapping so `_execute_turn` can re-substitute
        # exactly what the SDK saw on the original interrupted turn.
        self.attachments = attachments


class _Submit:
    """Queue marker for a freshly submitted prompt carrying terminal-
    style `[File N]` attachments. Plain strings still work for
    attachment-free prompts — the worker treats them identically — but
    once a prompt has attachments we need to ride them through the
    queue so `_execute_turn` can both persist the sidecar and build the
    substituted SDK text. Kept separate from `_Replay` so the replay
    path's "don't re-persist user row" rule stays untangled from
    attachment handling."""

    __slots__ = ("prompt", "attachments")

    def __init__(self, prompt: str, attachments: list[dict[str, Any]]) -> None:
        self.prompt = prompt
        self.attachments = attachments


RunnerStatus = Literal["idle", "running"]


class _Envelope:
    """Event plus its monotonically-increasing sequence number.

    Subscribers receive envelopes so they can update their own
    `lastSeq` cursor for future reconnects. Using a small class rather
    than a tuple to keep attribute access obvious at call sites.

    `wire` holds the pre-encoded text-frame JSON (payload merged with
    `_seq`). Encoding the frame once at emit time instead of per
    subscriber avoids an `orjson.dumps(...).decode()` hop on every
    WebSocket send — non-trivial on tool-heavy turns where a single
    event fans out to N tabs plus buffered replay. `payload` is still
    exposed for tests and for the approval/session-broker code paths
    that peek at event types without serializing.
    """

    __slots__ = ("seq", "payload", "wire")

    def __init__(self, seq: int, payload: dict[str, Any]) -> None:
        self.seq = seq
        self.payload = payload
        # Merge `_seq` into the frame once. Subscribers + replay use
        # `env.wire` directly; see `ws_agent._forward_events`.
        self.wire = orjson.dumps({**payload, "_seq": seq}).decode()
