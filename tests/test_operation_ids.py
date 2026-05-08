"""Tests for OpenAPI operationId completeness and uniqueness.

Acceptance criteria for feature-13-005:
- Every HTTP operation in the app has a non-empty operationId.
- All operationIds are unique across the whole app.
"""

from __future__ import annotations

import pytest

from bearings.web.app import create_app


@pytest.fixture(scope="module")
def openapi_spec() -> dict:  # type: ignore[type-arg]
    """Return the parsed OpenAPI spec from a minimal test app."""
    app = create_app()
    return app.openapi()


def _iter_operations(spec: dict) -> list[tuple[str, str, str]]:  # type: ignore[type-arg]
    """Yield (path, method, operationId) for every HTTP operation in the spec."""
    results: list[tuple[str, str, str]] = []
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    for path, path_item in spec.get("paths", {}).items():
        for method, op in path_item.items():
            if method.lower() not in http_methods:
                continue
            op_id = op.get("operationId", "")
            results.append((path, method.upper(), op_id))
    return results


def test_every_operation_has_non_empty_operation_id(openapi_spec: dict) -> None:  # type: ignore[type-arg]
    """Every operation in the OpenAPI spec must have a non-empty operationId."""
    operations = _iter_operations(openapi_spec)
    assert operations, "No operations found in OpenAPI spec"

    missing = [
        f"{method} {path}" for path, method, op_id in operations if not op_id or not op_id.strip()
    ]
    assert not missing, f"Operations missing operationId ({len(missing)}):\n" + "\n".join(
        f"  {m}" for m in missing
    )


def test_operation_ids_are_unique(openapi_spec: dict) -> None:  # type: ignore[type-arg]
    """All operationIds must be unique across the app."""
    operations = _iter_operations(openapi_spec)

    seen: dict[str, list[str]] = {}
    for path, method, op_id in operations:
        if not op_id:
            continue
        seen.setdefault(op_id, []).append(f"{method} {path}")

    duplicates = {op_id: paths for op_id, paths in seen.items() if len(paths) > 1}
    assert not duplicates, f"Duplicate operationIds found ({len(duplicates)}):\n" + "\n".join(
        f"  {op_id!r}: {paths}" for op_id, paths in sorted(duplicates.items())
    )


def test_operation_id_count(openapi_spec: dict) -> None:  # type: ignore[type-arg]
    """Sanity-check: the spec must contain exactly 133 HTTP operations."""
    operations = _iter_operations(openapi_spec)
    assert len(operations) == 133, f"Expected 133 operations in OpenAPI spec, got {len(operations)}"
