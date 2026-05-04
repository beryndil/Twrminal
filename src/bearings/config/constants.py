"""Numeric and string defaults for the Bearings v1 rebuild.

Source-of-truth notes
---------------------

Every constant in this module is mandated by either:

* ``docs/model-routing-v1-spec.md`` — routing/quota/usage defaults
  (cited per-line by section §);
* ``docs/architecture-v1.md`` — internal-runtime defaults whose
  rationale is documented in §1.1.2 / §5 of the arch doc; or
* ``docs/behavior/<subsystem>.md`` — user-observable timing /
  threshold values whose authoritative source is the per-subsystem
  behavior spec; or
* the project ``CLAUDE.md`` repo invariants (port 8788 + DB at
  ``~/.local/share/bearings-v1/``) that let v0.17.x and v1 run
  side-by-side during the dogfood phase.

Downstream modules MUST import from here instead of hard-coding
literals — the auditor's "no inline literals" gate (item 0.5
done-when) scans every diff under ``src/bearings/`` for numeric /
string defaults that should have come from this module.

Spec §3's priority-ladder values (10/20/30/40/50/60/1000) are
deliberately *not* exposed here. Per ``docs/architecture-v1.md`` §6.5
#7 the source-of-truth for those values is the DB seed in
``db/connection.py`` (the user can edit them after first-run, so a
``Final[int]`` constant would lie). The constants module names the
runtime-tunable defaults; the seed names the (editable) priority
ladder.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Final, Literal

# ---------------------------------------------------------------------------
# Process-level defaults (project CLAUDE.md "Repo invariants")
# ---------------------------------------------------------------------------

# Concurrent-run port: v0.17.x stays on 8787; v1 lives on 8788 so both UIs
# can be hosted at once during dogfood.
DEFAULT_PORT: Final[int] = 8788

# Loopback bind: Bearings is single-user localhost; binding to anything else
# would expose subscription-auth to the LAN.
DEFAULT_HOST: Final[str] = "127.0.0.1"

# DB path: ``~/.local/share/bearings-v1/sessions.db`` per CLAUDE.md "Repo
# invariants". ``expanduser()`` resolves the leading ``~`` at import time so
# downstream code never has to think about it.
DEFAULT_DB_PATH: Final[Path] = Path("~/.local/share/bearings-v1/sessions.db").expanduser()

# Billing mode default — mirrors v0.17.x BillingCfg semantics so the shared
# config file at ``~/.config/bearings/config.toml`` round-trips cleanly
# during the dogfood cutover (2026-05-01). "payg" preserves the legacy
# pre-billing-knob behavior; users on Anthropic Max/Pro flip to
# "subscription" in the config to swap session-card dollar figures for
# token totals (rendering hookup is a future v1 item). Typed as the same
# ``Literal`` ``BillingCfg.mode`` declares so the Pydantic field default
# satisfies ``mypy --strict`` without an inline ``# type: ignore``.
DEFAULT_BILLING_MODE: Final[Literal["payg", "subscription"]] = "payg"
DEFAULT_BILLING_PLAN: Final[str | None] = None

# ---------------------------------------------------------------------------
# Routing / quota / usage defaults (docs/model-routing-v1-spec.md)
# ---------------------------------------------------------------------------

# Routing preview debounce after the user types in the new-session dialog
# (spec §6 "Reactive behavior" — debounced ~300 ms). The ``_MS`` companion
# is exposed so ``Settings.routing_preview_debounce_ms`` reads naturally as
# an ``int`` field; the ``timedelta`` form is the canonical value.
ROUTING_PREVIEW_DEBOUNCE: Final[timedelta] = timedelta(milliseconds=300)
ROUTING_PREVIEW_DEBOUNCE_MS: Final[int] = 300

# Quota poller cadence (spec §4 — "polls /usage every 5 minutes"). The
# seconds form is exposed for ``Settings.quota_poll_interval_s``.
USAGE_POLL_INTERVAL: Final[timedelta] = timedelta(minutes=5)
USAGE_POLL_INTERVAL_S: Final[int] = 300

# Quota guard downgrade threshold (spec §4 — "if overall_used_pct >= 0.80
# ... downgrade executor; if sonnet_used_pct >= 0.80 and executor ==
# 'sonnet' ... downgrade to haiku"). Spec §13 risk #2 admits this is a
# guess and may become user-tunable; ``Settings.quota_threshold_pct``
# already exposes the override.
QUOTA_THRESHOLD_PCT: Final[float] = 0.80

# Header quota-bar colour transitions (spec §4 + §10 "Quota bars in the
# session header" — "yellow at 80% used, red at 95%").
QUOTA_BAR_YELLOW_PCT: Final[float] = 0.80
QUOTA_BAR_RED_PCT: Final[float] = 0.95

# Override-rate "Review:" highlighting threshold (spec §8 — "Rules with
# override_rate > 0.30 over the last 14 days are surfaced ... as 'Review:'
# highlighted rows").
OVERRIDE_RATE_REVIEW_THRESHOLD: Final[float] = 0.30

# Override-rate rolling window (spec §8 + §10 "Rules to review list" —
# "rules with override rate > 30% in the last 14 days").
OVERRIDE_RATE_WINDOW: Final[timedelta] = timedelta(days=14)
OVERRIDE_RATE_WINDOW_DAYS: Final[int] = 14

# Inspector Usage headroom-chart window (spec §7 "Quota efficiency" + §10
# "Headroom remaining chart" — "rolling 7-day plot").
USAGE_HEADROOM_WINDOW: Final[timedelta] = timedelta(days=7)
USAGE_HEADROOM_WINDOW_DAYS: Final[int] = 7

# Default advisor max-uses per executor pairing (spec §2 default-policy
# table). Sonnet-paired executor gets 5; Haiku-paired gets 3 (the table
# notes Haiku consults less frequently because more turns are mechanical).
DEFAULT_ADVISOR_MAX_USES_SONNET: Final[int] = 5
DEFAULT_ADVISOR_MAX_USES_HAIKU: Final[int] = 3

# Advisor beta-header ID (spec §2 — "behind beta header
# advisor-tool-2026-03-01"). Pinned here so a future GA-without-header
# bump touches a single symbol per arch §5 #1/#2.
ADVISOR_TOOL_BETA_HEADER: Final[str] = "advisor-tool-2026-03-01"

# Spec-vocabulary effort label → SDK ``effort`` literal mapping (arch §5
# #4). The spec writes rules in ``auto``/``low``/``medium``/``high``/
# ``xhigh``; the SDK exposes ``effort`` as a literal taking
# ``low``/``medium``/``high``/``max``. Putting the table here means a
# future SDK literal addition (e.g. ``auto`` becomes a real value) is a
# one-line edit. ``None`` means "omit the field — let the SDK pick".
EFFORT_LEVEL_TO_SDK: Final[dict[str, str | None]] = {
    "auto": None,
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
}

# Executor → SDK ``fallback_model`` mapping (arch §5 #5 — "sonnet → haiku,
# opus → sonnet, haiku → haiku (no further)"). The mapping is total so
# ``EXECUTOR_FALLBACK_MODEL[executor]`` never raises ``KeyError`` for a
# valid executor name.
EXECUTOR_FALLBACK_MODEL: Final[dict[str, str]] = {
    "sonnet": "haiku",
    "opus": "sonnet",
    "haiku": "haiku",
}

# ---------------------------------------------------------------------------
# Internal-runtime defaults (docs/architecture-v1.md §1.1.2)
# ---------------------------------------------------------------------------

# Per-runner WS event ring buffer cap (arch §1.1.2 — "RING_BUFFER_MAX =
# 5000"). Bounds replay buffer growth on long-lived sessions.
RING_BUFFER_MAX: Final[int] = 5000

# Tool-call keepalive tick cadence (arch §1.1.2 — "TOOL_PROGRESS_INTERVAL_S
# = 2.0"). Per-tool-call ProgressTickerManager emits a heartbeat at this
# interval so the UI's elapsed-time readout never freezes.
TOOL_PROGRESS_INTERVAL: Final[timedelta] = timedelta(seconds=2)
TOOL_PROGRESS_INTERVAL_S: Final[float] = 2.0

# WS idle ping interval (arch §1.1.2 — "WS_IDLE_PING_INTERVAL_S = 15.0").
# Keeps long-idle WebSocket connections from being reaped by intermediate
# proxies / NATs.
WS_IDLE_PING_INTERVAL: Final[timedelta] = timedelta(seconds=15)
WS_IDLE_PING_INTERVAL_S: Final[float] = 15.0

# History prefix prime cap (arch §1.1.2 — "HISTORY_PRIME_MAX_CHARS =
# 60_000"). On runner reattach, replay no more than this many chars of
# prior conversation into the prompt prefix.
HISTORY_PRIME_MAX_CHARS: Final[int] = 60_000

# Context-pressure layer inject threshold % (arch §1.1.2 —
# "PRESSURE_INJECT_THRESHOLD_PCT = 70.0"). Above this, ``agent/prompt.py``
# inserts the ``<context-pressure>`` block so the model knows it is near
# the cap. Distinct from the auto-driver's pressure-watchdog handoff
# threshold below — that is a *halt* trigger, this is a *steering* one.
PRESSURE_INJECT_THRESHOLD_PCT: Final[float] = 70.0

# Default per-tool-call output cap (arch §1.1.2 + §4.8 SessionConfig
# default — "tool_output_cap_chars: int = 8000"). Soft cap for streaming;
# hard cap behaviour lives in tool-output-streaming behavior doc.
DEFAULT_TOOL_OUTPUT_CAP_CHARS: Final[int] = 8000

# ---------------------------------------------------------------------------
# Streaming-protocol defaults (item 1.2; docs/behavior/tool-output-streaming.md)
# ---------------------------------------------------------------------------

# Per-event ``ToolOutputDelta.delta`` cap for the wire protocol. The behavior
# doc (``docs/behavior/tool-output-streaming.md`` §"Very-long-output
# truncation rules") prescribes user-visible soft/hard caps for display
# and persistence; this constant is the *transport*-level cap that keeps
# any single WebSocket frame from exceeding a tractable size. Backend
# splits oversized deltas into multiple :class:`ToolOutputDelta` events
# preserving total payload (codepoint-safe — Python ``str`` slicing splits
# at codepoints). 64 KiB chosen so a typical 100k tool-output payload
# becomes ≤2 frames; larger values risk client-side rendering hitches.
STREAM_MAX_DELTA_CHARS: Final[int] = 64_000

# Hard cap on total per-tool-call output bytes streamed through the
# protocol. Beyond this cap the runner emits a :class:`ToolOutputDelta`
# carrying the truncation marker (``[truncated — N chars elided]``) and
# drops further deltas for that ``tool_call_id``. Per behavior doc
# §"Very-long-output truncation rules" — "the marker always appears at
# the end of the persisted body". 1 MiB chosen as a generous ceiling
# that comfortably accommodates `cargo build` / `pytest -v` style
# outputs while keeping any single tool's runaway loop from saturating
# the per-runner ring buffer.
STREAM_MAX_TOOL_OUTPUT_CHARS: Final[int] = 1_048_576

# Truncation marker template. ``{n}`` is the chars-elided count; the
# template includes the surrounding brackets to keep the contract
# inline-literal-free at the call site. Behavior-doc-mandated wording.
STREAM_TRUNCATION_MARKER_TEMPLATE: Final[str] = "\n[truncated — {n} chars elided]"

# Heartbeat ping interval for idle WebSocket connections. Aliases
# :data:`WS_IDLE_PING_INTERVAL_S` so the streaming layer's import surface
# names the concern at the call site without forcing every consumer to
# know which subsystem owns the underlying interval. The two MUST stay
# numerically equal (asserted at module import below).
STREAM_HEARTBEAT_INTERVAL_S: Final[float] = WS_IDLE_PING_INTERVAL_S

# ---------------------------------------------------------------------------
# Session module vocabulary (arch §4.1, §4.8; SDK shapes verified via
# context7 ``/anthropics/claude-agent-sdk-python`` queried 2026-04-28)
# ---------------------------------------------------------------------------

# Canonical short-name executor models the routing layer accepts as
# ``RoutingDecision.executor_model`` (spec §App A). Long-form SDK model
# IDs (e.g. ``claude-sonnet-4-5``) are accepted via the
# ``EXECUTOR_MODEL_FULL_ID_PREFIX`` test below; the two together cover
# both the user-facing vocabulary in tag rules and the SDK pinning the
# rebuild does in ``agent/options.py:build_options`` (item 1.2). The
# ``opusplan`` short name is the spec §1 alias the resolution stage
# applies when ``executor=opus`` and the user has not explicitly typed
# ``opus`` (per spec §1 "executor=opus → resolve to opusplan unless
# explicitly typed 'opus'").
KNOWN_EXECUTOR_MODELS: Final[frozenset[str]] = frozenset({"sonnet", "haiku", "opus", "opusplan"})

# A ``RoutingDecision.executor_model`` whose value starts with this
# prefix is accepted as a full SDK model ID without further short-name
# enumeration; the SDK resolves it. This is the boundary-validator side
# of arch §5 #4 "future SDK literal addition is a one-line table edit".
EXECUTOR_MODEL_FULL_ID_PREFIX: Final[str] = "claude-"

# Effort labels the spec writes routing rules in (spec §App A
# ``effort_level``). The translation to SDK ``effort`` literal lives
# already in ``EFFORT_LEVEL_TO_SDK`` above; this set is the validator
# input alphabet.
KNOWN_EFFORT_LEVELS: Final[frozenset[str]] = frozenset({"auto", "low", "medium", "high", "xhigh"})

# ``RoutingDecision.source`` valid values (spec §App A enum). The seven
# values cover every shape ``agent/routing.py:evaluate`` (item 1.8) and
# ``agent/quota.py:apply_quota_guard`` (item 1.8) can produce, plus the
# ``unknown_legacy`` carrier per spec §5 "Backfill for legacy data".
KNOWN_ROUTING_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "tag_rule",
        "system_rule",
        "default",
        "manual",
        "quota_downgrade",
        "manual_override_quota",
        "unknown_legacy",
    }
)

# Spec §3 "Match types" alphabet — what ``RoutingRule.match_type`` /
# ``SystemRoutingRule.match_type`` may be. Mirrors the SQL CHECK
# constraint on ``tag_routing_rules.match_type`` /
# ``system_routing_rules.match_type``; lifted into a constant so the
# DB-layer dataclass validator and the API-layer Pydantic input model
# share the alphabet.
KNOWN_MATCH_TYPES: Final[frozenset[str]] = frozenset(
    {"keyword", "regex", "length_gt", "length_lt", "always"}
)

# SDK ``permission_mode`` literal alphabet, per
# ``claude_agent_sdk.ClaudeAgentOptions`` (context7 query
# ``/anthropics/claude-agent-sdk-python`` 2026-04-28). Note both
# ``dontAsk`` and ``auto`` are valid current literals; v0.17.x predates
# both. ``AgentSession.set_permission_mode`` (arch §2.1 + §5 #9)
# validates against this set before forwarding to the live client.
KNOWN_SDK_PERMISSION_MODES: Final[frozenset[str]] = frozenset(
    {"default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"}
)

# SDK ``setting_sources`` literal alphabet (context7 query as above —
# the SDK accepts ``"user"``, ``"project"``, ``"local"``).
# ``SessionConfig`` validates each entry of its ``setting_sources``
# tuple against this set.
KNOWN_SDK_SETTING_SOURCES: Final[frozenset[str]] = frozenset({"user", "project", "local"})

# Permission-profile presets — Bearings' own abstraction layered on top
# of SDK ``permission_mode`` + ``allowed_tools`` + ``disallowed_tools``.
# The three presets cover the three mid-level postures: read-only
# inspection (RESTRICTED), normal day-to-day editing (STANDARD), and
# fully autonomous (EXPANDED). Profile names are user-facing strings;
# the ``PermissionProfile`` enum in ``agent/session.py`` mirrors them.
PERMISSION_PROFILE_NAMES: Final[frozenset[str]] = frozenset({"restricted", "standard", "expanded"})

# Profile → SDK ``permission_mode`` resolution table. The table values
# are validated against ``KNOWN_SDK_PERMISSION_MODES`` by an init-time
# self-check in ``agent/session.py``.
PERMISSION_PROFILE_TO_SDK_MODE: Final[dict[str, str]] = {
    "restricted": "default",
    "standard": "acceptEdits",
    "expanded": "bypassPermissions",
}

# Profile → SDK ``allowed_tools`` allowance. ``RESTRICTED`` allows
# read-only inspection tools only; ``STANDARD`` adds the everyday
# write/edit/bash set; ``EXPANDED`` is empty because under
# ``bypassPermissions`` the allowlist is moot — every tool is
# auto-approved at the SDK boundary. Tuples are immutable; the resolver
# in ``agent/session.py`` casts to ``list`` only at the SDK boundary.
PERMISSION_PROFILE_ALLOWED_TOOLS: Final[dict[str, tuple[str, ...]]] = {
    "restricted": ("Read", "Glob", "Grep", "WebFetch", "WebSearch"),
    "standard": (
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "Bash",
        "WebFetch",
        "WebSearch",
        "Task",
    ),
    "expanded": (),
}

# Profile → SDK ``disallowed_tools`` deny list. Only ``RESTRICTED``
# carries explicit denies; the other two profiles delegate to the
# permission_mode (acceptEdits / bypassPermissions).
PERMISSION_PROFILE_DISALLOWED_TOOLS: Final[dict[str, tuple[str, ...]]] = {
    "restricted": ("Bash", "Write", "Edit"),
    "standard": (),
    "expanded": (),
}

# ---------------------------------------------------------------------------
# Structural validation bounds (well-known facts; not spec-derived)
# ---------------------------------------------------------------------------

# TCP port valid-range floor / ceiling. Used by Settings.port's pydantic
# ``ge=`` / ``le=`` validators so the bounds aren't bare literals at the
# call site (per item 0.5's "no inline literals" gate).
TCP_PORT_MIN: Final[int] = 1
TCP_PORT_MAX: Final[int] = 65_535

# Percentage-as-fraction floor / ceiling (0.0 = 0 %, 1.0 = 100 %).
# Used by every ``*_pct`` Settings field so quota / override-rate
# fractions can't drift outside [0, 1].
PCT_MIN: Final[float] = 0.0
PCT_MAX: Final[float] = 1.0

# ---------------------------------------------------------------------------
# Behavioral defaults (docs/behavior/<subsystem>.md)
# ---------------------------------------------------------------------------

# Auto-driver pressure-watchdog handoff trigger (behavior/checklists.md
# §"Pressure-watchdog handoff request" — "60 % by default"). When the
# leg's reported context pressure crosses this threshold and the agent
# has not emitted a handoff sentinel, the driver injects one nudge before
# treating the quiet turn as a silent-exit failure.
CHECKLIST_DRIVER_PRESSURE_HANDOFF_THRESHOLD_PCT: Final[float] = 60.0

# Auto-driver per-item leg cap (behavior/checklists.md §"Sentinel safety
# caps" — "default 5"). After this many legs on a single item, the driver
# halts that item with ``failure_reason = max_legs_per_item exceeded``.
CHECKLIST_DRIVER_MAX_LEGS_PER_ITEM: Final[int] = 5

# Auto-driver per-run item cap (behavior/checklists.md — "default 50").
# After touching this many items in a single run, the driver halts with
# ``Halted: max items``.
CHECKLIST_DRIVER_MAX_ITEMS_PER_RUN: Final[int] = 50

# Auto-driver blocking-followup nesting cap (behavior/checklists.md —
# "default 3"). Beyond this, the followup is treated as a malformed
# sentinel and ignored.
CHECKLIST_DRIVER_MAX_FOLLOWUP_DEPTH: Final[int] = 3

# ``bearings todo recent`` default lookback (behavior/bearings-cli.md
# §"bearings todo recent" — "Lists entries that changed in the last N
# days (default 7)").
BEARINGS_TODO_RECENT_DEFAULT_DAYS: Final[int] = 7

# Auto-driver per-leg turn cap. Decided-and-documented (behavior doc is
# silent on this cap): bound the inner ``run_turn`` loop so a runaway
# leg cannot spin forever waiting for a sentinel. 20 turns chosen as
# generous-but-finite — most items resolve in 3-7 turns; a leg that has
# emitted nothing actionable after 20 turns is treated as
# ``failure_reason = "leg_turn_cap_exceeded"`` and the leg-cap path
# advances per failure-policy.
CHECKLIST_DRIVER_MAX_TURNS_PER_LEG: Final[int] = 20

# Auto-driver pressure-watchdog nudge text. Per behavior/checklists.md
# §"Pressure-watchdog handoff request" — "the driver injects one nudge
# turn ('please emit a handoff plug now') before treating a quiet turn
# as a silent-exit failure". The exact wording is observable to the
# user (one extra turn appears in the chat) so it lives here, not
# inline.
CHECKLIST_DRIVER_PRESSURE_NUDGE_TEXT: Final[str] = (
    "please emit a handoff plug now — the leg's context-window pressure "
    "has crossed the watchdog threshold."
)

# Auto-driver run-state alphabet. Mirrors the schema CHECK constraint on
# ``auto_driver_runs.state`` (per ``schema.sql``). The dataclass row
# mirror in ``db/auto_driver_runs.py`` validates against this set so a
# bad write fails at construction time rather than at INSERT time.
AUTO_DRIVER_STATE_IDLE: Final[str] = "idle"
AUTO_DRIVER_STATE_RUNNING: Final[str] = "running"
AUTO_DRIVER_STATE_PAUSED: Final[str] = "paused"
AUTO_DRIVER_STATE_FINISHED: Final[str] = "finished"
AUTO_DRIVER_STATE_ERRORED: Final[str] = "errored"
KNOWN_AUTO_DRIVER_STATES: Final[frozenset[str]] = frozenset(
    {
        AUTO_DRIVER_STATE_IDLE,
        AUTO_DRIVER_STATE_RUNNING,
        AUTO_DRIVER_STATE_PAUSED,
        AUTO_DRIVER_STATE_FINISHED,
        AUTO_DRIVER_STATE_ERRORED,
    }
)

# Auto-driver failure-policy alphabet. Per behavior/checklists.md
# §"Run-control surface" the user picks ``halt`` (default) or ``skip``
# from a dropdown next to Start. The choice applies to the next Start;
# in-flight runs honor the policy they were started with.
AUTO_DRIVER_FAILURE_POLICY_HALT: Final[str] = "halt"
AUTO_DRIVER_FAILURE_POLICY_SKIP: Final[str] = "skip"
KNOWN_AUTO_DRIVER_FAILURE_POLICIES: Final[frozenset[str]] = frozenset(
    {AUTO_DRIVER_FAILURE_POLICY_HALT, AUTO_DRIVER_FAILURE_POLICY_SKIP}
)

# Item non-completion category alphabet, carried on
# ``checklist_items.blocked_reason_category``. Per behavior/checklists.md
# §"Item-status colors" the user observes blocked (amber), failed (red)
# and skipped (grey) as distinct colors; the schema's ``blocked_*``
# columns serve as the generic "non-completion observable" surface
# (decided-and-documented — the schema header comment names the columns
# as the sentinel-blocked surface, but the same triple naturally carries
# any non-completion category, and the alternative — three parallel
# ``<state>_at`` columns — would triplicate the schema for no semantic
# gain). The category drives the pip color the UI renders.
ITEM_OUTCOME_BLOCKED: Final[str] = "blocked"
ITEM_OUTCOME_FAILED: Final[str] = "failed"
ITEM_OUTCOME_SKIPPED: Final[str] = "skipped"
KNOWN_ITEM_OUTCOMES: Final[frozenset[str]] = frozenset(
    {ITEM_OUTCOME_BLOCKED, ITEM_OUTCOME_FAILED, ITEM_OUTCOME_SKIPPED}
)

# Sentinel kind alphabet. Per behavior/checklists.md §"Sentinels
# (auto-pause / failure / completion)" the user observes six sentinel
# kinds the working agent emits; a malformed / incomplete sentinel is
# silently ignored (the parser must not act on a half-emitted block).
# Decided-and-documented: the wire format is the
# ``<bearings:sentinel kind="..." />`` tag form; rationale lives in
# ``agent/sentinel.py``'s docstring.
SENTINEL_KIND_ITEM_DONE: Final[str] = "item_done"
SENTINEL_KIND_HANDOFF: Final[str] = "handoff"
SENTINEL_KIND_FOLLOWUP_BLOCKING: Final[str] = "followup_blocking"
SENTINEL_KIND_FOLLOWUP_NONBLOCKING: Final[str] = "followup_nonblocking"
SENTINEL_KIND_ITEM_BLOCKED: Final[str] = "item_blocked"
SENTINEL_KIND_ITEM_FAILED: Final[str] = "item_failed"
KNOWN_SENTINEL_KINDS: Final[frozenset[str]] = frozenset(
    {
        SENTINEL_KIND_ITEM_DONE,
        SENTINEL_KIND_HANDOFF,
        SENTINEL_KIND_FOLLOWUP_BLOCKING,
        SENTINEL_KIND_FOLLOWUP_NONBLOCKING,
        SENTINEL_KIND_ITEM_BLOCKED,
        SENTINEL_KIND_ITEM_FAILED,
    }
)

# Driver outcome strings observed by the user on the status line freeze
# (per behavior/checklists.md §"Run-control surface"). Templates so the
# item-N substitution is explicit at the call site.
DRIVER_OUTCOME_COMPLETED: Final[str] = "Completed"
DRIVER_OUTCOME_HALTED_FAILURE_TEMPLATE: Final[str] = "Halted: failure on item {n}"
DRIVER_OUTCOME_HALTED_MAX_ITEMS: Final[str] = "Halted: max items"
DRIVER_OUTCOME_HALTED_STOPPED: Final[str] = "Halted: stopped by user"
DRIVER_OUTCOME_HALTED_EMPTY: Final[str] = "Halted: empty"

# Spawned-by alphabet for ``paired_chats.spawned_by``. Mirrors the
# schema CHECK constraint.
PAIRED_CHAT_SPAWNED_BY_USER: Final[str] = "user"
PAIRED_CHAT_SPAWNED_BY_DRIVER: Final[str] = "driver"
KNOWN_PAIRED_CHAT_SPAWNED_BY: Final[frozenset[str]] = frozenset(
    {PAIRED_CHAT_SPAWNED_BY_USER, PAIRED_CHAT_SPAWNED_BY_DRIVER}
)

# Checklist item label / notes / blocked-reason maxima. Mirrors the
# label-cap pattern used for tag names / template names so user-facing
# labels share a single character budget.
CHECKLIST_ITEM_LABEL_MAX_LENGTH: Final[int] = 500
CHECKLIST_ITEM_NOTES_MAX_LENGTH: Final[int] = 30_000
CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH: Final[int] = 4_000

# Sort-order step between siblings. Decided-and-documented: leave gaps
# so a future "insert between A and B" works without a full renumber
# (assign mid-point). The :func:`reorder` path renumbers compactly when
# the gap collapses below the step.
CHECKLIST_SORT_ORDER_STEP: Final[int] = 100

# ---------------------------------------------------------------------------
# Checkpoints + templates (item 1.3; arch §1.1.3 db/checkpoints.py +
# db/templates.py; arch §5 #12 — Bearings owns its named-snapshot
# checkpoints rather than the SDK ``enable_file_checkpointing``
# automatic-write-snapshot primitive; behavior surfaces in
# ``docs/behavior/chat.md`` §"Slash commands in the composer" /``
# docs/behavior/context-menus.md`` §"Checkpoint (gutter chip)" / §"Session
# row" ``session.save_as_template``).
# ---------------------------------------------------------------------------

# Per-session ceiling on stored checkpoints. The behavior docs do not
# mandate a retention policy; this constant is the runtime-tunable
# default the API layer (item 1.10) enforces when ``checkpoints.create``
# would push a session past the cap. Chosen high enough that a
# disciplined user almost never bumps into it (typical session has 1-5
# checkpoints) yet low enough that a runaway client cannot bloat the DB.
MAX_CHECKPOINTS_PER_SESSION: Final[int] = 50

# Default label applied when the user invokes the ``/checkpoint`` slash
# command without an explicit label. The ``{n}`` placeholder is the
# 1-indexed ordinal of the checkpoint within the session (filled by the
# DB helper at create time); per ``docs/behavior/chat.md`` §"Slash
# commands" the label is what surfaces in the gutter chip the user
# right-clicks on per ``docs/behavior/context-menus.md`` §"Checkpoint".
DEFAULT_CHECKPOINT_LABEL_TEMPLATE: Final[str] = "Checkpoint {n}"

# Maximum length the API layer accepts on a checkpoint label / template
# name / template description. Caps protect the WS frame and the gutter
# chip's render width without quoting a UI-pixel number; chosen to be
# generous (a typical label is ≤40 chars) but bounded.
CHECKPOINT_LABEL_MAX_LENGTH: Final[int] = 200
TEMPLATE_NAME_MAX_LENGTH: Final[int] = 200
TEMPLATE_DESCRIPTION_MAX_LENGTH: Final[int] = 1000

# Default template field values when a user creates a template via the
# ``session.save_as_template`` context-menu action without overriding
# the routing/permission fields. Mirror the spec §3 default routing
# rule (priority 1000, ``always`` match, sonnet+opus advisor, auto
# effort) and the standard permission profile, so a "save current as
# template" with no edits produces a workhorse-default preset.
DEFAULT_TEMPLATE_MODEL: Final[str] = "sonnet"
DEFAULT_TEMPLATE_ADVISOR_MODEL: Final[str | None] = "opus"
DEFAULT_TEMPLATE_ADVISOR_MAX_USES: Final[int] = 5
DEFAULT_TEMPLATE_EFFORT_LEVEL: Final[str] = "auto"
DEFAULT_TEMPLATE_PERMISSION_PROFILE: Final[str] = "standard"

# ---------------------------------------------------------------------------
# Tags + tag memories (item 1.4; arch §1.1.3 ``db/tags.py`` +
# ``db/memories.py``; arch §1.1.5 ``web/routes/tags.py`` +
# ``web/routes/memories.py``; behavior surfaces in ``docs/behavior/chat.md``
# §"When the user creates a chat", ``docs/behavior/checklists.md``
# §"…inherits the checklist's working directory, model, and tags",
# ``docs/behavior/context-menus.md`` §"Tag (sidebar tag chip in the filter
# panel)" + §"Tag chip (attached to a session, …)"). Spec §App A pins the
# allowed alphabet for ``tags.default_model`` (mirrors templates' validator
# in ``db/templates.py``).
# ---------------------------------------------------------------------------

# Tag-name maximum length. Tag names surface as sidebar filter chips and
# inside the new-session-dialog tag picker (per ``docs/behavior/chat.md``
# §"When the user creates a chat"); the cap is generous enough for the
# slash-namespaced names the rebuild's test fixtures use
# (``bearings/architect`` ≈ 18 chars) and for arbitrary user labels,
# while bounded so the tag-picker dropdown doesn't try to render a
# pathological name. Mirrors :data:`TEMPLATE_NAME_MAX_LENGTH` for
# consistency across user-facing label fields.
TAG_NAME_MAX_LENGTH: Final[int] = 200

# Tag-color maximum length. Colors are user-supplied free-text per the
# ``tags.color`` schema column (no CHECK constraint at the schema level
# — the color field is purely cosmetic and validation is the API
# layer's job). Cap chosen long enough for ``rgba(...)`` / ``oklch(...)``
# strings without needing a CSS parser at the wire boundary; short
# enough that an absurd value can't bloat the row.
TAG_COLOR_MAX_LENGTH: Final[int] = 64

# Tag-group separator. The schema does not declare a separate
# ``tag_groups`` table; tag groups are expressed by slash-namespacing
# the tag name (``<group>/<name>``). The separator is a single character
# so the group prefix is unambiguous and a bare name (no separator) is
# treated as the unnamed/default group. Decided-and-documented per the
# item-1.4 done-when's "tag groups" requirement: the schema landed in
# 0.4 with no group column, so the rebuild adopts the slash-namespace
# convention already in test fixtures (``bearings/architect``,
# ``bearings/exec``).
TAG_GROUP_SEPARATOR: Final[str] = "/"

# Tag-memory title maximum length. Titles surface in the memories editor
# UI (per ``docs/behavior/vault.md`` cross-reference) as a one-line
# summary above the body editor; same cap as tag names so the two label
# surfaces share a single character budget.
TAG_MEMORY_TITLE_MAX_LENGTH: Final[int] = 200

# Tag-memory body maximum length. Memories are system-prompt fragments
# (per arch §1.1.3 — "tag memories as system-prompt fragments that the
# prompt assembler reads per turn"); the cap bounds any single fragment
# so a runaway memory cannot saturate the prompt-prime budget
# :data:`HISTORY_PRIME_MAX_CHARS` upstream. Chosen at half of that
# budget so up to two large memories can coexist.
TAG_MEMORY_BODY_MAX_LENGTH: Final[int] = 30_000

# ---------------------------------------------------------------------------
# Prompt endpoint (item 1.7; arch §1.1.5 ``web/routes/sessions.py``;
# behavior surface in ``docs/behavior/prompt-endpoint.md``).
#
# The behavior doc is silent on the exact rate-limit numbers
# ("per-session POST rate over the configured window") — values below
# are decided-and-documented. Chosen to comfortably accommodate
# orchestrator-driver bursts (an orchestrator dispatches a few prompts
# in quick succession at handoff) while still throttling a runaway
# loop. Tunable via ``Settings`` if usage shows the defaults are wrong.
# ---------------------------------------------------------------------------

# Per-session sliding window for the rate-limit gate (behavior doc
# §"Rate-limit observable behavior"). One minute is short enough that
# ``Retry-After`` is a tractable wait; long enough to absorb a tight
# burst from a dispatcher.
PROMPT_RATE_LIMIT_WINDOW: Final[timedelta] = timedelta(seconds=60)
PROMPT_RATE_LIMIT_WINDOW_S: Final[int] = 60

# Maximum POSTs per session per window. 30 chosen so a 10-step dispatch
# loop has 3x headroom; the user-facing typing path never reaches
# anything close because keystroke->Send is human-paced.
PROMPT_RATE_LIMIT_MAX_PER_WINDOW: Final[int] = 30

# Maximum prompt content length (characters). Behavior doc is silent on
# a hard cap; the prompt assembler's history-prime budget upstream is
# 60K chars (HISTORY_PRIME_MAX_CHARS), so a single user prompt above
# that would never fit in a turn anyway. 64 KiB chosen as a generous
# bound that still rejects pathological pastes and protects the runner
# queue from a runaway client.
PROMPT_CONTENT_MAX_CHARS: Final[int] = 64_000

# Wire-shape ack body keys (behavior doc §"202 semantics" — the body is
# a small JSON envelope with ``queued: true`` + ``session_id``). Pinned
# as constants so a future shape edit touches one symbol per
# coding-standards "no string-literal magic".
PROMPT_ACK_QUEUED_KEY: Final[str] = "queued"
PROMPT_ACK_SESSION_ID_KEY: Final[str] = "session_id"

# ---------------------------------------------------------------------------
# Sessions (item 1.7; arch §1.1.3 ``db/sessions.py``; behavior surface
# in ``docs/behavior/chat.md`` + ``docs/behavior/paired-chats.md``).
#
# Session-row constants: kind alphabet, id prefix, title bounds. The
# kind alphabet mirrors schema.sql's CHECK constraint.
# ---------------------------------------------------------------------------

# Session kind discriminator alphabet. Schema CHECK constraint:
# ``kind IN ('chat', 'checklist')``. The kind partitions the session
# table into two surfaces (chat = composer + transcript;
# checklist = structured-list pane); the prompt-endpoint accepts both
# (per behavior doc "only chat-kind and checklist-kind sessions are
# runnable").
SESSION_KIND_CHAT: Final[str] = "chat"
SESSION_KIND_CHECKLIST: Final[str] = "checklist"
KNOWN_SESSION_KINDS: Final[frozenset[str]] = frozenset({SESSION_KIND_CHAT, SESSION_KIND_CHECKLIST})

# Session id prefix. ``ses_<32-hex>`` per the ``new_id`` convention in
# ``db/_id.py`` so a stray id in a log line is self-describing.
SESSION_ID_PREFIX: Final[str] = "ses"

# Message id prefix. Each user / assistant / tool / system message row
# carries a ``msg_<32-hex>`` primary key.
MESSAGE_ID_PREFIX: Final[str] = "msg"

# Session title cap. Sidebar rows render the title; cap chosen wide
# enough for descriptive titles, narrow enough that a runaway label
# does not bloat the row height.
SESSION_TITLE_MAX_LENGTH: Final[int] = 500

# Session description cap. The description (also called the "plug")
# carries hand-off context for orchestrator/executor patterns; budget
# matches checklist-item notes for consistency.
SESSION_DESCRIPTION_MAX_LENGTH: Final[int] = 30_000

# Closing-summary bounds (the agent-authored 1-3 sentence summary the
# ``close_session`` MCP tool stamps when judging the user's task done).
# Plan §"Slice B" pins the wire shape at 1-2000 chars: long enough for a
# multi-sentence summary, short enough to render as a hover tooltip on
# a closed sidebar row without overflow.
SESSION_CLOSING_SUMMARY_MIN_LENGTH: Final[int] = 1
SESSION_CLOSING_SUMMARY_MAX_LENGTH: Final[int] = 2_000

# ---------------------------------------------------------------------------
# Bearings-internal MCP server (item Slice B / dogfood-unblock plan).
#
# The agent reaches Bearings-internal capability via an in-process MCP
# server registered on ``ClaudeAgentOptions.mcp_servers``. The server
# name and the tool name are constants because they appear in three
# places: the SDK options wiring (item 1.3+), the agent system-prompt
# instruction text, and the test fixtures that exercise the tool
# directly.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Idle-reap (Slice A5 of wiring-agent-loop.md). Per sign-off Q3
# (accepted 2026-05-01) the threshold is 600s with a 60s poll cadence:
# matches the v0.17.x behavior-doc-cited "long-idle teardown is
# server-side transparent" feel without thrashing the SDK subprocess.
# A session goes idle when it has zero subscribers AND zero queued
# prompts; the reaper polls last_active_ns and cancels the supervisor
# task so the SDK subprocess closes. The next prompt POST re-spawns
# transparently per behavior doc §"long-idle teardown".
# ---------------------------------------------------------------------------

# Seconds without activity before a session's supervisor is reaped.
IDLE_REAP_THRESHOLD_S: Final[int] = 600

# Poll cadence for the reaper task. Tests inject a much smaller
# value via the constants-module monkey-patch fixture.
IDLE_REAP_POLL_INTERVAL_S: Final[int] = 60

# ---------------------------------------------------------------------------

# Server name on ``ClaudeAgentOptions.mcp_servers``. Agents reference
# tools as ``mcp__<server>__<tool>``; the SDK builds that handle from
# the key the consumer puts in the ``mcp_servers`` mapping. Keeping the
# server name here means the system-prompt instruction can render the
# fully-qualified tool name without inline literals.
BEARINGS_MCP_SERVER_NAME: Final[str] = "bearings"

# ``close_session`` tool name. Agent-facing surface; do not rename
# without coordinating with the system-prompt instruction text and any
# allowed-tools allowlist that pins the namespaced form.
CLOSE_SESSION_TOOL_NAME: Final[str] = "close_session"

# ---------------------------------------------------------------------------
# Bearings CLI (item 1.7; arch §1.1.1 ``cli/`` package; behavior surface
# in ``docs/behavior/bearings-cli.md``).
#
# Exit codes per behavior doc §"Common observable conventions":
#   0 — success.
#   1 — operation-level failure (always paired with stderr message).
#   2 — usage / validation error (argparse-style stderr message).
# ---------------------------------------------------------------------------

CLI_EXIT_OK: Final[int] = 0
CLI_EXIT_OPERATION_FAILURE: Final[int] = 1
CLI_EXIT_USAGE_ERROR: Final[int] = 2

# ``bearings todo check`` default max-age (behavior doc §"bearings todo
# check" — "linter checks staleness"). Decided-and-documented (doc
# silent on default): 30 days matches a typical project review cadence.
BEARINGS_TODO_CHECK_DEFAULT_MAX_AGE_DAYS: Final[int] = 30

# ---------------------------------------------------------------------------
# Per-message persistence — ``ResultMessage.model_usage`` projection
# (item 1.9; spec §5 + arch §5 #3).
#
# The SDK exposes ``ResultMessage.model_usage`` as ``dict[str, Any] | None``
# (verified via the installed ``claude_agent_sdk.types.ResultMessage``
# dataclass shape, 2026-04-28). At runtime each value is a per-model dict
# whose token-bucket keys mirror the Anthropic API convention for the
# Messages endpoint's usage block. Pinning the key names here as named
# constants means a future SDK rename (e.g. ``input_tokens`` →
# ``inputTokens``) is a one-line edit; without these, the projection
# in ``agent/persistence.py`` would carry inline literals that the
# auditor flags per coding-standards §"no inline string literals".
# ---------------------------------------------------------------------------
MODEL_USAGE_KEY_INPUT_TOKENS: Final[str] = "input_tokens"
MODEL_USAGE_KEY_OUTPUT_TOKENS: Final[str] = "output_tokens"
# Cache-read token bucket. The Anthropic Messages API uses
# ``cache_read_input_tokens``; the SDK forwards the same key on the
# per-model dict.
MODEL_USAGE_KEY_CACHE_READ_TOKENS: Final[str] = "cache_read_input_tokens"

# ``GET /api/sessions/{id}/messages`` page-size cap. The endpoint
# returns the full transcript by default — for very long sessions a
# client may pass ``limit`` to fetch only the tail. Cap chosen wide
# enough to cover typical sessions (a few hundred messages) while
# still bounding the worst-case payload size at the wire boundary.
MESSAGES_LIST_DEFAULT_LIMIT: Final[int | None] = None
MESSAGES_LIST_MAX_LIMIT: Final[int] = 1000

# Page size for cursor-based message pagination (item 1.3). The
# session-open fetch uses this as the tail limit; each ``loadOlder()``
# call walks back by the same window. 100 rows is well under the ~5 MB
# payload threshold for a typical Bearings session.
MESSAGE_PAGE_SIZE: Final[int] = 100

# The TODO.md filename the walker recognises. Pinned constant so a
# future per-project rename touches one symbol.
BEARINGS_TODO_FILENAME: Final[str] = "TODO.md"

# Heading level the parser recognises as an entry boundary. Behavior
# doc §"bearings todo open" — entries are "## Heading" blocks; H1 is
# the file title, H3+ is body subsection. Pinned so a future spec
# tweak (e.g. H3 entries) is one edit.
BEARINGS_TODO_ENTRY_HEADING_PREFIX: Final[str] = "## "

# Walker depth cap — how deep below CWD the walker will descend looking
# for TODO.md files. Decided-and-documented: typical projects are
# ≤6 deep (monorepo-with-packages); 8 chosen as a generous bound that
# stops a pathological ``find /`` from happening if the user mistakenly
# runs the CLI from ``$HOME``.
BEARINGS_TODO_WALK_MAX_DEPTH: Final[int] = 8

# ---------------------------------------------------------------------------
# Vault (item 1.5; arch §1.1.3 ``db/vault.py`` + §1.1.5
# ``web/routes/vault.py``; behavior surface in
# ``docs/behavior/vault.md``).
# ---------------------------------------------------------------------------

# Default plan-root directory. Per ``docs/behavior/vault.md`` §"Vault
# entry types" — "Plans — `.md` files directly under any configured
# plan root (e.g. `~/.claude/plans/`)". Resolved at import time so
# downstream code never re-expands ``~``.
DEFAULT_VAULT_PLAN_ROOT: Final[Path] = Path("~/.claude/plans").expanduser()

# Default TODO-glob pattern. Per vault.md §"Vault entry types" —
# "Todos — `TODO.md` files matched by the configured glob set (e.g.
# `~/Projects/**/TODO.md`)". Stored as a string template because
# :func:`glob.iglob` accepts the absolute pattern verbatim;
# :class:`pathlib.Path`'s ``**`` expansion has subtler semantics that
# the recursive-glob path doesn't need here.
DEFAULT_VAULT_TODO_GLOB: Final[str] = str(Path("~/Projects/**/TODO.md").expanduser())

# Vault-entry kind discriminator alphabet. Mirrors the schema's
# ``CHECK (kind IN ('plan', 'todo'))`` constraint so a future schema
# amendment is a one-line edit here plus a one-line edit in
# ``schema.sql``.
VAULT_KIND_PLAN: Final[str] = "plan"
VAULT_KIND_TODO: Final[str] = "todo"
KNOWN_VAULT_KINDS: Final[frozenset[str]] = frozenset({VAULT_KIND_PLAN, VAULT_KIND_TODO})

# Per-line snippet cap for search hits. Per vault.md §"Search
# semantics" — "a snippet of the matching line (trimmed to a hard cap;
# long single-line entries wrap inside the snippet container)". Chosen
# wide enough that a typical line of prose fits in full while keeping
# pathological JSON-blob lines from saturating the response.
VAULT_SEARCH_SNIPPET_MAX_CHARS: Final[int] = 240

# Vault search result hard-cap. Per vault.md §"Search semantics" —
# "Result count has a hard cap; when the cap is reached the user sees
# a 'showing first N — narrow your query for more' indicator". The
# server returns at most this many hits and a ``capped`` flag so the
# pane stays scannable.
VAULT_SEARCH_RESULT_CAP: Final[int] = 200

# Vault file body soft-cap. Vault docs are user-authored markdown; the
# largest plan in this rebuild is ≈60 KB, but a runaway TODO.md could
# hit pathological sizes. 1 MiB chosen so a runaway file returns a
# truncated body marker rather than wedging the API. Mirrors
# :data:`STREAM_MAX_TOOL_OUTPUT_CHARS` to keep the truncation
# vocabulary consistent across surfaces.
VAULT_BODY_MAX_CHARS: Final[int] = 1_048_576

# Body-truncation marker. Mirrors
# :data:`STREAM_TRUNCATION_MARKER_TEMPLATE` — same wording, same
# ``{n}`` placeholder for chars-elided count, so two different
# truncation surfaces look identical in the rendered body.
VAULT_BODY_TRUNCATION_MARKER_TEMPLATE: Final[str] = "\n[truncated — {n} chars elided]"

# Redaction keyword set. Per vault.md §"Redaction rendering" —
# "Detects common secret shapes (high-entropy strings adjacent to
# keywords like `key`, `token`, `secret`, `password`)". The matcher
# applies these case-insensitively against the left-hand side of an
# ``=``/``:`` separator; values that follow are masked.
VAULT_REDACTION_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"key", "token", "secret", "password", "passwd", "apikey", "api_key", "auth"}
)

# Minimum length of a redaction value. Below this, a token-looking
# fragment is too short to be a real secret in practice (e.g.
# ``key=on``); the heuristic skips the match to avoid false positives
# on short config flags. Vault.md is silent on the threshold so this
# is decided-and-documented.
VAULT_REDACTION_MIN_VALUE_CHARS: Final[int] = 12

# Mask glyph for redacted values (vault.md §"Redaction rendering" —
# "replaces the visible text with a `••••••••` mask"). Eight bullets
# matches the spec mock; expressed as repetition of the single Unicode
# bullet so a cosmetic change is one tweak.
VAULT_REDACTION_MASK_GLYPH: Final[str] = "•" * 8

# Vault path safety: the maximum number of path components a single
# search result line is allowed to scan before bailing — defensive
# bound against pathological binary files that slipped past the
# extension filter. Vault docs are markdown (``.md`` filter at
# scan time) so this rarely fires; the bound prevents a one-off
# rogue file from monopolising the search loop.
VAULT_SEARCH_MAX_LINES_PER_DOC: Final[int] = 100_000


# ---------------------------------------------------------------------------
# Uploads (item 1.10; arch §1.1.5 ``web/routes/uploads.py``).
#
# The behavior docs are silent on the upload-endpoint shape — chat.md
# references "attachment chips" only at the UI surface, with no contract
# for where bytes land or how they are addressed. The route below is
# decided-and-documented:
#
#   * Content-addressed storage: the sha256 of the body is the natural
#     primary key. Hash collisions return the existing row instead of
#     writing twice — duplicate uploads are deduped at zero cost.
#   * On-disk layout: ``<storage_root>/<sha256[:2]>/<sha256>``. The
#     two-character shard keeps any one directory below ~256 entries
#     after a full hash space sweep, which is well-behaved on every
#     filesystem the rebuild targets.
#   * Per-row metadata: id, sha256, filename (user-supplied), mime_type
#     (UploadFile.content_type or octet-stream fallback), size,
#     created_at.
# ---------------------------------------------------------------------------

# Hard cap on a single upload body (bytes). 10 MiB is generous for the
# attachment-chip use case (screenshots, small PDFs, plain-text logs)
# while bounding worst-case disk pressure on a runaway client.
MAX_UPLOAD_SIZE_BYTES: Final[int] = 10 * 1024 * 1024

# Default on-disk storage root for upload bodies. Mirrors
# :data:`DEFAULT_DB_PATH` so the rebuild's per-instance state lives
# under one XDG-shaped tree (``~/.local/share/bearings-v1/``). Resolved
# at import time so downstream code never re-expands ``~``.
DEFAULT_UPLOADS_STORAGE_ROOT: Final[Path] = Path("~/.local/share/bearings-v1/uploads").expanduser()

# Number of leading hex chars from the sha256 used as the shard
# subdirectory name. Two chars = 256 buckets; aligned with the git
# object-store convention so a power user reading the on-disk layout
# recognises the shape immediately.
UPLOADS_SHA256_SHARD_CHARS: Final[int] = 2

# Upload row id prefix — ``upl_<integer>``. Mirrors the
# ``ses_``/``msg_`` convention (``SESSION_ID_PREFIX`` /
# ``MESSAGE_ID_PREFIX``) so a stray id in a log line is self-describing.
UPLOAD_ID_PREFIX: Final[str] = "upl"

# Upload filename / mime-type bounds. Filenames surface in the
# ``UploadOut`` wire shape and the future "attachment chip" UI;
# mime-types are user-supplied via ``UploadFile.content_type`` (with
# the ``UPLOAD_DEFAULT_MIME_TYPE`` fallback below) and need a bound so
# a hand-crafted malicious header cannot bloat the row.
UPLOAD_FILENAME_MAX_LENGTH: Final[int] = 500
UPLOAD_MIME_TYPE_MAX_LENGTH: Final[int] = 200

# Fallback mime-type when the multipart-form-data part has no
# ``Content-Type`` header. RFC 2046 §4.5.1 names octet-stream as the
# generic-binary fallback.
UPLOAD_DEFAULT_MIME_TYPE: Final[str] = "application/octet-stream"

# ``GET /api/uploads`` page-size defaults. The list returns newest-first;
# the cap bounds worst-case payload size for a long-running instance.
UPLOADS_LIST_DEFAULT_LIMIT: Final[int] = 100
UPLOADS_LIST_MAX_LIMIT: Final[int] = 1000

# Streaming chunk size for ``GET /api/uploads/{id}/content``. Mirrors
# :data:`STREAM_MAX_DELTA_CHARS` order-of-magnitude (64 KiB) so the
# wire-frame budget is consistent across surfaces.
UPLOAD_STREAM_CHUNK_BYTES: Final[int] = 64 * 1024

# ---------------------------------------------------------------------------
# Filesystem read/list (item 1.10; arch §1.1.5 ``web/routes/fs.py``).
#
# vault.md is plan/todo-specific (the vault is a curated read-only index
# of plans + TODOs); the ``/api/fs/*`` endpoint is the general-purpose
# filesystem walker arch §1.1.5 names. Decided-and-documented because
# no behavior doc covers the general-walk surface:
#
#   * Inputs are absolute paths only. Relative paths are rejected at
#     the validator boundary — no implicit "relative to what?" guess.
#   * Path safety is realpath-based: ``os.path.realpath(raw)`` resolves
#     ``..``, symlinks, and ``//``-style normalisation in one pass.
#     The resolved path must start with one of ``FsCfg.allow_roots``'s
#     own realpaths; otherwise the route returns 403.
#   * Read responses are utf-8 with ``errors="replace"`` so a binary
#     file does not crash the decoder; an explicit binary-detect step
#     is omitted in v1 (the size cap below makes a runaway binary read
#     bounded anyway).
# ---------------------------------------------------------------------------

# Hard cap on a single ``GET /api/fs/read`` response body (bytes). The
# cap bounds worst-case payload size at the wire boundary; over-cap
# files return 413 (no truncation marker — the FS surface is read-as-
# is, vault.md owns the marker convention).
FS_READ_MAX_BYTES: Final[int] = 1024 * 1024

# Hard cap on entries returned by a single ``GET /api/fs/list``. A
# directory with more children than this returns the first
# ``FS_LIST_MAX_ENTRIES`` plus a ``capped=true`` flag in the wire
# shape; clients that need a deeper view drill into a subdirectory.
FS_LIST_MAX_ENTRIES: Final[int] = 5000

# Filesystem-entry kind alphabet. Mirrors the ``stat`` shapes the
# walker recognises; ``other`` covers FIFOs / sockets / block devices
# / character devices in one bucket so the wire shape stays tractable.
FS_ENTRY_KIND_FILE: Final[str] = "file"
FS_ENTRY_KIND_DIR: Final[str] = "dir"
FS_ENTRY_KIND_SYMLINK: Final[str] = "symlink"
FS_ENTRY_KIND_OTHER: Final[str] = "other"
KNOWN_FS_ENTRY_KINDS: Final[frozenset[str]] = frozenset(
    {
        FS_ENTRY_KIND_FILE,
        FS_ENTRY_KIND_DIR,
        FS_ENTRY_KIND_SYMLINK,
        FS_ENTRY_KIND_OTHER,
    }
)

# ---------------------------------------------------------------------------
# Shell exec (item 1.10; arch §1.1.5 ``web/routes/shell.py``).
#
# tool-output-streaming.md documents agent-side tool calls (Bash, Edit,
# Read, etc.) — the UI never invokes a shell on the user's behalf. The
# route below is a user-side dispatch surface (e.g., "open this in the
# system editor"). Decided-and-documented:
#
#   * ``subprocess.run`` with ``shell=False`` always; the API never
#     accepts a shell-string and never spawns ``sh -c``.
#   * argv[0] must be a member of ``ALLOWED_SHELL_COMMANDS``; this is
#     the API-level allowlist. Power users override via
#     ``ShellCfg.allowed_commands`` in TOML.
#   * Bounded timeout — :data:`SHELL_EXEC_TIMEOUT_S`. A timeout returns
#     504 Gateway Timeout (the spawned process is killed first).
# ---------------------------------------------------------------------------

# Per-call wall-clock cap. 30 s is generous for the "open in editor"
# flow without letting a runaway spawn block the route forever.
SHELL_EXEC_TIMEOUT_S: Final[float] = 30.0

# Per-call output cap (bytes, per stream). 1 MiB matches the FS read
# cap so the two surfaces share a budget.
SHELL_OUTPUT_MAX_BYTES: Final[int] = 1024 * 1024

# argv length cap. Keeps a hand-crafted payload from bloating the
# request body / log lines without rejecting the legitimate
# ``xdg-open <path>``-style two-element argv.
SHELL_ARGV_MAX_ENTRIES: Final[int] = 64
SHELL_ARGV_ENTRY_MAX_LENGTH: Final[int] = 4_000

# Default shell-command allowlist. Strict least-privilege: only
# ``xdg-open`` (the standard "open in associated app" dispatcher on
# Linux) plus the two POSIX no-ops ``echo`` / ``true`` (kept as
# integration-test handles so the test surface does not require
# overriding the allowlist). Power users extend via
# ``ShellCfg.allowed_commands`` in TOML.
DEFAULT_ALLOWED_SHELL_COMMANDS: Final[frozenset[str]] = frozenset({"xdg-open", "echo", "true"})

# ---------------------------------------------------------------------------
# Diagnostics (item 1.10; arch §1.1.5 ``web/routes/diag.py``).
#
# Localhost-only per project CLAUDE.md (Bearings is single-user; no
# auth in v1). Surfaces internal runtime state for debugging; the
# 1.3 audit carry-forward applies — diag MUST NOT expose checkpoint
# state via SDK ``enable_file_checkpointing`` primitives. Bearings
# checkpoints (item 1.3) are the table-fork semantic per arch §5
# row 12 and are surfaced via the dedicated ``checkpoints`` route
# group, not via diag.
# ---------------------------------------------------------------------------

# Cap on the per-runner / per-driver list lengths the diag endpoints
# return. A reasonable headroom over the steady-state fleet size while
# bounding worst-case payloads.
DIAG_RUNNER_SAMPLE_LIMIT: Final[int] = 200
DIAG_DRIVER_SAMPLE_LIMIT: Final[int] = 200

# ---------------------------------------------------------------------------
# Health (item 1.10; arch §1.1.5 ``web/routes/health.py``).
#
# ``GET /api/health`` returns 200 always — the readiness signal is the
# JSON ``db_ok`` field, not the HTTP status. This matches the systemd
# / external-monitor convention where 200 means "the server is alive
# and accepting traffic" and the body carries the deeper readiness
# breakdown.
# ---------------------------------------------------------------------------

HEALTH_STATUS_OK: Final[str] = "ok"
HEALTH_STATUS_DEGRADED: Final[str] = "degraded"
KNOWN_HEALTH_STATUSES: Final[frozenset[str]] = frozenset({HEALTH_STATUS_OK, HEALTH_STATUS_DEGRADED})

# DB liveness probe. ``SELECT 1`` is universally valid SQL with
# zero side effects.
HEALTH_DB_PROBE_QUERY: Final[str] = "SELECT 1"

# ---------------------------------------------------------------------------
# Metrics (item 1.10; arch §1.1.5 ``web/routes/metrics.py`` + arch §1.1.7
# ``bearings.metrics`` package).
#
# Prometheus text exposition is the single supported format in v1
# (OpenMetrics is wire-compatible for the surfaces below). Metric
# names use the Prometheus convention: snake_case, ``_total`` suffix
# for counters, unit suffix for gauges, ``_info`` for "build info"
# style gauges.
# ---------------------------------------------------------------------------

METRICS_CONTENT_TYPE: Final[str] = "text/plain; version=0.0.4; charset=utf-8"

METRIC_NAME_INFO: Final[str] = "bearings_info"
METRIC_NAME_UPTIME_SECONDS: Final[str] = "bearings_uptime_seconds"
METRIC_NAME_ACTIVE_RUNNERS: Final[str] = "bearings_active_runners"
METRIC_NAME_QUEUED_PROMPTS: Final[str] = "bearings_queued_prompts"
METRIC_NAME_ACTIVE_DRIVERS: Final[str] = "bearings_active_drivers"
METRIC_NAME_QUOTA_OVERALL: Final[str] = "bearings_quota_overall_used_pct"
METRIC_NAME_QUOTA_SONNET: Final[str] = "bearings_quota_sonnet_used_pct"
METRIC_NAME_ROUTING_DECISIONS_TOTAL: Final[str] = "bearings_routing_decisions_total"
METRIC_NAME_ADVISOR_CALLS_TOTAL: Final[str] = "bearings_advisor_calls_total"

# ---------------------------------------------------------------------------
# OpenAPI export (item 1.10; FastAPI auto-generates ``/openapi.json``).
#
# Title + version flow into the spec's ``info`` block; tag names group
# operations in the rendered docs. Pinned as constants so a future
# rename touches one symbol per coding-standards "no inline literals".
# ---------------------------------------------------------------------------

OPENAPI_TITLE: Final[str] = "Bearings"
OPENAPI_DESCRIPTION: Final[str] = (
    "Localhost web UI that streams Claude Code agent sessions (v1 rebuild)."
)

# Route-group tag alphabet. Every router carries a ``tags=[...]`` arg
# at ``include_router`` time so the rendered OpenAPI groups operations.
ROUTE_TAG_SESSIONS: Final[str] = "sessions"
ROUTE_TAG_APPROVALS: Final[str] = "approvals"
ROUTE_TAG_MESSAGES: Final[str] = "messages"
ROUTE_TAG_TAGS: Final[str] = "tags"
ROUTE_TAG_MEMORIES: Final[str] = "memories"
ROUTE_TAG_VAULT: Final[str] = "vault"
ROUTE_TAG_CHECKLISTS: Final[str] = "checklists"
ROUTE_TAG_PAIRED_CHATS: Final[str] = "paired-chats"
ROUTE_TAG_ROUTING: Final[str] = "routing"
ROUTE_TAG_QUOTA: Final[str] = "quota"
ROUTE_TAG_USAGE: Final[str] = "usage"
ROUTE_TAG_UPLOADS: Final[str] = "uploads"
ROUTE_TAG_FS: Final[str] = "fs"
ROUTE_TAG_SHELL: Final[str] = "shell"
ROUTE_TAG_DIAG: Final[str] = "diag"
ROUTE_TAG_HEALTH: Final[str] = "health"
ROUTE_TAG_METRICS: Final[str] = "metrics"
ROUTE_TAG_COMMANDS: Final[str] = "commands"
ROUTE_TAG_HISTORY: Final[str] = "history"
ROUTE_TAG_WS_SESSIONS: Final[str] = "ws-sessions"
ROUTE_TAG_PREFERENCES: Final[str] = "preferences"
ROUTE_TAG_IMPORT: Final[str] = "import"

# History search result hard cap. The search endpoint returns at most this
# many hits (sessions + messages combined) per query to keep response sizes
# predictable.
HISTORY_SEARCH_RESULT_CAP: Final[int] = 50

# Maximum characters rendered in a history search snippet. The snippet is
# extracted from the matching field (message content or session description)
# around the first occurrence of the query term.
HISTORY_SEARCH_SNIPPET_CHARS: Final[int] = 120

# Debounce window (milliseconds) for the sidebar search input. Mirrors the
# vault-search debounce so two reactive search surfaces feel consistent.
HISTORY_SEARCH_DEBOUNCE_MS: Final[int] = 300


# Self-consistency: every profile that appears in the resolution tables
# below must also appear in :data:`PERMISSION_PROFILE_NAMES`, and every
# resolved SDK mode must be a member of :data:`KNOWN_SDK_PERMISSION_MODES`.
# Asserting at import time means a future hand-edit cannot drift one of
# the four parallel tables silently — an inconsistent mapping fails
# ``import bearings.config.constants`` itself, which the linter and the
# test runner both pick up before any downstream logic executes.
assert set(PERMISSION_PROFILE_TO_SDK_MODE) == PERMISSION_PROFILE_NAMES
assert set(PERMISSION_PROFILE_ALLOWED_TOOLS) == PERMISSION_PROFILE_NAMES
assert set(PERMISSION_PROFILE_DISALLOWED_TOOLS) == PERMISSION_PROFILE_NAMES
assert set(PERMISSION_PROFILE_TO_SDK_MODE.values()) <= KNOWN_SDK_PERMISSION_MODES
assert STREAM_HEARTBEAT_INTERVAL_S == WS_IDLE_PING_INTERVAL_S

# Vault kind alphabet must mirror schema.sql's CHECK constraint so a
# scan that produces an unsupported kind fails at the dataclass
# validator before it reaches the DB.
assert frozenset({VAULT_KIND_PLAN, VAULT_KIND_TODO}) == KNOWN_VAULT_KINDS

# FS-entry kind alphabet — every named kind appears in the
# ``KNOWN_FS_ENTRY_KINDS`` set so a stat result missing the alphabet
# fails at the dataclass validator before it leaves the agent layer.
assert (
    frozenset(
        {
            FS_ENTRY_KIND_FILE,
            FS_ENTRY_KIND_DIR,
            FS_ENTRY_KIND_SYMLINK,
            FS_ENTRY_KIND_OTHER,
        }
    )
    == KNOWN_FS_ENTRY_KINDS
)

# Health-status alphabet — every named status appears in the
# ``KNOWN_HEALTH_STATUSES`` set so the wire-shape validator can
# enforce the alphabet at the API boundary.
assert frozenset({HEALTH_STATUS_OK, HEALTH_STATUS_DEGRADED}) == KNOWN_HEALTH_STATUSES


__all__ = [
    "ADVISOR_TOOL_BETA_HEADER",
    "AUTO_DRIVER_FAILURE_POLICY_HALT",
    "AUTO_DRIVER_FAILURE_POLICY_SKIP",
    "AUTO_DRIVER_STATE_ERRORED",
    "AUTO_DRIVER_STATE_FINISHED",
    "AUTO_DRIVER_STATE_IDLE",
    "AUTO_DRIVER_STATE_PAUSED",
    "AUTO_DRIVER_STATE_RUNNING",
    "BEARINGS_MCP_SERVER_NAME",
    "BEARINGS_TODO_CHECK_DEFAULT_MAX_AGE_DAYS",
    "BEARINGS_TODO_ENTRY_HEADING_PREFIX",
    "BEARINGS_TODO_FILENAME",
    "BEARINGS_TODO_RECENT_DEFAULT_DAYS",
    "BEARINGS_TODO_WALK_MAX_DEPTH",
    "CHECKLIST_DRIVER_MAX_FOLLOWUP_DEPTH",
    "CHECKLIST_DRIVER_MAX_ITEMS_PER_RUN",
    "CHECKLIST_DRIVER_MAX_LEGS_PER_ITEM",
    "CHECKLIST_DRIVER_MAX_TURNS_PER_LEG",
    "CHECKLIST_DRIVER_PRESSURE_HANDOFF_THRESHOLD_PCT",
    "CHECKLIST_DRIVER_PRESSURE_NUDGE_TEXT",
    "CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH",
    "CHECKLIST_ITEM_LABEL_MAX_LENGTH",
    "CHECKLIST_ITEM_NOTES_MAX_LENGTH",
    "CHECKLIST_SORT_ORDER_STEP",
    "CHECKPOINT_LABEL_MAX_LENGTH",
    "CLI_EXIT_OK",
    "CLI_EXIT_OPERATION_FAILURE",
    "CLI_EXIT_USAGE_ERROR",
    "CLOSE_SESSION_TOOL_NAME",
    "DEFAULT_ADVISOR_MAX_USES_HAIKU",
    "DEFAULT_ADVISOR_MAX_USES_SONNET",
    "DEFAULT_ALLOWED_SHELL_COMMANDS",
    "DEFAULT_BILLING_MODE",
    "DEFAULT_BILLING_PLAN",
    "DEFAULT_CHECKPOINT_LABEL_TEMPLATE",
    "DEFAULT_DB_PATH",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_TEMPLATE_ADVISOR_MAX_USES",
    "DEFAULT_TEMPLATE_ADVISOR_MODEL",
    "DEFAULT_TEMPLATE_EFFORT_LEVEL",
    "DEFAULT_TEMPLATE_MODEL",
    "DEFAULT_TEMPLATE_PERMISSION_PROFILE",
    "DEFAULT_TOOL_OUTPUT_CAP_CHARS",
    "DEFAULT_UPLOADS_STORAGE_ROOT",
    "DEFAULT_VAULT_PLAN_ROOT",
    "DEFAULT_VAULT_TODO_GLOB",
    "DIAG_DRIVER_SAMPLE_LIMIT",
    "DIAG_RUNNER_SAMPLE_LIMIT",
    "DRIVER_OUTCOME_COMPLETED",
    "DRIVER_OUTCOME_HALTED_EMPTY",
    "DRIVER_OUTCOME_HALTED_FAILURE_TEMPLATE",
    "DRIVER_OUTCOME_HALTED_MAX_ITEMS",
    "DRIVER_OUTCOME_HALTED_STOPPED",
    "EFFORT_LEVEL_TO_SDK",
    "EXECUTOR_FALLBACK_MODEL",
    "EXECUTOR_MODEL_FULL_ID_PREFIX",
    "FS_ENTRY_KIND_DIR",
    "FS_ENTRY_KIND_FILE",
    "FS_ENTRY_KIND_OTHER",
    "FS_ENTRY_KIND_SYMLINK",
    "FS_LIST_MAX_ENTRIES",
    "FS_READ_MAX_BYTES",
    "HEALTH_DB_PROBE_QUERY",
    "HEALTH_STATUS_DEGRADED",
    "HEALTH_STATUS_OK",
    "HISTORY_PRIME_MAX_CHARS",
    "HISTORY_SEARCH_DEBOUNCE_MS",
    "HISTORY_SEARCH_RESULT_CAP",
    "HISTORY_SEARCH_SNIPPET_CHARS",
    "IDLE_REAP_POLL_INTERVAL_S",
    "IDLE_REAP_THRESHOLD_S",
    "ITEM_OUTCOME_BLOCKED",
    "ITEM_OUTCOME_FAILED",
    "ITEM_OUTCOME_SKIPPED",
    "KNOWN_AUTO_DRIVER_FAILURE_POLICIES",
    "KNOWN_AUTO_DRIVER_STATES",
    "KNOWN_EFFORT_LEVELS",
    "KNOWN_EXECUTOR_MODELS",
    "KNOWN_FS_ENTRY_KINDS",
    "KNOWN_HEALTH_STATUSES",
    "KNOWN_ITEM_OUTCOMES",
    "KNOWN_PAIRED_CHAT_SPAWNED_BY",
    "KNOWN_ROUTING_SOURCES",
    "KNOWN_SDK_PERMISSION_MODES",
    "KNOWN_SDK_SETTING_SOURCES",
    "KNOWN_SENTINEL_KINDS",
    "KNOWN_SESSION_KINDS",
    "KNOWN_VAULT_KINDS",
    "MAX_CHECKPOINTS_PER_SESSION",
    "MAX_UPLOAD_SIZE_BYTES",
    "MESSAGES_LIST_DEFAULT_LIMIT",
    "MESSAGES_LIST_MAX_LIMIT",
    "MESSAGE_ID_PREFIX",
    "MESSAGE_PAGE_SIZE",
    "METRICS_CONTENT_TYPE",
    "METRIC_NAME_ACTIVE_DRIVERS",
    "METRIC_NAME_ACTIVE_RUNNERS",
    "METRIC_NAME_ADVISOR_CALLS_TOTAL",
    "METRIC_NAME_INFO",
    "METRIC_NAME_QUEUED_PROMPTS",
    "METRIC_NAME_QUOTA_OVERALL",
    "METRIC_NAME_QUOTA_SONNET",
    "METRIC_NAME_ROUTING_DECISIONS_TOTAL",
    "METRIC_NAME_UPTIME_SECONDS",
    "MODEL_USAGE_KEY_CACHE_READ_TOKENS",
    "MODEL_USAGE_KEY_INPUT_TOKENS",
    "MODEL_USAGE_KEY_OUTPUT_TOKENS",
    "OPENAPI_DESCRIPTION",
    "OPENAPI_TITLE",
    "OVERRIDE_RATE_REVIEW_THRESHOLD",
    "OVERRIDE_RATE_WINDOW",
    "OVERRIDE_RATE_WINDOW_DAYS",
    "PAIRED_CHAT_SPAWNED_BY_DRIVER",
    "PAIRED_CHAT_SPAWNED_BY_USER",
    "PCT_MAX",
    "PCT_MIN",
    "PERMISSION_PROFILE_ALLOWED_TOOLS",
    "PERMISSION_PROFILE_DISALLOWED_TOOLS",
    "PERMISSION_PROFILE_NAMES",
    "PERMISSION_PROFILE_TO_SDK_MODE",
    "PRESSURE_INJECT_THRESHOLD_PCT",
    "PROMPT_ACK_QUEUED_KEY",
    "PROMPT_ACK_SESSION_ID_KEY",
    "PROMPT_CONTENT_MAX_CHARS",
    "PROMPT_RATE_LIMIT_MAX_PER_WINDOW",
    "PROMPT_RATE_LIMIT_WINDOW",
    "PROMPT_RATE_LIMIT_WINDOW_S",
    "QUOTA_BAR_RED_PCT",
    "QUOTA_BAR_YELLOW_PCT",
    "QUOTA_THRESHOLD_PCT",
    "RING_BUFFER_MAX",
    "ROUTE_TAG_APPROVALS",
    "ROUTE_TAG_CHECKLISTS",
    "ROUTE_TAG_COMMANDS",
    "ROUTE_TAG_DIAG",
    "ROUTE_TAG_FS",
    "ROUTE_TAG_HEALTH",
    "ROUTE_TAG_HISTORY",
    "ROUTE_TAG_IMPORT",
    "ROUTE_TAG_MEMORIES",
    "ROUTE_TAG_MESSAGES",
    "ROUTE_TAG_METRICS",
    "ROUTE_TAG_PAIRED_CHATS",
    "ROUTE_TAG_PREFERENCES",
    "ROUTE_TAG_QUOTA",
    "ROUTE_TAG_ROUTING",
    "ROUTE_TAG_SESSIONS",
    "ROUTE_TAG_SHELL",
    "ROUTE_TAG_TAGS",
    "ROUTE_TAG_UPLOADS",
    "ROUTE_TAG_USAGE",
    "ROUTE_TAG_VAULT",
    "ROUTE_TAG_WS_SESSIONS",
    "ROUTING_PREVIEW_DEBOUNCE",
    "ROUTING_PREVIEW_DEBOUNCE_MS",
    "SENTINEL_KIND_FOLLOWUP_BLOCKING",
    "SENTINEL_KIND_FOLLOWUP_NONBLOCKING",
    "SENTINEL_KIND_HANDOFF",
    "SENTINEL_KIND_ITEM_BLOCKED",
    "SENTINEL_KIND_ITEM_DONE",
    "SENTINEL_KIND_ITEM_FAILED",
    "SESSION_CLOSING_SUMMARY_MAX_LENGTH",
    "SESSION_CLOSING_SUMMARY_MIN_LENGTH",
    "SESSION_DESCRIPTION_MAX_LENGTH",
    "SESSION_ID_PREFIX",
    "SESSION_KIND_CHAT",
    "SESSION_KIND_CHECKLIST",
    "SESSION_TITLE_MAX_LENGTH",
    "SHELL_ARGV_ENTRY_MAX_LENGTH",
    "SHELL_ARGV_MAX_ENTRIES",
    "SHELL_EXEC_TIMEOUT_S",
    "SHELL_OUTPUT_MAX_BYTES",
    "STREAM_HEARTBEAT_INTERVAL_S",
    "STREAM_MAX_DELTA_CHARS",
    "STREAM_MAX_TOOL_OUTPUT_CHARS",
    "STREAM_TRUNCATION_MARKER_TEMPLATE",
    "TAG_COLOR_MAX_LENGTH",
    "TAG_GROUP_SEPARATOR",
    "TAG_MEMORY_BODY_MAX_LENGTH",
    "TAG_MEMORY_TITLE_MAX_LENGTH",
    "TAG_NAME_MAX_LENGTH",
    "TCP_PORT_MAX",
    "TCP_PORT_MIN",
    "TEMPLATE_DESCRIPTION_MAX_LENGTH",
    "TEMPLATE_NAME_MAX_LENGTH",
    "TOOL_PROGRESS_INTERVAL",
    "TOOL_PROGRESS_INTERVAL_S",
    "UPLOADS_LIST_DEFAULT_LIMIT",
    "UPLOADS_LIST_MAX_LIMIT",
    "UPLOADS_SHA256_SHARD_CHARS",
    "UPLOAD_DEFAULT_MIME_TYPE",
    "UPLOAD_FILENAME_MAX_LENGTH",
    "UPLOAD_ID_PREFIX",
    "UPLOAD_MIME_TYPE_MAX_LENGTH",
    "UPLOAD_STREAM_CHUNK_BYTES",
    "USAGE_HEADROOM_WINDOW",
    "USAGE_HEADROOM_WINDOW_DAYS",
    "USAGE_POLL_INTERVAL",
    "USAGE_POLL_INTERVAL_S",
    "VAULT_BODY_MAX_CHARS",
    "VAULT_BODY_TRUNCATION_MARKER_TEMPLATE",
    "VAULT_KIND_PLAN",
    "VAULT_KIND_TODO",
    "VAULT_REDACTION_KEYWORDS",
    "VAULT_REDACTION_MASK_GLYPH",
    "VAULT_REDACTION_MIN_VALUE_CHARS",
    "VAULT_SEARCH_MAX_LINES_PER_DOC",
    "VAULT_SEARCH_RESULT_CAP",
    "VAULT_SEARCH_SNIPPET_MAX_CHARS",
    "WS_IDLE_PING_INTERVAL",
    "WS_IDLE_PING_INTERVAL_S",
]
