"""Application configuration.

Loaded from environment variables (with optional ``.env`` file fallback)
via pydantic-settings. The :class:`Settings` class is the **single
config module** for Bearings — every other module reads its tunables
from here, never from inline literals or ad-hoc ``os.environ`` lookups.

Charter §28 (Configuration Management) — IN scope: no hardcoded values
for endpoints, paths, timeouts, or feature flags; secrets via env
(BYO Anthropic key per §9 lands later, in its own field).
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Environment = Literal["development", "staging", "production"]


def _default_data_dir() -> Path:
    """XDG-style default for the writeable data directory.

    Resolves to ``$XDG_DATA_HOME/bearings`` if set, else
    ``~/.local/share/bearings``. Computed at field-default time, not
    import time, so tests that monkeypatch ``HOME`` see the patched
    value (Pydantic calls the factory once per ``Settings()`` instance).
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "bearings"


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Resolution order (later wins):

    1. Class-level defaults declared on each field below.
    2. Values in a ``.env`` file at the project root, if present.
    3. Process environment variables (``BEARINGS_*``).
    4. Constructor keyword arguments (used in tests).

    All env var names are case-insensitive and prefixed with
    ``BEARINGS_``, e.g. ``BEARINGS_LOG_LEVEL=DEBUG``. ``extra="forbid"``
    rejects unknown constructor kwargs (e.g. ``Settings(log_lvl=...)``);
    note that pydantic-settings does *not* surface typo'd env vars
    (``BEARINGS_LOG_LEVL``) as model extras — they're silently ignored
    by the env loader.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BEARINGS_",
        case_sensitive=False,
        extra="forbid",
    )

    app_name: str = Field(
        default="bearings",
        description="Human-readable application name; used in log events.",
    )
    environment: Environment = Field(
        default="development",
        description="Deployment environment. Drives log format and error verbosity.",
    )
    log_level: LogLevel = Field(
        default="INFO",
        description="Minimum log level emitted. Matches stdlib logging level names.",
    )
    log_json: bool = Field(
        default=False,
        description="Emit logs as one-JSON-object-per-line. Off in dev, on in prod.",
    )
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        description=(
            "Writeable directory for runtime state (SQLite DB, future caches). "
            "Defaults to $XDG_DATA_HOME/bearings or ~/.local/share/bearings."
        ),
    )
    db_filename: str = Field(
        default="bearings.sqlite3",
        description="SQLite database filename inside data_dir.",
    )

    # ---- Web server bind ----
    #
    # Defaults match the prompt-endpoint already encoded in
    # ``~/.claude/CLAUDE.md`` (autonomous-execution pattern POSTs to
    # ``http://127.0.0.1:8788``). Localhost-only by default — Sec rule:
    # never bind 0.0.0.0 implicitly. Multi-device exposure is the §11
    # network-surface phase, gated behind explicit configuration.
    host: str = Field(
        default="127.0.0.1",
        description="Bind host for the HTTP server. Defaults to localhost only.",
    )
    port: int = Field(
        default=8788,
        ge=1,
        le=65535,
        description="Bind port for the HTTP server.",
    )

    # ---- Shared-token auth ----
    #
    # v1 auth model is a single shared bearer token sent on every
    # authenticated request via the header named by ``auth_header_name``.
    # NOT JWT, NOT OAuth2, NOT cookies. Stack pin §3 — settled in plan.
    # Empty default + ``auth_disabled=False`` means the app refuses to
    # boot without an explicit token (Op directive: Zero-Crash; never
    # boot an unauthenticated localhost server "by accident").
    auth_token: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Shared bearer token for the HTTP API. Required unless "
            "auth_disabled=True. Empty value triggers a startup failure."
        ),
    )
    auth_header_name: str = Field(
        default="X-Bearings-Token",
        description="HTTP header carrying the shared bearer token.",
    )
    auth_disabled: bool = Field(
        default=False,
        description=(
            "Dev-only escape hatch: skip auth entirely. Must be paired "
            "with a structured warning log at startup so it's visible "
            "in any environment that accidentally enables it."
        ),
    )

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite database file.

        Composed from ``data_dir`` + ``db_filename`` so callers don't
        have to remember the convention or join the two manually.
        """
        return self.data_dir / self.db_filename
