"""Pydantic-settings root model for the Bearings v1 runtime.

Loads configuration from layered sources, in precedence order
(higher overrides lower):

1. Constructor / explicit kwargs (programmatic override; primarily tests).
2. Environment variables prefixed ``BEARINGS_`` (case-insensitive).
3. TOML at the XDG config path (``$XDG_CONFIG_HOME/bearings/config.toml``;
   falls back to ``~/.config/bearings/config.toml`` when the env var is
   unset). A missing file is silently treated as "no overrides".
4. Hard-coded defaults from :mod:`bearings.config.constants`.

Numeric / string defaults are *never* expressed as inline literals in
this module: every field's ``default`` references a named constant from
:mod:`bearings.config.constants`. The auditor's "no inline literals
downstream" gate (item 0.5 done-when) flags any literal here.

Strict validation:

* ``extra="forbid"`` — unknown TOML keys / env vars surface as
  ``ValidationError`` rather than being silently dropped.
* ``case_sensitive=False`` — ``BEARINGS_PORT`` / ``bearings_port`` /
  ``Bearings_Port`` are equivalent. Linux env-var convention is
  uppercase; TOML keys are typically lowercase; the Settings shape
  must accept both without bespoke handling.
* mypy ``--strict`` clean — no ``Any``.

The frame is intentionally narrow: this module ships only the runtime
knobs item 0.5's done-when explicitly names (port, db_path) plus the
spec-driven knobs that are clearly cross-cutting (routing preview
debounce, advisor enable, quota threshold + poll cadence,
override-rate review threshold, tool-output cap). Phase 1 items
introduce additional sub-configs (Auth/Vault/Uploads/...) per
``docs/architecture-v1.md`` §1.1.2 as their feature surface lands.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from bearings.config.constants import (
    DEFAULT_ALLOWED_SHELL_COMMANDS,
    DEFAULT_BILLING_MODE,
    DEFAULT_BILLING_PLAN,
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TOOL_OUTPUT_CAP_CHARS,
    DEFAULT_UPLOADS_STORAGE_ROOT,
    DEFAULT_VAULT_PLAN_ROOT,
    DEFAULT_VAULT_TODO_GLOB,
    FS_LIST_MAX_ENTRIES,
    FS_READ_MAX_BYTES,
    MAX_UPLOAD_SIZE_BYTES,
    OVERRIDE_RATE_REVIEW_THRESHOLD,
    PCT_MAX,
    PCT_MIN,
    QUOTA_THRESHOLD_PCT,
    ROUTING_PREVIEW_DEBOUNCE_MS,
    SHELL_EXEC_TIMEOUT_S,
    SHELL_OUTPUT_MAX_BYTES,
    TCP_PORT_MAX,
    TCP_PORT_MIN,
    USAGE_POLL_INTERVAL_S,
)

_XDG_CONFIG_HOME_ENV: Final[str] = "XDG_CONFIG_HOME"
_XDG_CONFIG_HOME_DEFAULT: Final[Path] = Path("~/.config").expanduser()
_BEARINGS_CONFIG_RELPATH: Final[Path] = Path("bearings") / "config.toml"


# Mirrors v0.17.x ``BillingMode``. Kept as a top-level ``Literal`` so the
# field validator surfaces ``ValidationError`` on a typo (``"subsciption"``)
# rather than accepting the string and confusing the renderer downstream.
BillingMode = Literal["payg", "subscription"]


class BillingCfg(BaseModel):  # type: ignore[explicit-any]
    """Billing mode + plan label — mirrors v0.17.x ``BillingCfg`` so the
    shared ``~/.config/bearings/config.toml`` round-trips cleanly during
    the dogfood cutover.

    ``mode``: ``"payg"`` (developer-API users; session-card shows dollar
    figures) or ``"subscription"`` (Anthropic Max/Pro users; session-card
    swaps to token totals because the dollar number is misleading on a
    subscription plan). Default ``"payg"`` preserves pre-billing-knob
    behavior.

    ``plan``: informational label like ``"max_20x"`` / ``"pro"`` /
    ``"max_5x"``. Currently unused by v1's renderer; reserved for a
    future plan-aware token meter should Anthropic ship per-plan quota
    endpoints. ``None`` is the no-plan-known sentinel.

    Frozen so the model can participate in cache keys downstream; defaults
    flow through the constants module per the no-inline-literals gate.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: BillingMode = Field(default=DEFAULT_BILLING_MODE)  # type: ignore[assignment]
    plan: str | None = Field(default=DEFAULT_BILLING_PLAN)


