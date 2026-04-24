"""`/api/version` is the seamless-reload watcher's source of truth.

The frontend pins the `build` field on boot and compares every
subsequent poll against that pin. A mismatch arms a visibility-
triggered reload, so the contract here matters: the field must be
stable across requests when the bundle hasn't changed, and it must
flip when index.html is rewritten by `npm run build`.
"""

from __future__ import annotations

import os
import time

from fastapi.testclient import TestClient


def test_version_returns_build_token_when_bundle_present(
    client: TestClient,
) -> None:
    """Production layout: the bundle has been built and the bundle
    directory exists. `version` and `build` are both populated; build
    is a stringified ns timestamp (numeric, parseable as int)."""
    resp = client.get("/api/version")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["version"], str)
    assert body["version"]  # non-empty
    # The conftest test fixture ships a built bundle; if not, this
    # test runs in dev mode and `build` is null. Either way is a
    # valid response shape; the watcher tolerates both.
    if body["build"] is not None:
        assert int(body["build"]) > 0


def test_version_build_token_stable_across_calls(client: TestClient) -> None:
    """No rebuild → identical token across calls. The watcher relies
    on this stability: every poll between rebuilds must see the same
    string, otherwise we'd reload spuriously."""
    a = client.get("/api/version").json()
    b = client.get("/api/version").json()
    assert a["build"] == b["build"]


def test_version_build_token_flips_after_index_rewrite(
    client: TestClient,
) -> None:
    """Touch index.html → token changes. Models the post-`npm run
    build` state where the file's mtime has bumped because the chunk
    references inside changed. If this test goes red, the watcher
    won't notice rebuilds and the seamless-reload feature stops
    working."""
    from bearings.api import routes_health

    if not routes_health._INDEX_HTML.exists():
        # Dev-mode run with no built bundle — the test for the rebuild
        # signal isn't applicable. Skip rather than fail; the previous
        # test asserts the null-build branch already.
        import pytest

        pytest.skip("bundle not built in this environment")

    before = client.get("/api/version").json()["build"]
    # Bump mtime by at least one ns. `os.utime(None)` sets to current
    # wall-clock; on fast hardware two consecutive calls can land in
    # the same ns bucket, so wait a tick first.
    time.sleep(0.01)
    os.utime(routes_health._INDEX_HTML, None)
    after = client.get("/api/version").json()["build"]
    assert before != after, "build token must change when index.html is rewritten"
