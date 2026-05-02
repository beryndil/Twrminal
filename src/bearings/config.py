from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import PermissionMode
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Permission-profile presets selected at first-run / `bearings init`.
# The names map to the Bearings 2026-04-21 security audit findings:
#   - "safe": public-default. Auth on (token auto-generated), per-
#     session sandbox working_dir, no `~/.claude` inherit, no MCP, no
#     hooks, bypassPermissions mode forbidden, fs picker clamped to
#     workspace root, commands palette scoped to project, default
#     budget ceiling.
#   - "workstation": laptop default. Auth on, $HOME working_dir, MCP
#     and hooks inherit allowed, bypassPermissions allowed but
#     ephemeral, Edit/Write still gates on per-call approval.
#   - "power-user": today's defaults restored. Banner names every gate
#     that's open so the operator sees exactly what they're running.
# `None` means "no profile applied" — the user opted out and is
# running raw config defaults (today's behavior pre-toggle-layer).
ProfileName = Literal["safe", "workstation", "power-user"]

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

# SDK setting-source values accepted by `ClaudeAgentOptions.setting_sources`.
# `user`  — `~/.claude/settings.json` (global Claude Code config).
# `project` — `<cwd>/.claude/settings.json` (per-project overrides).
# `local` — `<cwd>/.claude/settings.local.json` (per-checkout overrides,
#            usually gitignored).
# An empty list means the SDK ignores all of those and runs with
# Bearings' explicit options only — that's the `safe` profile default.
SettingSource = Literal["user", "project", "local"]

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
    # When set, new sessions whose `working_dir` is unspecified land in
    # `<workspace_root>/<session_id>` — a per-session sandbox subdir —
    # rather than the legacy `agent.working_dir` (which today defaults to
    # `$HOME` for laptop convenience). The `safe` profile points this at
    # `~/.local/share/bearings/workspaces` so a shared-box install
    # doesn't accidentally let a session walk the operator's home tree.
    # `None` keeps the legacy behavior and is what `power-user` /
    # `workstation` profiles run with.
    workspace_root: Path | None = None
    # Default permission mode applied to fresh sessions before any
    # client opts into a different one. `None` lets the SDK pick
    # (currently: ask-on-every-tool, the "default" mode the SDK exposes
    # as `PermissionMode.default` when nothing is specified). Profiles
    # don't currently override this — kept here so a future profile
    # that wants e.g. "always plan" has a clean knob to flip without
    # touching session-create code.
    default_permission_mode: PermissionMode | None = None
    # Whether the `set_permission_mode` WS frame is allowed to escalate
    # to `bypassPermissions`. `True` (today's behavior) lets the user
    # waive every prompt for the rest of a turn from the header
    # selector — fine for a single-operator workstation, unsafe on a
    # shared box where a stray click silently grants Edit/Write/Bash.
    # `False` (the `safe` profile default) makes the WS handler refuse
    # the escalation; the selector still offers default / plan /
    # acceptEdits. The 4-mode set in the UI is intentionally untouched
    # — the handler-side refusal is what matters; the UI display will
    # later read this flag to gray the option out.
    allow_bypass_permissions: bool = True
    # SDK `setting_sources`. `None` (today's behavior) lets the SDK
    # apply its own defaults — which today inherit `~/.claude/`
    # settings.json, project `.claude/settings.json`, and the gitignored
    # `.claude/settings.local.json`. `[]` (`safe` profile default) tells
    # the SDK to ignore every external settings file so a session run
    # under Bearings starts from a clean slate. `["user"]` /
    # `["project"]` / `["user", "project"]` etc. are explicit narrowings
    # — passed through to the SDK verbatim. Mostly relevant when
    # Bearings is running on a multi-user box or a shared dev VM where
    # the operator's `~/.claude` settings.json shouldn't leak into a
    # session another person is driving.
    setting_sources: list[SettingSource] | None = None
    # Whether the SDK should inherit MCP server registrations from the
    # operator's `~/.claude/` settings (the SDK's default behavior).
    # `True` (today's behavior, `power-user` / `workstation` default)
    # means the agent has access to whatever MCP servers the operator
    # has configured globally — useful Patina/Sentinel/Fortress glue
    # for Dave, dangerous on a shared box. `False` (`safe` profile
    # default) passes an empty `mcp_servers={}` dict to the SDK so a
    # session can only call MCP servers Bearings explicitly registers
    # for it (currently: none).
    inherit_mcp_servers: bool = True
    # Whether the SDK should inherit hook scripts from the operator's
    # `~/.claude/settings.json`. `True` (today's behavior) means
    # PreToolUse/PostToolUse/Stop/etc. hooks defined globally fire for
    # Bearings sessions too. `False` (`safe` profile default) passes
    # `hooks={}` so no inherited hook script runs — a hardening guard
    # against a malicious or stale hook leaking through. Bearings does
    # not yet register its own hooks; this knob will gain a positive
    # use-case alongside that.
    inherit_hooks: bool = True
    # Character threshold past which the PostToolUse hook emits an
    # advisory note telling the model the full output is persisted in
    # Bearings' DB and retrievable via `bearings__get_tool_output`.
    # Native tool outputs (Read/Bash/Grep) cannot be rewritten on the
    # wire — the model sees the raw output this turn — but the
    # advisory primes it to summarize aggressively in its reply and to
    # use the retrieval tool on later turns instead of asking the SDK
    # to replay the raw bytes. 8k chars ≈ 2k tokens; a single grep
    # that previously dominated a turn now leaves a short capsule in
    # the model's running summary. Set to 0 to disable the advisory
    # entirely (regression path if the hook ever causes trouble).
    # See plan `~/.claude/plans/enumerated-inventing-ullman.md` Option 6.
    tool_output_cap_chars: int = 8000
    # Whether Bearings registers its own in-process MCP server on
    # every SDK client. The server currently exposes
    # `bearings__get_tool_output` (paired with `tool_output_cap_chars`
    # above) and will gain checkpoint/reset helpers in a later wave.
    # `True` is the default because every Bearings feature in the
    # token-cost plan depends on the server being present. Flip off
    # only if a diagnostic run needs a "vanilla" SDK client without
    # Bearings tools polluting the tool list.
    enable_bearings_mcp: bool = True
    # Whether PreCompact hook steering is wired. The hook hands the
    # CLI's compactor a `custom_instructions` block telling it which
    # turns to preserve verbatim (most recent research-dense turn,
    # unanswered user questions) and which to drop (duplicate Read
    # calls, failed Bash retries). No effect when auto-compact is off
    # on the model. Flip off only for A/B-testing raw compaction
    # against steered compaction.
    enable_precompact_steering: bool = True
    # Whether the `researcher` sub-agent is registered via
    # `ClaudeAgentOptions.agents`. When True, the main turn can
    # delegate heavy codebase exploration via the `Task` tool so the
    # raw tool-call output lives in an isolated sub-agent context and
    # only a summary returns to the parent. Keeps the parent's
    # context small on research-heavy turns. Disabled by default
    # until the researcher prompt has a few real-world turns of
    # iteration under it.
    enable_researcher_subagent: bool = False
    # Slice 6 of the Session Reorg plan
    # (`~/.claude/plans/sparkling-triaging-otter.md`). Whether
    # `POST /sessions/{id}/reorg/analyze?mode=llm` is allowed to spawn
    # an in-process one-shot `claude_agent_sdk.query(...)` call to
    # propose how the source session should be split. Disabled by
    # default — the heuristic analyzer (time-gap + Jaccard topic
    # distance) ships ON regardless. Flip on after the LLM prompt has
    # been dogfooded against a few real noisy sessions; until then,
    # heuristic-only is the well-tested path. When False, an LLM-mode
    # request degrades to the heuristic and the response's `notes`
    # field surfaces the fallback to the UI.
    enable_llm_reorg_analyze: bool = False
    # Auto-suggest titles plan (`~/.claude/plans/auto-suggesting-titles.md`).
    # Whether `POST /sessions/{id}/suggest_titles` is allowed to spawn
    # an in-process one-shot `claude_agent_sdk.query(...)` call to
    # propose three candidate titles for an existing session based on
    # its recent messages. Disabled by default for the same reason the
    # reorg-analyze knob is — the prompt needs dogfooding before it
    # ships on. When False, the route returns 503 with a hint pointing
    # the user at this config key; the SessionEdit modal surfaces the
    # message inline so the operator knows exactly which flag to flip.
    enable_llm_title_suggest: bool = False
    # Spawn-from-reply Wave 3 (`~/.claude/plans/classifying-spawn-reply-wave-3.md`).
    # Whether `POST /sessions/{id}/spawn_from_reply/{message_id}/classify`
    # is allowed to spawn an in-process one-shot `claude_agent_sdk.query()`
    # call to classify an assistant reply into single_chat / multi_chat /
    # checklist shape. Disabled by default — the fallback path always
    # returns single_chat so the route degrades gracefully without a 503.
    # Flip on once the classifier prompt has been dogfooded against real
    # replies and the shape heuristics feel stable.
    enable_llm_spawn_classifier: bool = False
    # Override the model used by suggest_titles + bulk-suggest when LLM
    # title-suggest is enabled. None means "fall back to the session's
    # configured model" (typically Opus / Sonnet). A title-summarizer
    # call doesn't need that horsepower — Haiku 4.5 cuts cost ~10× per
    # click with no perceptible quality loss on the 3-candidate
    # narrow→medium→wide axis the prompt asks for. Recommended in the
    # default config the installer drops; left None here so an explicit
    # override has to be a deliberate choice.
    title_suggest_model: str | None = None


