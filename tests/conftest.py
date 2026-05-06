"""Shared pytest fixtures.

Pytest auto-discovers fixtures in ``conftest.py``: any fixture defined
here is available to every test file in the same directory or below,
without explicit import. The fixtures here are all ``autouse=True`` —
they run for every test in the suite, no opt-in needed. Their job is
**test isolation**: prevent the host shell environment, a stray
``.env`` file in the repo root, or the developer's real
``~/.local/share/bearings`` from leaking into a test run.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_bearings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip BEARINGS_* environment variables for the duration of each test.

    Without this, a developer with ``BEARINGS_LOG_LEVEL=DEBUG`` exported
    in their shell would get different test results than CI. monkeypatch
    handles automatic restoration when the test ends.
    """
    for key in list(os.environ):
        if key.startswith("BEARINGS_"):
            monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run each test from a fresh temp directory.

    pydantic-settings reads ``.env`` relative to ``cwd``. Running tests
    from the repo root would consult the repo's ``.env`` if one exists.
    Switching to a clean ``tmp_path`` per test guarantees hermeticity.
    """
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point ``settings.data_dir`` at a per-test temp directory.

    Without this, tests that construct ``Settings()`` resolve
    ``data_dir`` to the developer's real ``~/.local/share/bearings``,
    and any test that exercises the migration runner would write into
    it. Setting ``BEARINGS_DATA_DIR`` overrides the default-factory
    via the same env-var mechanism production uses.
    """
    monkeypatch.setenv("BEARINGS_DATA_DIR", str(tmp_path / "data"))
    yield
