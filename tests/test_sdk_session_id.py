"""Unit tests for :mod:`bearings.agent.sdk_session_id`.

Verifies the deterministic mapping between Bearings session ids and the
SDK's UUID-form session identifiers. The mapping must:

* Be bijective — round-trip ``bearings → sdk_uuid → bearings`` returns
  the original input verbatim.
* Match the SDK's UUID validation regex (``8-4-4-4-12`` lowercase hex).
* Reject malformed inputs at the boundary (wrong prefix, non-hex chars,
  wrong length) instead of silently producing garbage the SDK would
  reject deeper inside its CLI startup.
"""

from __future__ import annotations

import re

import pytest

from bearings.agent.sdk_session_id import (
    bearings_to_sdk_uuid,
    sdk_uuid_to_bearings,
)
from bearings.db._id import new_id

# Mirror of the SDK's own UUID validation regex.
_SDK_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
)


def test_bearings_to_sdk_uuid_produces_valid_uuid() -> None:
    """Output must match the SDK's strict UUID format."""
    bearings_id = "ses_0123456789abcdef0123456789abcdef"
    sdk_uuid = bearings_to_sdk_uuid(bearings_id)
    assert _SDK_UUID_RE.match(sdk_uuid) is not None
    assert sdk_uuid == "01234567-89ab-cdef-0123-456789abcdef"


def test_round_trip_is_identity() -> None:
    """``sdk_uuid_to_bearings(bearings_to_sdk_uuid(x)) == x`` for valid inputs."""
    for _ in range(50):
        bearings_id = new_id("ses")
        sdk_uuid = bearings_to_sdk_uuid(bearings_id)
        recovered = sdk_uuid_to_bearings(sdk_uuid)
        assert recovered == bearings_id


def test_bearings_to_sdk_uuid_rejects_wrong_prefix() -> None:
    """Inputs not starting with ``ses_`` raise ``ValueError``."""
    with pytest.raises(ValueError, match="does not match"):
        bearings_to_sdk_uuid("msg_0123456789abcdef0123456789abcdef")


def test_bearings_to_sdk_uuid_rejects_short_input() -> None:
    """Inputs with fewer than 32 hex chars after the prefix raise."""
    with pytest.raises(ValueError, match="does not match"):
        bearings_to_sdk_uuid("ses_short")


def test_bearings_to_sdk_uuid_rejects_non_hex_chars() -> None:
    """Inputs with non-hex characters in the random part raise."""
    # ``z`` is invalid hex.
    with pytest.raises(ValueError, match="does not match"):
        bearings_to_sdk_uuid("ses_z123456789abcdef0123456789abcdef")


def test_bearings_to_sdk_uuid_rejects_uppercase_hex() -> None:
    """The Bearings format is strict lowercase; uppercase hex is rejected."""
    with pytest.raises(ValueError, match="does not match"):
        bearings_to_sdk_uuid("ses_0123456789ABCDEF0123456789abcdef")


def test_sdk_uuid_to_bearings_rejects_malformed() -> None:
    """Inputs not matching the UUID regex raise."""
    with pytest.raises(ValueError, match="does not match"):
        sdk_uuid_to_bearings("not-a-uuid")
    with pytest.raises(ValueError, match="does not match"):
        sdk_uuid_to_bearings("01234567-89ab-cdef-0123")  # too short
    # Missing hyphens.
    with pytest.raises(ValueError, match="does not match"):
        sdk_uuid_to_bearings("0123456789abcdef0123456789abcdef")


def test_sdk_uuid_to_bearings_accepts_uppercase() -> None:
    """The SDK's UUID regex is case-insensitive — uppercase UUIDs round-trip
    to lowercase Bearings ids (because the Bearings format is lowercase)."""
    sdk_uuid = "01234567-89AB-CDEF-0123-456789ABCDEF"
    recovered = sdk_uuid_to_bearings(sdk_uuid)
    # Bearings id retains the case the SDK provided. The mapping is
    # case-preserving on the round trip; uppercase SDK input yields
    # uppercase Bearings hex. The Bearings id format itself is strictly
    # lowercase (per :func:`bearings.db._id.new_id`), so the inverse
    # mapping should never receive uppercase in practice — this test
    # documents the boundary behaviour.
    assert recovered == "ses_0123456789ABCDEF0123456789ABCDEF"


def test_real_bearings_id_maps_to_uuid() -> None:
    """A freshly generated Bearings id maps to a valid SDK UUID."""
    bearings_id = new_id("ses")
    sdk_uuid = bearings_to_sdk_uuid(bearings_id)
    assert _SDK_UUID_RE.match(sdk_uuid) is not None
