"""Unit tests for bearings_dir/contract.py.

Acceptance-criteria coverage:

* AC-contract-1  ManifestModel constructs with valid fields.
* AC-contract-2  ManifestModel rejects wrong schema_version (version-mismatch).
* AC-contract-3  ManifestModel rejects empty directory / primary_marker / brief.
* AC-contract-4  StateModel constructs with all-optional fields absent.
* AC-contract-5  StateModel rejects wrong schema_version.
* AC-contract-6  PendingOpModel constructs; rejects empty description.
* AC-contract-7  PendingModel constructs with empty ops dict.
* AC-contract-8  validate_schema_version raises ValueError on mismatch.
* AC-contract-9  load_manifest / load_state / load_pending parse valid dicts.
* AC-contract-10 load_manifest raises on bad schema_version (version-mismatch
                 edge case per acceptance criteria).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bearings.bearings_dir.contract import (
    SCHEMA_VERSION,
    ManifestModel,
    PendingModel,
    PendingOpModel,
    StateModel,
    load_manifest,
    load_pending,
    load_state,
    validate_schema_version,
)
from bearings.config.constants import BEARINGS_DIR_SCHEMA_VERSION

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _valid_manifest_dict() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "directory": "/home/user/projects/foo",
        "primary_marker": ".git",
        "created_at": _NOW,
        "brief": "Directory: /home/user/projects/foo\nPrimary marker: .git",
    }


# ---------------------------------------------------------------------------
# AC-contract-1  ManifestModel — happy path
# ---------------------------------------------------------------------------


def test_manifest_model_constructs() -> None:
    m = ManifestModel(**_valid_manifest_dict())  # type: ignore[arg-type]
    assert m.directory == "/home/user/projects/foo"
    assert m.primary_marker == ".git"
    assert m.schema_version == BEARINGS_DIR_SCHEMA_VERSION


def test_manifest_model_is_frozen() -> None:
    m = ManifestModel(**_valid_manifest_dict())  # type: ignore[arg-type]
    with pytest.raises((AttributeError, TypeError, ValidationError)):
        m.brief = "new brief"


# ---------------------------------------------------------------------------
# AC-contract-2  ManifestModel — version mismatch
# ---------------------------------------------------------------------------


def test_manifest_model_rejects_wrong_schema_version() -> None:
    data = _valid_manifest_dict()
    data["schema_version"] = 999
    with pytest.raises(ValidationError, match="schema_version"):
        ManifestModel(**data)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-contract-3  ManifestModel — empty required strings
# ---------------------------------------------------------------------------


def test_manifest_model_rejects_empty_directory() -> None:
    data = _valid_manifest_dict()
    data["directory"] = ""
    with pytest.raises(ValidationError, match="directory"):
        ManifestModel(**data)  # type: ignore[arg-type]


def test_manifest_model_rejects_empty_primary_marker() -> None:
    data = _valid_manifest_dict()
    data["primary_marker"] = ""
    with pytest.raises(ValidationError, match="primary_marker"):
        ManifestModel(**data)  # type: ignore[arg-type]


def test_manifest_model_rejects_empty_brief() -> None:
    data = _valid_manifest_dict()
    data["brief"] = ""
    with pytest.raises(ValidationError, match="brief"):
        ManifestModel(**data)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-contract-4  StateModel — optional fields default to None
# ---------------------------------------------------------------------------


def test_state_model_defaults_optional_fields_to_none() -> None:
    s = StateModel(schema_version=SCHEMA_VERSION)
    assert s.last_session_id is None
    assert s.last_seen_at is None


def test_state_model_accepts_all_fields() -> None:
    s = StateModel(
        schema_version=SCHEMA_VERSION,
        last_session_id="ses_abc",
        last_seen_at=_NOW,
    )
    assert s.last_session_id == "ses_abc"
    assert s.last_seen_at == _NOW


# ---------------------------------------------------------------------------
# AC-contract-5  StateModel — version mismatch
# ---------------------------------------------------------------------------


def test_state_model_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        StateModel(schema_version=0)


# ---------------------------------------------------------------------------
# AC-contract-6  PendingOpModel
# ---------------------------------------------------------------------------


def test_pending_op_model_constructs() -> None:
    op = PendingOpModel(description="Deploy", started_at="2026-01-01T00:00:00Z")
    assert op.description == "Deploy"


def test_pending_op_model_rejects_empty_description() -> None:
    with pytest.raises(ValidationError, match="description"):
        PendingOpModel(description="", started_at="2026-01-01T00:00:00Z")


def test_pending_op_model_allows_extra_fields() -> None:
    op = PendingOpModel.model_validate(
        {"description": "Deploy", "started_at": "2026-01-01T00:00:00Z", "extra_flag": True}
    )
    assert op.model_extra == {"extra_flag": True}


# ---------------------------------------------------------------------------
# AC-contract-7  PendingModel
# ---------------------------------------------------------------------------


def test_pending_model_empty_ops() -> None:
    p = PendingModel()
    assert p.ops == {}


def test_pending_model_with_ops() -> None:
    p = PendingModel(
        ops={
            "deploy": PendingOpModel(
                description="Deploy to prod",
                started_at="2026-01-01T00:00:00Z",
            )
        }
    )
    assert "deploy" in p.ops
    assert p.ops["deploy"].description == "Deploy to prod"


# ---------------------------------------------------------------------------
# AC-contract-8  validate_schema_version helper
# ---------------------------------------------------------------------------


def test_validate_schema_version_passes_for_correct_version() -> None:
    validate_schema_version({"schema_version": SCHEMA_VERSION})  # no exception


def test_validate_schema_version_raises_for_mismatch() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        validate_schema_version({"schema_version": 0})


def test_validate_schema_version_raises_for_missing() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        validate_schema_version({})


# ---------------------------------------------------------------------------
# AC-contract-9  load_* helpers — happy path
# ---------------------------------------------------------------------------


def test_load_manifest_happy_path() -> None:
    data = _valid_manifest_dict()
    m = load_manifest(data)
    assert m.directory == "/home/user/projects/foo"


def test_load_state_happy_path() -> None:
    data = {"schema_version": SCHEMA_VERSION}
    s = load_state(data)
    assert s.last_session_id is None


def test_load_pending_empty() -> None:
    p = load_pending({})
    assert p.ops == {}


def test_load_pending_with_ops() -> None:
    data = {
        "ops": {
            "review": {
                "description": "Code review",
                "started_at": "2026-01-01T00:00:00Z",
            }
        }
    }
    p = load_pending(data)
    assert "review" in p.ops


# ---------------------------------------------------------------------------
# AC-contract-10  load_manifest raises on bad schema_version (version-mismatch
#                 edge case per acceptance criteria)
# ---------------------------------------------------------------------------


def test_load_manifest_raises_on_version_mismatch() -> None:
    data = _valid_manifest_dict()
    data["schema_version"] = 999
    with pytest.raises(ValidationError, match="schema_version"):
        load_manifest(data)


def test_load_state_raises_on_version_mismatch() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        load_state({"schema_version": 999})
