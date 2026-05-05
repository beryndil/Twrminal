"""Deterministic mapping between Bearings session ids and SDK UUID-form ids.

The Claude Agent SDK enforces strict UUID format (``8-4-4-4-12`` lowercase
hex) for ``ClaudeAgentOptions.session_id`` and ``ClaudeAgentOptions.resume``.
Bearings session ids are ``ses_<32hex>`` (32 hex chars from
:func:`secrets.token_hex` per :mod:`bearings.db._id`). Splitting that
32-hex chunk as ``8-4-4-4-12`` produces a syntactically valid UUID — no
schema column, no UUID generation, no migration.

The mapping is bijective: the same Bearings session id always yields the
same SDK UUID, and the SDK UUID can be inverted back to the Bearings id
when the SDK calls back into Bearings (the
:class:`bearings.agent.session_store.BearingsSessionStore` adapter does
this on ``append()`` to look up the originating session row for the DB
write).

Why deterministic mapping over a stored ``sdk_session_uuid`` column:

* No schema migration needed.
* Existing sessions trivially have a derivable UUID (no backfill).
* Round-trip is a pure function — same input, same output, easy to
  unit-test.

References:

* SDK UUID validation regex: ``^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-
  [0-9a-f]{4}-[0-9a-f]{12}$`` (case-insensitive) per
  ``claude_agent_sdk/_internal/sessions.py``.
* Bearings id format: ``<prefix>_<32hex>`` per :func:`bearings.db._id.new_id`.
"""

from __future__ import annotations

import re
from typing import Final

from bearings.config.constants import SESSION_ID_PREFIX

# Bearings session id format — ``ses_<32 lowercase-hex chars>``.
_BEARINGS_SESSION_ID_RE: Final[re.Pattern[str]] = re.compile(
    rf"^{re.escape(SESSION_ID_PREFIX)}_([0-9a-f]{{32}})$",
)

# SDK UUID format (mirrors the SDK's own ``_UUID_RE`` validation regex —
# case-insensitive per the SDK's own re.IGNORECASE flag).
_SDK_UUID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# UUID component widths in hex chars (sum: 32).
_UUID_COMPONENT_WIDTHS: Final[tuple[int, int, int, int, int]] = (8, 4, 4, 4, 12)


def bearings_to_sdk_uuid(session_id: str) -> str:
    """Map ``ses_<32hex>`` → ``<8>-<4>-<4>-<4>-<12>`` UUID string.

    Args:
        session_id: A Bearings session id — must match the
            ``ses_<32 lowercase-hex chars>`` shape that
            :func:`bearings.db._id.new_id` emits.

    Returns:
        The SDK-form UUID string, suitable for
        ``ClaudeAgentOptions.session_id`` / ``ClaudeAgentOptions.resume``.

    Raises:
        ValueError: If ``session_id`` does not match the Bearings
            session-id format (e.g. wrong prefix, non-hex chars, wrong
            length). Surfaces the mismatch at the call site instead of
            silently producing a malformed UUID the SDK would reject
            with a less actionable error deep inside its CLI startup.
    """
    match = _BEARINGS_SESSION_ID_RE.match(session_id)
    if match is None:
        raise ValueError(
            f"bearings_to_sdk_uuid: session_id {session_id!r} does not match "
            f"the {SESSION_ID_PREFIX}_<32hex> Bearings format"
        )
    hex_blob = match.group(1)
    parts: list[str] = []
    cursor = 0
    for width in _UUID_COMPONENT_WIDTHS:
        parts.append(hex_blob[cursor : cursor + width])
        cursor += width
    return "-".join(parts)


def sdk_uuid_to_bearings(sdk_uuid: str) -> str:
    """Inverse of :func:`bearings_to_sdk_uuid`: SDK UUID → ``ses_<32hex>``.

    Used by :class:`bearings.agent.session_store.BearingsSessionStore`
    on the ``append()`` and ``load()`` callbacks: the SDK identifies the
    session by UUID, and the adapter must resolve it back to the Bearings
    primary key for the DB write.

    Args:
        sdk_uuid: An SDK-form UUID string — must match the
            ``8-4-4-4-12`` lowercase-hex shape (matches the SDK's own
            validation regex).

    Returns:
        The Bearings session id (``ses_<32hex>``) corresponding to
        ``sdk_uuid``.

    Raises:
        ValueError: If ``sdk_uuid`` does not match the UUID format.
    """
    if _SDK_UUID_RE.match(sdk_uuid) is None:
        raise ValueError(
            f"sdk_uuid_to_bearings: {sdk_uuid!r} does not match the "
            f"8-4-4-4-12 lowercase-hex UUID format"
        )
    hex_blob = sdk_uuid.replace("-", "")
    return f"{SESSION_ID_PREFIX}_{hex_blob}"


__all__ = [
    "bearings_to_sdk_uuid",
    "sdk_uuid_to_bearings",
]