class VaultCfg(BaseModel):  # type: ignore[explicit-any]
    # ``disallow_any_explicit`` flags the Pydantic metaclass surface;
    # the ignore is the same narrow carve-out :class:`Settings` makes.
    """Vault sub-config — plan-root directories + TODO glob patterns.

    Per ``docs/architecture-v1.md`` §1.1.2 a ``VaultCfg`` lives under
    :class:`Settings`; per ``docs/behavior/vault.md`` §"Vault entry
    types" the user configures plan roots (where each ``.md`` is a
    plan, non-recursive) and TODO globs (where matching files are
    surfaced as todo entries, recursive globbing supported via ``**``).

    Both fields default to single-element tuples sourced from
    :data:`bearings.config.constants.DEFAULT_VAULT_PLAN_ROOT` and
    :data:`bearings.config.constants.DEFAULT_VAULT_TODO_GLOB`. A user
    who installs Bearings without ever editing config sees the
    expected ``~/.claude/plans/*.md`` + ``~/Projects/**/TODO.md``
    surface; a power user can override via TOML (``vault.plan_roots``
    / ``vault.todo_globs`` accept lists). The ``frozen=True`` config
    keeps the model hashable so a downstream consumer can include it
    in a dataclass cache key.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_roots: tuple[Path, ...] = Field(default=(DEFAULT_VAULT_PLAN_ROOT,))
    todo_globs: tuple[str, ...] = Field(default=(DEFAULT_VAULT_TODO_GLOB,))


class UploadsCfg(BaseModel):  # type: ignore[explicit-any]
    """Uploads sub-config — on-disk storage root + per-body size cap.

    Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/uploads.py``
    accepts multipart-form-data uploads, writes the body under
    :data:`UploadsCfg.storage_root` keyed by sha256, and persists the
    metadata row in the DB. Behavior docs are silent on the endpoint
    shape (chat.md mentions "attachment chips" only); see the
    constants module for the decided-and-documented contract.

    Defaults flow from :mod:`bearings.config.constants` so the
    no-inline-literals gate holds. ``frozen=True`` keeps the model
    hashable for downstream cache keys.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    storage_root: Path = Field(default=DEFAULT_UPLOADS_STORAGE_ROOT)
    max_size_bytes: int = Field(default=MAX_UPLOAD_SIZE_BYTES, gt=0)


class FsCfg(BaseModel):  # type: ignore[explicit-any]
    """Filesystem-walk sub-config — allow-roots + read/list caps.

    Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/fs.py`` is the
    general-purpose FS-picker walker. The route enforces every input
    path against :data:`FsCfg.allow_roots` after realpath resolution
    so ``..``, symlink escape, and absolute-path-outside-root are all
    rejected at the boundary.

    The default ``allow_roots`` is empty — a fresh ``Settings()`` has
    NO accessible filesystem surface from the FS endpoint. A user
    opts in via TOML by setting ``fs.allow_roots = ["/home/me/projects"]``;
    tests inject a tuple containing a ``tmp_path`` so the endpoint is
    deterministic. Decided-and-documented (vault.md is plan/todo-only;
    no behavior doc covers a default for the general walker).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_roots: tuple[Path, ...] = Field(default=())
    read_max_bytes: int = Field(default=FS_READ_MAX_BYTES, gt=0)
    list_max_entries: int = Field(default=FS_LIST_MAX_ENTRIES, gt=0)


class ShellCfg(BaseModel):  # type: ignore[explicit-any]
    """Shell-exec sub-config — argv allowlist + per-call wall-clock cap.

    Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/shell.py``
    dispatches argv via ``subprocess.run`` with ``shell=False`` and
    rejects any argv whose argv[0] is not in
    :data:`ShellCfg.allowed_commands`. The default allowlist (per
    :data:`bearings.config.constants.DEFAULT_ALLOWED_SHELL_COMMANDS`)
    is intentionally minimal — only ``xdg-open`` plus the two POSIX
    no-ops ``echo`` / ``true`` so the integration-test surface
    requires no allowlist override. Power users extend via TOML.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_commands: frozenset[str] = Field(default=DEFAULT_ALLOWED_SHELL_COMMANDS)
    timeout_s: float = Field(default=SHELL_EXEC_TIMEOUT_S, gt=0.0)
    output_max_bytes: int = Field(default=SHELL_OUTPUT_MAX_BYTES, gt=0)


def xdg_config_path() -> Path:
    """Return the XDG-resolved config-file path for Bearings.

    Reads ``$XDG_CONFIG_HOME`` (falls back to ``~/.config``) and appends
    ``bearings/config.toml``. Does not check whether the file exists —
    the TOML source treats a missing file as "no overrides" per
    pydantic-settings' :class:`TomlConfigSettingsSource` semantics.

    A whitespace-only ``XDG_CONFIG_HOME`` is treated as unset (per the
    XDG Base Directory spec, an empty value falls back to the default).
    """
    base = os.environ.get(_XDG_CONFIG_HOME_ENV, "").strip()
    root = Path(base).expanduser() if base else _XDG_CONFIG_HOME_DEFAULT
    return root / _BEARINGS_CONFIG_RELPATH


