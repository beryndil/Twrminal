from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# `commands.scope` controls how far the `/api/commands` palette walks:
#   - "all" (default): project `.claude/` + user `~/.claude/` + every
#     installed plugin under `~/.claude/plugins/marketplaces/*`. Today's
#     behavior, useful for power users.
#   - "user": project + user, but skip plugins. Middle ground for when
#     the user has trusted commands under `~/.claude/` but doesn't want
#     to trust everything a marketplace ever installed.
#   - "project": project `.claude/` only. `safe`-profile default per
#     the 2026-04-21 security audit §5 — a session running in one
#     project shouldn't pick up commands from another project or from
#     plugins the user forgot they ever added.
CommandsScope = Literal["all", "user", "project"]

# Shorthand for the two knobs we expose for extended thinking:
#   - "adaptive": model decides how much to think (recommended default).
#   - "disabled": never emit thinking blocks.
# `None` means "don't pass anything", which falls through to the SDK's
# own default (currently: thinking off unless the model is configured for
# it). We default to "adaptive" so sessions show reasoning in the UI.
ThinkingMode = Literal["adaptive", "disabled"]

# Billing mode toggles what the UI shows as the "spend" metric.
#   - "payg": dollars from ResultMessage.total_cost_usd (the SDK's
#     pay-as-you-go equivalent cost). Matches the developer-API bill
#     exactly.
#   - "subscription": token totals from ResultMessage.usage. Dollars
#     are misleading on a Max/Pro subscription because billing is
#     flat; tokens correlate with the quota that actually depletes.
# Anthropic does not expose Max-plan quota percentages via any public
# API, so "subscription" mode shows raw tokens rather than a fake
# percentage meter.
BillingMode = Literal["payg", "subscription"]


def _xdg(var: str, default: Path) -> Path:
    raw = os.environ.get(var)
    return Path(raw) if raw else default


CONFIG_HOME = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "bearings"
DATA_HOME = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / "bearings"


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    # Extra origins accepted on the WS handshake beyond the loopback
    # defaults (`http://127.0.0.1:<port>`, `http://localhost:<port>`,
    # `http://[::1]:<port>`). Use to whitelist the Vite dev server
    # (e.g. `"http://localhost:5173"`) or any custom local deployment.
    # Entries are compared verbatim against the browser's `Origin`
    # header — include scheme and port, no trailing slash. Added as a
    # ship-blocker fix (2026-04-21 security audit §1).
    allowed_origins: list[str] = Field(default_factory=list)


class AuthCfg(BaseModel):
    enabled: bool = False
    token: str | None = None


class AgentCfg(BaseModel):
    working_dir: Path = Field(default_factory=lambda: Path.home())
    model: str = "claude-opus-4-7"
    # Extended-thinking control. "adaptive" lets Claude decide how much
    # to think per turn (minimal on simple prompts, deeper on complex
    # ones); "disabled" turns thinking off entirely; `None` skips the
    # flag so the SDK's own default applies. The Conversation view
    # renders the resulting thinking blocks in a collapsed `<details>`
    # next to each assistant turn.
    thinking: ThinkingMode | None = "adaptive"
    # Default per-session spend cap applied when `SessionCreate` doesn't
    # carry an explicit `max_budget_usd`. `None` (today's behavior)
    # leaves new sessions uncapped and relies on the user to set one
    # manually — fine for Dave, dangerous for a shared box where a
    # runaway loop can rack up real-dollar cost before the turn
    # finishes. The `safe` profile flips this to a small positive
    # number. Enforced at session-create in `routes_sessions.py`;
    # the cap itself lives on `sessions.max_budget_usd` once written.
    # Per-session overrides remain authoritative — setting this only
    # fills in the default when the caller didn't specify.
    # 2026-04-21 security audit §7 (2026-04-23 fix).
    default_max_budget_usd: float | None = None


class StorageCfg(BaseModel):
    db_path: Path = Field(default_factory=lambda: DATA_HOME / "db.sqlite")


class MetricsCfg(BaseModel):
    enabled: bool = False


class RunnerCfg(BaseModel):
    # Seconds a `SessionRunner` is allowed to sit "quiet" (no turn in
    # flight AND no WebSocket subscribers) before the registry reaper
    # evicts it, freeing its worker task + 5000-slot ring buffer. The
    # runner is recreated on the next WS connect; SDK session id is
    # persisted so the resumed turn still has history. Set to 0 to
    # disable the reaper (v0.3.13 behavior — runners live until the
    # session is deleted or the app shuts down).
    idle_ttl_seconds: float = 900.0
    # How often the reaper wakes to scan. One pass is cheap (a dict
    # comprehension under a short-held asyncio.Lock), so this only
    # controls eviction latency, not overhead.
    reap_interval_seconds: float = 60.0


