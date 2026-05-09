"""Tests for the FastAPI auto-generated ``/openapi.json`` export (item 1.10).

Asserts the spec parses, every router's prefix appears in ``paths``,
the schemas component carries every Pydantic ``Out`` model, and the
spec validates against the OpenAPI 3.x shape (presence of ``openapi``
+ ``info`` + ``paths`` + ``components``).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from bearings.config.constants import (
    OPENAPI_TITLE,
    ROUTE_TAG_DIAG,
    ROUTE_TAG_FS,
    ROUTE_TAG_HEALTH,
    ROUTE_TAG_METRICS,
    ROUTE_TAG_SHELL,
    ROUTE_TAG_UPLOADS,
)
from bearings.web.app import create_app


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_openapi_endpoint_returns_json(app_client: TestClient) -> None:
    response = app_client.get("/openapi.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_openapi_spec_shape(app_client: TestClient) -> None:
    spec = app_client.get("/openapi.json").json()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == OPENAPI_TITLE
    assert spec["info"]["version"]
    assert isinstance(spec["paths"], dict)
    assert isinstance(spec["components"]["schemas"], dict)


def test_openapi_paths_count_above_threshold(app_client: TestClient) -> None:
    spec = app_client.get("/openapi.json").json()
    # 10 existing routers contribute >30 paths; item 1.10 adds 6 more
    # surfaces. Threshold deliberately conservative — a path-count
    # regression below this is a strong signal of a mounting bug.
    assert len(spec["paths"]) >= 30


def test_openapi_schemas_count_above_threshold(app_client: TestClient) -> None:
    spec = app_client.get("/openapi.json").json()
    assert len(spec["components"]["schemas"]) >= 20


def test_openapi_includes_misc_api_routes(app_client: TestClient) -> None:
    spec = app_client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/uploads" in paths
    assert "/api/fs/list" in paths
    assert "/api/fs/read" in paths
    assert "/api/shell/exec" in paths
    assert "/api/diag/server" in paths
    assert "/api/diag/sessions" in paths
    assert "/api/diag/drivers" in paths
    assert "/api/diag/quota" in paths
    assert "/api/health" in paths
    assert "/metrics" in paths


def test_openapi_misc_api_routes_carry_tags(app_client: TestClient) -> None:
    """Every misc-API operation surfaces its tag for the rendered docs."""
    spec = app_client.get("/openapi.json").json()
    expected: dict[str, str] = {
        "/api/uploads": ROUTE_TAG_UPLOADS,
        "/api/fs/list": ROUTE_TAG_FS,
        "/api/shell/exec": ROUTE_TAG_SHELL,
        "/api/diag/server": ROUTE_TAG_DIAG,
        "/api/health": ROUTE_TAG_HEALTH,
        "/metrics": ROUTE_TAG_METRICS,
    }
    for path, expected_tag in expected.items():
        node = spec["paths"][path]
        # Each path-item has at least one operation method (get/post).
        for method, op in node.items():
            if method in ("get", "post", "put", "patch", "delete"):
                assert expected_tag in op.get("tags", []), (
                    f"{method.upper()} {path} missing tag {expected_tag!r}"
                )


def test_openapi_every_operation_has_tags(app_client: TestClient) -> None:
    """No untagged operation in the entire spec — keeps the rendered
    docs grouped instead of showing a "default" bucket."""
    spec = app_client.get("/openapi.json").json()
    untagged: list[str] = []
    for path, node in spec["paths"].items():
        for method, op in node.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if not op.get("tags"):
                untagged.append(f"{method.upper()} {path}")
    assert not untagged, f"untagged operations: {untagged}"


def test_openapi_queued_endpoints_have_202_schema(app_client: TestClient) -> None:
    """202 responses on the three queued endpoints must declare a non-empty schema.

    Regression guard for the audit finding: FastAPI emits ``schema: {}`` when
    a route returns a raw ``Response`` without ``responses={202: {"model": ...}}``.
    SDK clients rely on the ``$ref`` to auto-generate typed response shapes.
    Per ``docs/behavior/prompt-endpoint.md`` §"202 semantics".
    """
    spec = app_client.get("/openapi.json").json()
    queued_paths = [
        "/api/sessions/{session_id}/prompt",
        "/api/sessions/{session_id}/regenerate",
        "/api/sessions/{session_id}/regenerate_from/{message_id}",
    ]
    for path in queued_paths:
        response_202 = spec["paths"][path]["post"]["responses"]["202"]
        schema = response_202["content"]["application/json"]["schema"]
        assert schema, f"202 schema is empty for POST {path}"
        assert "$ref" in schema or "properties" in schema, (
            f"202 schema has no $ref or properties for POST {path}: {schema!r}"
        )


def test_openapi_misc_api_schemas_referenced(app_client: TestClient) -> None:
    spec = app_client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    # Every wire-shape DTO from item 1.10 surfaces.
    expected_schemas = {
        "UploadOut",
        "UploadListOut",
        "FsEntryOut",
        "FsListOut",
        "FsReadOut",
        "ShellExecIn",
        "ShellExecOut",
        "ServerDiagOut",
        "RunnerDiagListOut",
        "DriverDiagListOut",
        "QuotaDiagOut",
        "HealthOut",
    }
    missing = expected_schemas - schemas.keys()
    assert not missing, f"missing schemas: {sorted(missing)}"