class Settings(BaseSettings):  # type: ignore[explicit-any]
    # ``disallow_any_explicit = true`` (pyproject.toml) flags this line
    # because pydantic-settings' :class:`BaseSettings` exposes ``Any``-
    # typed metaclass surface. The ignore is the narrowest possible
    # carve-out — every field below is fully typed.
    """Root settings model for the Bearings v1 runtime.

    Field defaults reference named constants from
    :mod:`bearings.config.constants`. See the module docstring for the
    no-inline-literal contract enforced by the item-0.5 audit.
    """

    model_config = SettingsConfigDict(
        env_prefix="BEARINGS_",
        case_sensitive=False,
        extra="forbid",
        env_file=None,
    )

    # Server bind. Master item 0.5 names ``port`` (default 8788) at the
    # top level; the env-var ``BEARINGS_PORT`` resolves directly.
    port: int = Field(default=DEFAULT_PORT, ge=TCP_PORT_MIN, le=TCP_PORT_MAX)
    host: str = Field(default=DEFAULT_HOST)

    # Storage. ``BEARINGS_DB_PATH`` resolves directly; the constants
    # module pre-expands ``~`` so the default is an absolute Path.
    db_path: Path = Field(default=DEFAULT_DB_PATH)

    # Per-tool-call output soft cap (arch §1.1.2 + §4.8 SessionConfig).
    tool_output_cap_chars: int = Field(default=DEFAULT_TOOL_OUTPUT_CAP_CHARS, gt=0)

    # Routing preview debounce override (spec §6 — "~300ms"). The
    # constant value is the spec mandate; this field lets a user retune
    # without an SDK pin bump.
    routing_preview_debounce_ms: int = Field(
        default=ROUTING_PREVIEW_DEBOUNCE_MS,
        gt=0,
    )

    # Master switch for the advisor primitive (spec §2). Defaults to on
    # so the spec's default-policy table fires; the user can disable
    # advisor wiring globally without touching individual rules.
    advisor_enabled: bool = Field(default=True)

    # Quota-guard tuning. The constant is the spec §4 mandate; both
    # fields are user-tunable per spec §13 risk #2.
    quota_threshold_pct: float = Field(default=QUOTA_THRESHOLD_PCT, ge=PCT_MIN, le=PCT_MAX)
    quota_poll_interval_s: int = Field(default=USAGE_POLL_INTERVAL_S, gt=0)

    # Override-rate review threshold (spec §8). User-tunable for noisy
    # rule sets where the default 0.30 produces too many "Review:"
    # highlights to act on.
    override_rate_review_threshold: float = Field(
        default=OVERRIDE_RATE_REVIEW_THRESHOLD,
        ge=PCT_MIN,
        le=PCT_MAX,
    )

    # Vault configuration (item 1.5; arch §1.1.2). The default-factory
    # produces a fresh :class:`VaultCfg` per ``Settings`` instance so a
    # frozen sub-config never accidentally shares identity across
    # constructions; the values themselves come from
    # :data:`bearings.config.constants` so the no-inline-literals gate
    # holds.
    vault: VaultCfg = Field(default_factory=VaultCfg)

    # Misc-API sub-configurations (item 1.10; arch §1.1.5
    # ``web/routes/{uploads,fs,shell}.py``). Default-factory pattern
    # mirrors ``vault`` above so each ``Settings`` instance has its
    # own frozen sub-config identity.
    uploads: UploadsCfg = Field(default_factory=UploadsCfg)
    fs: FsCfg = Field(default_factory=FsCfg)
    shell: ShellCfg = Field(default_factory=ShellCfg)

    # Billing mode mirrors v0.17.x so the shared XDG config file
    # (``~/.config/bearings/config.toml``) round-trips cleanly during
    # the dogfood cutover (2026-05-01). The renderer wiring is a
    # post-cutover follow-up — accepting the field now unblocks the
    # systemd unit; surfacing the value in the inspector is a separate
    # item once the dogfood feedback says it matters.
    billing: BillingCfg = Field(default_factory=BillingCfg)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Layer XDG-TOML beneath env vars and explicit kwargs.

        Precedence (high → low, per pydantic-settings tuple order):

        1. ``init_settings`` (constructor kwargs)
        2. ``env_settings`` (``BEARINGS_*`` env vars)
        3. ``TomlConfigSettingsSource`` reading the XDG config path

        Default ``dotenv`` and ``secrets`` sources are dropped: Bearings
        is single-user localhost and does not load .env files or
        Docker-style secrets directories.
        """
        # ``cls`` is the auto-bound classmethod target; pydantic-settings
        # passes the same class explicitly as ``settings_cls`` for the
        # override signature so the body uses the named arg. The other
        # two sources are intentionally dropped (see docstring).
        del cls, dotenv_settings, file_secret_settings
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=xdg_config_path()),
        )


__all__ = [
    "BillingCfg",
    "BillingMode",
    "FsCfg",
    "Settings",
    "ShellCfg",
    "UploadsCfg",
    "VaultCfg",
    "xdg_config_path",
]