class UploadsCfg(BaseModel):
    # Chrome/Wayland strips `text/uri-list` metadata from browser file
    # drops even though `DataTransfer.files` still carries the bytes.
    # The drop handler reads those bytes and POSTs them to
    # `/api/uploads`; the server persists under `upload_dir` with a
    # UUID name and hands the absolute path back for prompt injection.
    upload_dir: Path = Field(default_factory=lambda: DATA_HOME / "uploads")
    # Size cap in whole megabytes. 25 is enough for screenshots, PDFs,
    # log excerpts; anything larger should be referenced by path via
    # the native picker instead.
    max_size_mb: int = 25
    # Extensions we refuse regardless of size — defense-in-depth against
    # dragging a shell script or binary. Bearings is localhost-only and
    # never executes uploads server-side, so the real protection is
    # already in place; this list just keeps the obviously-wrong cases
    # from landing in the upload dir. Matched case-insensitively.
    blocked_extensions: list[str] = Field(
        default_factory=lambda: [
            ".sh",
            ".bash",
            ".zsh",
            ".fish",
            ".bat",
            ".cmd",
            ".ps1",
            ".exe",
            ".msi",
            ".com",
            ".so",
            ".dll",
            ".dylib",
            ".appimage",
        ]
    )


class ArtifactsCfg(BaseModel):
    """On-disk surface for agent-authored artifacts served back to the UI.

    The mirror image of `UploadsCfg`: uploads carry browser bytes *to* the
    agent; artifacts carry agent-written files *back* to the browser so
    the Conversation view can render them inline (an image `<img>` today,
    a PDF/DOCX preview in later phases). Files land here when Claude
    calls `POST /api/sessions/{sid}/artifacts` to register a path it has
    already written; the GET endpoint streams them by id with the right
    Content-Type and `Content-Disposition: inline`.
    `serve_roots` is the allowlist the register endpoint enforces — a
    file is registerable iff its resolved path lives under one of these
    roots. Defaults: the artifacts dir itself, plus the uploads dir (so a
    user-dropped file can also be re-served back into the view via the
    deferred attachment-chip path). Add to this list via `config.toml` if
    you want Claude to be able to serve files it writes elsewhere under
    the working dir — but weigh the read-exposure cost: every path in
    this list becomes readable via `GET /api/artifacts/{id}` by any
    authenticated caller.
    `max_register_size_mb` caps what `POST /api/sessions/{sid}/artifacts`
    will accept by `stat().st_size`. 100 MB is generous — agent-authored
    PDFs and screenshots are small; bigger artifacts (video, large
    datasets) should be referenced by path through the filesystem picker
    rather than served inline."""

    artifacts_dir: Path = Field(default_factory=lambda: DATA_HOME / "artifacts")
    serve_roots: list[Path] = Field(
        default_factory=lambda: [DATA_HOME / "artifacts", DATA_HOME / "uploads"]
    )
    max_register_size_mb: int = 100


class FsCfg(BaseModel):
    """Filesystem-surface policy for the in-app folder/file pickers.

    `allow_root` clamps `/api/fs/list`: the route is authenticated-
    localhost-only, but even under auth a cross-origin attacker who
    somehow got a valid token (reused Bearer) shouldn't be able to
    enumerate the entire host. Default is `$HOME` — narrow enough to
    matter, wide enough that a returning user doesn't hit 403 on the
    dirs they actually work in. Set to `/` to restore v0.1.x behavior
    (full host listing) if you know what you're trading away.
    Added 2026-04-21 security audit §5.
    """

    allow_root: Path = Field(default_factory=lambda: Path.home())


class ShellCfg(BaseModel):
    """Commands the `/api/shell/open` bridge dispatches to.

    Each field is a `list[str]` argv — the path is substituted into any
    `{path}` placeholder and appended as a trailing arg if no placeholder
    is present. `None` means the user hasn't configured that kind and the
    bridge answers 400 (UI surfaces this as a "Configure in settings"
    tooltip per plan §2.3). argv-list form avoids `shell=True`, keeping
    quoting sane on paths with spaces.

    Added in Phase 4a.1 of docs/context-menu-plan.md. Powers the
    `open_in` submenu (Phase 6) + Phase 4a.2 working-dir menus. Bearings
    is localhost-only and never runs these commands in response to
    untrusted input — the caller is always the local SvelteKit bundle —
    so defense-in-depth here is about argv hygiene, not sandboxing."""

    editor_command: list[str] | None = None
    terminal_command: list[str] | None = None
    file_explorer_command: list[str] | None = None
    git_gui_command: list[str] | None = None
    claude_cli_command: list[str] | None = None