class StorageCfg(BaseModel):
    db_path: Path = Field(default_factory=lambda: DATA_HOME / "db.sqlite")
    # Singleton avatar PNG written by `POST /api/preferences/avatar`.
    # Fixed path under DATA_HOME — Bearings is single-user, so one file
    # covers the whole feature. Tests redirect this at `tmp_path` so
    # uploads don't scribble on the developer's real avatar. The file
    # is normalised to 512×512 PNG by Pillow regardless of the upload
    # format (PNG / JPEG / WebP), so callers can treat the path as a
    # static asset and serve it byte-for-byte.
    avatar_path: Path = Field(default_factory=lambda: DATA_HOME / "avatar.png")
    # Per-upload byte cap, enforced while reading the multipart body.
    # 5 MiB is comfortable for a high-res portrait at any reasonable
    # input compression while keeping accidental "I dropped a 4K
    # screenshot" cases out of the resize pipeline.
    avatar_max_size_mb: int = 5
    # Auto-hydrate display_name + avatar from the host OS at boot when
    # the prefs row is still seed state. Off in test fixtures so the
    # dev's real GECOS / AccountsService values don't leak into test
    # assertions; on by default in production for the "fresh install
    # just works" UX. Manual edits via Settings are never overwritten.
    system_identity_hydrate: bool = True


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
    # the native picker instead. Plan §8.5 calls for 10 MB as the
    # per-spec attachment ceiling — installs that want the tighter cap
    # set this to 10 in `config.toml`.
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
    # Plan §8.5 attachment MIME allowlist. Non-empty list switches the
    # upload route from denylist mode (legacy) to allowlist mode: only
    # files whose `Content-Type` is in `allowed_mime_types` OR whose
    # lowercased extension is in `allowed_extensions` are accepted; the
    # per-extension fallback exists because browsers serve many code
    # files as `application/octet-stream` and rejecting on MIME alone
    # would break review-this-file workflows. Empty list keeps the
    # legacy denylist behaviour so existing configs are unaffected.
    allowed_mime_types: list[str] = Field(default_factory=list)
    allowed_extensions: list[str] = Field(default_factory=list)
    # Per-turn caps (plan §8.5). The frontend enforces these before the
    # POST round-trip — they live here so the same number can be served
    # to the UI via `/ui-config` and a config bump propagates without a
    # frontend rebuild. The backend doesn't enforce per-turn caps
    # directly (it doesn't see "turn boundaries"); the per-FILE cap
    # above is the hard backend gate.
    max_per_turn_count: int = 10
    max_per_turn_bytes: int = 50 * 1024 * 1024
    # Retention window for `bearings gc uploads`. UUID subdirs whose
    # newest entry is older than this many days get pruned by the sweep.
    # 30 days lines up with the L5.9 punch-list ask and is the floor
    # most workflows can tolerate — a session that needs to re-read a
    # dropped file weeks later should re-attach it. Set to 0 to disable
    # the sweep (the CLI subcommand still runs, it just finds nothing).
    retention_days: int = 30


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


class ProfileCfg(BaseModel):
    """Permission-profile metadata.

    `name` is informational — it records which preset the user picked
    at `bearings init` time so the startup banner and UI header can
    display "running profile: safe" etc. The actual gates that make a
    profile a profile live in their own `[agent]` / `[commands]` /
    `[fs]` / `[auth]` knobs; this field is what surfaces the choice to
    the operator and to anything that wants to display it. `None`
    means no profile was applied (raw defaults / mix-and-match).

    `show_banner` controls whether `bearings serve` prints the gate
    audit on startup. Default `True` because the whole point of the
    banner is to make the security posture visible — but a systemd-
    user service operator who reads journald has another path to that
    info and can opt out if the duplication is noisy.
    """

    name: ProfileName | None = None
    show_banner: bool = True


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
    profile: ProfileCfg = Field(default_factory=ProfileCfg)

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
