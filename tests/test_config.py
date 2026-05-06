"""Tests for bearings.config.

The conftest fixtures ``_isolate_app_env`` and ``_isolate_cwd`` give us
a hermetic environment per test: no BEARINGS_* vars from the host shell,
and no .env file in cwd. So bare ``Settings()`` reads only the env
vars we explicitly set with monkeypatch.
"""

import pytest
from pydantic import ValidationError

from bearings.config import Settings


def test_settings_defaults_when_no_env() -> None:
    """Without env vars, Settings returns class-level defaults."""
    settings = Settings()
    assert settings.app_name == "bearings"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.log_json is False


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """BEARINGS_* env vars override defaults."""
    monkeypatch.setenv("BEARINGS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("BEARINGS_ENVIRONMENT", "production")
    monkeypatch.setenv("BEARINGS_LOG_JSON", "true")

    settings = Settings()
    assert settings.log_level == "DEBUG"
    assert settings.environment == "production"
    assert settings.log_json is True


def test_settings_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env var lookup is case-insensitive."""
    monkeypatch.setenv("bearings_log_level", "WARNING")
    settings = Settings()
    assert settings.log_level == "WARNING"


def test_settings_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Literal type rejects values outside the allowed set."""
    monkeypatch.setenv("BEARINGS_LOG_LEVEL", "TRACE")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_data_dir_default_is_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    """data_dir defaults under XDG_DATA_HOME/bearings when set."""
    # The autouse _isolate_data_dir fixture sets BEARINGS_DATA_DIR; clear
    # it here so the default-factory runs.
    monkeypatch.delenv("BEARINGS_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-test")  # noqa: S108
    settings = Settings()
    assert str(settings.data_dir) == "/tmp/xdg-test/bearings"  # noqa: S108


def test_settings_db_path_composes(monkeypatch: pytest.MonkeyPatch) -> None:
    """db_path = data_dir / db_filename."""
    monkeypatch.setenv("BEARINGS_DATA_DIR", "/var/data/b")
    monkeypatch.setenv("BEARINGS_DB_FILENAME", "custom.db")
    settings = Settings()
    assert str(settings.db_path) == "/var/data/b/custom.db"


def test_settings_auth_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth + bind defaults are localhost-friendly with empty token.

    Empty token is intentional — the web app factory raises at boot
    unless ``auth_disabled=True``. Settings itself never decides; it
    just carries the values.

    The autouse ``_isolate_auth_token`` fixture sets a token for web
    tests; clear it locally so we observe the field default.
    """
    monkeypatch.delenv("BEARINGS_AUTH_TOKEN", raising=False)
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8788
    assert settings.auth_header_name == "X-Bearings-Token"
    assert settings.auth_disabled is False
    assert settings.auth_token.get_secret_value() == ""


def test_settings_auth_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``BEARINGS_AUTH_TOKEN`` populates the SecretStr field."""
    monkeypatch.setenv("BEARINGS_AUTH_TOKEN", "test-token-1234567890")
    settings = Settings()
    assert settings.auth_token.get_secret_value() == "test-token-1234567890"


def test_settings_port_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """Port range is enforced at the model boundary (1..65535)."""
    monkeypatch.setenv("BEARINGS_PORT", "70000")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_typos_in_kwargs() -> None:
    """extra='forbid' rejects unknown constructor kwargs.

    Note: pydantic-settings does *not* extend this to env vars — a
    typo'd env var like BEARINGS_LOG_LEVL is silently ignored by the env
    loader (it's never seen as an "extra" by the model). Catching
    typo'd env vars is recipe-tier work, not boilerplate.
    """
    with pytest.raises(ValidationError):
        Settings(log_lvl="DEBUG")  # type: ignore[call-arg]