class CommandsCfg(BaseModel):
    """Scope policy for `/api/commands` — the slash-command palette.

    The scanner walks three sources: project `.claude/`, user
    `~/.claude/`, and every installed plugin under
    `~/.claude/plugins/marketplaces/*`. `scope` narrows which of those
    are surfaced to the palette:

      - "all" (default)  — today's behavior; power-user friendly.
      - "user"           — project + user; skip plugins.
      - "project"        — project only; `safe`-profile default.

    The server never *executes* these commands — they're rendered as
    completions in the composer and sent verbatim to the agent — so
    this knob controls visibility, not privilege. Narrowing still
    matters: a session running in project A shouldn't autocomplete
    to commands that only make sense in project B, and plugin slash-
    commands can carry prompts the user doesn't remember installing.
    Added 2026-04-21 security audit §5 (2026-04-23 fix).
    """

    scope: CommandsScope = "all"


class VaultCfg(BaseModel):
    """Read-only on-disk markdown surface exposed under `/api/vault/*`.

    Aggregates Dave's planning docs (plans under `~/.claude/plans/`)
    and per-project `TODO.md` files so the Bearings UI can browse them
    without terminal-hopping. Paths are expanded with `~` / env-var
    substitution at request time, so a user rename of `$HOME` or a
    fresh project-root won't strand the index.

    Security: the values here ARE the allowlist. `/api/vault/doc` only
    returns bytes for paths that appear in the current scan. Adding or
    removing patterns is equivalent to granting/revoking read exposure
    — treat like `fs.allow_root`."""

    plan_roots: list[Path] = Field(default_factory=lambda: [Path.home() / ".claude" / "plans"])
    todo_globs: list[str] = Field(
        default_factory=lambda: [
            str(Path.home() / "Projects" / "**" / "TODO.md"),
            str(Path.home() / ".claude" / "TODO.md"),
            str(Path.home() / "usb_backup" / "TODO.md"),
        ]
    )


class BillingCfg(BaseModel):
    # Defaults to "payg" so nothing changes for developer-API users who
    # were using Bearings before this knob existed. Max/Pro subscribers
    # set this to "subscription" in config.toml to swap the session-card
    # dollar figure for token totals.
    mode: BillingMode = "payg"
    # Informational only — e.g. "max_20x", "pro", "max_5x". Currently
    # unused by the rendering code; reserved for a future plan-aware
    # token meter should Anthropic ship quota endpoints.
    plan: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BEARINGS_", extra="ignore")

    server: ServerCfg = Field(default_factory=ServerCfg)
    auth: AuthCfg = Field(default_factory=AuthCfg)
    agent: AgentCfg = Field(default_factory=AgentCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    metrics: MetricsCfg = Field(default_factory=MetricsCfg)
    billing: BillingCfg = Field(default_factory=BillingCfg)
    runner: RunnerCfg = Field(default_factory=RunnerCfg)
    uploads: UploadsCfg = Field(default_factory=UploadsCfg)
    artifacts: ArtifactsCfg = Field(default_factory=ArtifactsCfg)
    shell: ShellCfg = Field(default_factory=ShellCfg)
    fs: FsCfg = Field(default_factory=FsCfg)
    commands: CommandsCfg = Field(default_factory=CommandsCfg)
    vault: VaultCfg = Field(default_factory=VaultCfg)

    config_file: Path = Field(default_factory=lambda: CONFIG_HOME / "config.toml")
    # `menus.toml` is the Phase 10 customization file: pinned / hidden
    # / shortcut overrides per context-menu target. Read once at boot
    # (no hot-reload) by `load_menu_config` off this path. Kept as a
    # separate file — not merged into config.toml — because the shape
    # is per-target with nested tables; mixing with the flat server /
    # auth / agent settings would be noisy.
    menus_file: Path = Field(default_factory=lambda: CONFIG_HOME / "menus.toml")

    def ensure_paths(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.storage.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings(config_file: Path | None = None) -> Settings:
    path = config_file or CONFIG_HOME / "config.toml"
    data: dict[str, Any] = {}
    if path.exists():
        data = tomllib.loads(path.read_text())
    settings = Settings(**data)
    settings.config_file = path
    return settings
