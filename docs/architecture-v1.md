# Bearings v1 — Architecture & SDK Currency Audit

**Status:** authored 2026-04-28 as item 0.2 of the v1 rebuild.
**Audience:** every executor on items 1.1–3.4. After Phase 0 closes, this
file (plus `docs/behavior/<subsystem>.md`) is the only authoritative
source on shape and decision rationale; v0.17.x source becomes
off-limits.
**Source spec:** `docs/model-routing-v1-spec.md` (governs routing
files); `~/.claude/coding-standards.md` (governs every line).
**Reference reads:** all v0.17.x file paths cited below were read in the
authoring of this doc; later items must NOT re-open them.

This doc fixes the shape. It does not contain code. Where a name has a
specific signature, it appears in §4. Where a name has a specific
container, it appears in §1 or §2. Where a divergence from v0.17.x is
non-obvious, the divergence carries its own rationale at the point of
divergence; §6 collects the omissions and the divergences-of-omission
that don't fit elsewhere.

The bar this doc must meet: a downstream executor on items 1.1–2.10
must be able to produce their item from this doc + the per-subsystem
behavioral spec, with v0.17.x source off-limits, without verbal
hand-waving. Anywhere this doc is silent on a decision and the executor
has to invent shape, that is an architecture-doc gap. Three of those in
a row halts the rebuild for amendment.

---

## Contents

1. Module decomposition
2. Class boundaries
3. Import graph
4. Key interfaces
5. SDK currency audit
6. Divergences from v0.17.x — appendix

---

## 1. Module decomposition

### 1.1 Backend top-level packages under `src/bearings/`

The rebuild collapses v0.17.x's two parallel mixin sprawls
(`agent/session/` and `agent/auto_driver/`) and its god-store
re-export wall into single-responsibility packages with one canonical
class per concern. The package count grows from 6 (v0.17.x:
`agent/`, `api/`, `bearings_dir/`, `db/`, `todo/`, plus loose
`cli.py`/`server.py`/`profiles.py`/`config.py`/`metrics.py`/`menus.py`/`uploads_gc.py`)
to 8 (`cli/`, `config/`, `db/`, `agent/`, `web/`, `bearings_dir/`,
`metrics/`, `migrations/`). Every loose top-level module from v0.17.x
either becomes a package or moves under one of the eight.

#### 1.1.1 `bearings.cli` — entrypoint surface

**Responsibility:** every Typer-style subcommand the user invokes from a
shell. Replaces v0.17.x's flat `cli.py` (524 lines) plus `__main__.py`
plus the orphaned `uploads_gc.py` (which only the CLI calls) plus the
`todo/` package (which only the CLI exposes).

**Public interface:** the `bearings` console-script entrypoint declared
in `pyproject.toml` resolves to `bearings.cli.app`.

| Module | Subcommand surface |
|---|---|
| `cli/app.py` | Root Typer app + global options. ≤80 lines. |
| `cli/serve.py` | `bearings serve` — starts the FastAPI app. |
| `cli/init.py` | `bearings init` — first-run profile wizard, writes `config.toml`. |
| `cli/gc.py` | `bearings gc uploads` — prunes `~/.local/share/bearings-v1/uploads/`. |
| `cli/todo.py` | `bearings todo` — `add`/`open`/`recent`/`lint`/`parse`. Per spec for item 1.7. |
| `cli/migrate.py` | `bearings migrate` — invokes `migrations/v0_17_to_v0_18.py`. |

**In:** parsing CLI flags, dispatching to a single domain function per
subcommand, formatting human-readable output. **Out:** any business
logic — every subcommand's body is a thin call into `agent`/`db`/`web`
helpers, exactly the *handlers stay thin* directive from coding-standards
§Code Quality.

**Diff vs v0.17.x:** v0.17.x scattered CLI work across `cli.py`,
`__main__.py`, `todo/` (5 modules), and `uploads_gc.py` because each
arrived in a different feature wave. The rebuild groups by
*entrypoint*, not by *feature wave* — `bearings todo add` lives next
to `bearings serve` because the user types both into the same shell.
The `todo/` parsing logic itself moves to a leaf helper module
under `cli/todo.py`'s implementation; it is not separately importable
from the rest of the codebase (no other caller had it).

#### 1.1.2 `bearings.config` — configuration + named constants

**Responsibility:** every value the rebuild reads at runtime that isn't
a function argument. Two sub-modules so that the type-hint container
(pydantic models) stays separate from the spec-numeric source of truth
(named constants). Spec §11 build-step #5 plus item 0.5's
"no inline literals downstream" gate live here.

| Module | What's in |
|---|---|
| `config/settings.py` | `Settings` root model + `ServerCfg` / `AuthCfg` / `AgentCfg` / `RoutingCfg` / `QuotaCfg` / `StorageCfg` / `MetricsCfg` / `RunnerCfg` / `UploadsCfg` / `ArtifactsCfg` / `FsCfg` / `ShellCfg` / `CommandsCfg` / `VaultCfg` / `ProfileCfg` / `BillingCfg`. TOML loading via `pydantic-settings`. ≤350 lines. |
| `config/constants.py` | Every spec numeric default as a `Final[...]` named constant: `QUOTA_THRESHOLD_PCT = 0.80`, `OVERRIDE_RATE_REVIEW_THRESHOLD = 0.30`, `USAGE_POLL_INTERVAL_S = 300`, `OVERRIDE_RATE_WINDOW_DAYS = 14`, `RING_BUFFER_MAX = 5000`, `TOOL_PROGRESS_INTERVAL_S = 2.0`, `WS_IDLE_PING_INTERVAL_S = 15.0`, `HISTORY_PRIME_MAX_CHARS = 60_000`, `PRESSURE_INJECT_THRESHOLD_PCT = 70.0`, `DEFAULT_TOOL_OUTPUT_CAP_CHARS = 8000`, plus the spec §3 priority ladder values. ≤200 lines. |
| `config/profiles.py` | Profile presets (`safe`/`workstation`/`power-user`); each is a function returning a frozen `Settings` overlay. Selectable at `bearings init`. |

**Diff vs v0.17.x:** v0.17.x has a single `config.py` (511 lines) with
inline literals ("80 chars", "5000 entries") scattered as defaults
inside Pydantic field definitions. The audit on item 0.5 fails any
inline literal seen in subsequent items, which is unenforceable when
the source-of-truth is mixed with the type definitions. Splitting them
makes the audit a grep: any numeric Final outside `config/constants.py`
is a violation.

#### 1.1.3 `bearings.db` — schema + per-concern queries

**Responsibility:** the SQLite schema and every query that touches it.
One module per resource group; **no god `store.py`**.

| Module | Tables / queries |
|---|---|
| `db/schema.sql` | Single canonical DDL file. Read once by `connect.py:init_db`. Replaces v0.17.x's drift-prone migration directory. (Migration script for the v0.17.x→v0.18.0 cutover lives in `migrations/`, not here.) |
| `db/connect.py` | `async def init_db(path) -> aiosqlite.Connection`. Idempotent first-run apply of `schema.sql`. Seeds spec §3 default system rules (idempotent on `seeded = 1`). |
| `db/sessions.py` | `sessions` table queries. CRUD + state transitions + token-totals readout. |
| `db/messages.py` | `messages` table queries — including the spec §5 routing/usage columns added day 1 (no ALTER chain). Tool-call rows live here too (one-to-many on `messages.id`). |
| `db/tags.py` | `tags` + the per-session join (`session_tags`). The `tags.class` column (`'project'` / `'severity'` / `'general'`) partitions the tag set for the three-section sidebar filter; `tags.sort_order` is per-class display order. Severity-class tags reject `default_model` / `working_dir` at the dataclass boundary. The slash-namespace `<group>/<name>` convention is retained for one release for back-compat — new categorisation goes through `class`. |
| `db/memories.py` | `tag_memories` table. Pulled out of v0.17.x's `_tags.py` so the boundary between "tags as labels" and "tag memories as system-prompt fragments" is visible. |
| `db/checklists.py` | `checklist_items` + `checklist_paired_chats`. |
| `db/checkpoints.py` | `checkpoints` table — Bearings' own snapshot/restore feature, distinct from the SDK's `enable_file_checkpointing` (see §5). |
| `db/templates.py` | `templates` table. |
| `db/vault.py` | Read-only filesystem index for `~/.claude/plans/` + `TODO.md` globs (no schema; the cache table that v0.17.x doesn't have stays optional). |
| `db/routing.py` | `tag_routing_rules`, `system_routing_rules`, `quota_snapshots`. **NEW.** Spec §3 + §4. |
| `db/audits.py` | `reorg_audits`, `auto_run_state`. |
| `db/artifacts.py` | `agent_artifacts` + `uploads` indexes. |
| `db/preferences.py` | `preferences` key-value table. |
| `db/_id.py` | Module-private helpers (`_new_id`, `_now`, `_date_filter`). The leading underscore is the import-rule signal: cross-package imports of `_id` are a lint violation. |

**Public interface:** every consumer imports the *concern module*, not
a re-export wall: `from bearings.db import sessions; await
sessions.create(conn, ...)`. There is no `bearings.db.store`. There is
no `__all__` re-export wall. Each concern module owns its own functions
and its own `__all__`.

**Diff vs v0.17.x:** v0.17.x has `db/store.py` (223 lines, almost all
re-exports of the 12 sibling `_*.py` modules) plus `_common.py` for
shared helpers. The store-as-facade pattern claims to "let callers keep
using `from bearings.db import store`" but the cost is real: every new
function has to be added in two places, and the re-export wall hides
which concern owns a name. Removing it is one less indirection per
import; the only callers that benefit from the facade are tests
that monkeypatch a name into `store`, and those rewrite as
`monkeypatch.setattr(sessions, "create", ...)`.

#### 1.1.4 `bearings.agent` — domain layer

**Responsibility:** everything between the Claude Agent SDK and the
DB. Per-session SDK lifecycle, prompt assembly, event translation,
runner fleet, autonomous checklist driver, routing evaluation, quota
guard, telemetry aggregation, in-process MCP server.

The single biggest decomposition move in the rebuild: v0.17.x's
`agent/session/` (7-mixin god class for `AgentSession`) and
`agent/auto_driver/` (3-mixin god class for `Driver`, plus a parallel
`auto_driver_runtime.py` that names the same thing differently)
collapse into one canonical file per class. The §FileSize cap (≤400
lines/file from coding-standards §Code Quality) is preserved by *real*
extraction — pure-function helpers move to clearly-named neighbor
modules, not mixin shells.

| Module | Responsibility |
|---|---|
| `agent/session.py` | `AgentSession` class (canonical, single file). Per-WS-session SDK wrapper. Owns `stream(prompt) -> AsyncIterator[AgentEvent]`. Constructor takes a `SessionConfig` dataclass (one arg) instead of v0.17.x's 14-positional-arg constructor. ≤350 lines. |
| `agent/options.py` | Pure function `build_options(session, prompt, decision) -> tuple[ClaudeAgentOptions, str, asyncio.Queue, asyncio.Queue]`. Receives the `RoutingDecision` so beta headers, `fallback_model`, `effort`, and the advisor wiring all attach in one place. ≤250 lines. |
| `agent/translate.py` | SDK→wire translators: `translate_stream_event(dict) -> AgentEvent | None`, `translate_block(block) -> AgentEvent | None`, `tool_call_end(block) -> ToolCallEnd`. Pure functions, no `self`. ≤250 lines. |
| `agent/events.py` | Pydantic discriminated union `AgentEvent` + every event class. Includes new `RoutingBadge` field on `MessageComplete` per spec §5. ≤300 lines. |
| `agent/prompt.py` | Layered prompt assembler (`assemble_prompt(conn, session_id) -> AssembledPrompt`). v0.17.x's shape is sound; rebuild keeps it with two changes: pure-fn type hints, and `directory_bearings` / `directory_onboarding` layers split into `bearings_dir/onboarding.py` callbacks instead of fetching the layer content from inside `prompt.py`. ≤400 lines. |
| `agent/hooks.py` | `build_post_tool_use_hook(...)`, `build_precompact_hook(...)`. Two factory functions, returns hook callables. v0.17.x has these as `_hooks_mixin.py` methods; here they are free functions whose closures capture only what the SDK hook callback signature needs. ≤200 lines. |
| `agent/history.py` | `build_history_prefix(session, prompt)`, `build_context_pressure_block(session)`. Pure functions reading the DB. v0.17.x's `_history_mixin.py` becomes this. ≤200 lines. |
| `agent/runner.py` | `SessionRunner` class. Worker loop, prompt queue, ring buffer, subscriber set, idle-reap signal. Inherits the fact that it must NOT import from `web/`. ≤450 lines (this is the one file allowed to exceed the §400 cap; size justification documented inline at the top). |
| `agent/turn_executor.py` | `execute_turn(runner, prompt, attachments)`. The per-turn driver: assemble options, call `session.stream`, fan events out, persist final message + tool calls + per-message routing/usage. Lives outside `runner.py` so the runner stays readable. ≤350 lines. |
| `agent/persistence.py` | Pure-IO assistant-turn persistence. `persist_assistant_turn(conn, message_id, blocks, model_usage, decision)`. Reads `ResultMessage.model_usage` and writes the spec §5 columns. v0.17.x has split persistence between `persist.py` and `turn_executor.py`; consolidate. ≤250 lines. |
| `agent/registry.py` | `RunnerRegistry` class. Fleet ownership + reaper. ≤200 lines. |
| `agent/approval.py` | `ApprovalBroker` class. Future-map for `can_use_tool` callbacks. Renamed from `approval_broker.py`; the `_broker` suffix was redundant when the module sits under `agent/`. ≤250 lines. |
| `agent/sessions_broker.py` | `SessionsBroker` class. Sidebar-list pubsub. **Lifts `SessionOut`-shaped dict construction up out of v0.17.x's lazy `from bearings.api.models import SessionOut` import** (cycle break — see §3). |
| `agent/auto_driver.py` | `Driver` class (canonical, single file). Outer loop + per-item dispatch + persistence + per-leg sessions, all method-direct (no mixin sprawl). ≤400 lines. The five v0.17.x modules (`driver.py` + `dispatch.py` + `persistence.py` + `sessions.py` + `contracts.py`) collapse here; only `contracts.py`'s dataclasses (`DriverConfig`, `DriverOutcome`, `DriverResult`, `DriverRuntime` Protocol) move to `agent/auto_driver_types.py`. |
| `agent/auto_driver_types.py` | Frozen dataclasses + the `DriverRuntime` Protocol. Imported by `auto_driver.py` and by the binding-runtime module. ≤150 lines. |
| `agent/auto_driver_runtime.py` | `AgentRunnerDriverRuntime` class (concrete `DriverRuntime` impl) + `AutoDriverRegistry` class. Takes a `RunnerFactory` Protocol injected at construction, **no `from bearings.web.*` imports**. ≤350 lines. |
| `agent/sentinel.py` | Checklist-sentinel parser (renamed from `checklist_sentinels.py`). Pure parsers — given an assistant message body, return a list of structured findings. ≤350 lines. |
| `agent/routing.py` | Pure function `evaluate(message, tags_with_rules, system_rules, quota_state) -> RoutingDecision`. **NEW.** Spec Appendix A. ≤300 lines. |
| `agent/quota.py` | `QuotaPoller` class (5-minute background task) + pure `apply_quota_guard(decision, snapshot) -> RoutingDecision`. **NEW.** ≤300 lines. |
| `agent/override_aggregator.py` | `OverrideAggregator` class (rolling 14-day per-rule). **NEW.** ≤250 lines. |
| `agent/event_fanout.py` | `emit_event(runner, event)` + `emit_ephemeral(runner, event)` helpers. Kept from v0.17.x; no behavior change. |
| `agent/progress_ticker.py` | `ProgressTickerManager` class. Per-tool-call keepalive ticks. Kept. |
| `agent/tool_output_coalescer.py` | `ToolOutputCoalescer` class. Kept. |
| `agent/tool_deny_callback.py` | Cross-runner BLOCKED-callback synthesizer. Kept; the lazy `from bearings.api.ws_agent import build_runner` becomes `from bearings.web.runner_factory import RunnerFactory` at the type-hint level only — actual factory is injected by `web/`. |
| `agent/line_buffer.py` | `LineBuffer`. Kept. |
| `agent/artifacts.py` | Agent-authored-file register helpers (renamed from v0.17.x's `_artifacts.py`). Kept. |
| `agent/attachments.py` | Composer-attachment translator (renamed from v0.17.x's `_attachments.py`). Kept. |
| `agent/mcp/server.py` | `build_bearings_mcp_server(...) -> McpSdkServerConfig`. Factory. ≤150 lines. |
| `agent/mcp/get_tool_output.py` | `bearings__get_tool_output` tool body. ≤150 lines. |
| `agent/mcp/streaming_bash.py` | `bearings__bash` tool + line-buffered subprocess pump (consolidates v0.17.x's `bash_tool.py`). ≤350 lines. |
| `agent/mcp/dir_init.py` | `bearings__dir_init` tool body. ≤150 lines. |
| `agent/researcher_prompt.py` | The `researcher` subagent's system-prompt string (`Final[str]`). Kept. |
| `agent/base_prompt.py` | The base layer's prompt string (`Final[str]`). Kept. |

**In each module:** one canonical class or one canonical pure
function (or one closely-related pair, like `evaluate` +
`apply_quota_guard`). **Out of every module:** mixins, `_*_mixin.py`
filenames, MRO-ordering comments, type-only abstract stubs that exist
only to satisfy mypy when sibling mixins call `self.X`. The §FileSize
cap is met by extracting *whole concerns* (history-prime → its own
module; option-build → its own module), never by mixin-splitting one
class.

#### 1.1.5 `bearings.web` — HTTP/WS surface

**Responsibility:** FastAPI app construction, every route group, every
WebSocket handler, the static-bundle mount.

The package is renamed from v0.17.x's `api/` so the import-graph layer
rule reads naturally (see §3): `web` imports `agent` imports `db`.
"`api`" was an awkward name because in v0.17.x, `agent/`
(domain) imports from `api/middleware` were a layer-violation smell;
"web" makes the boundary visible by convention (web → domain → storage).

| Module | What's in |
|---|---|
| `web/app.py` | `create_app(settings) -> FastAPI`. Lifespan, `app.state` wiring (DB, runners registry, sessions broker, auto-driver registry, runner factory, quota poller, override aggregator). ≤200 lines. |
| `web/runner_factory.py` | `build_runner(app, session_id) -> SessionRunner`. **Lifted out of v0.17.x's `api/ws_agent.py`** so the `agent` layer can take it as a `RunnerFactory: Protocol` argument without a lazy import. The factory is FastAPI-aware (reads `app.state`); the `RunnerFactory` Protocol is FastAPI-ignorant. |
| `web/middleware.py` | Security headers, global exception handler, CSP provider. Kept; the CSP-provider callable stays here. ≤300 lines. |
| `web/auth.py` | `check_auth`, `check_ws_auth`, `check_ws_origin`, `ws_accept_subprotocol`. ≤200 lines. |
| `web/static.py` | `_BundleStaticFiles` + SPA fallback heuristic. **Lifted out of v0.17.x's `server.py`** — currently 200 lines of bundle-cache logic embedded in app construction; lives on its own here. ≤200 lines. |
| `web/routes/__init__.py` | Re-exports the router list `web/app.py` registers. |
| `web/routes/sessions.py` | `GET/POST/PATCH/DELETE /api/sessions[/{id}]`, `POST /api/sessions/{id}/prompt`, `POST /api/sessions/{id}/regenerate`, `PATCH /api/sessions/{id}/model` (NEW — calls `runner.set_model()` for the spec §7 mid-session swap; see §5 SDK shifts). |
| `web/routes/sessions_bulk.py` | Bulk close/reopen/delete/tag. |
| `web/routes/messages.py` | Message read + edit + history. |
| `web/routes/tags.py` | Tag CRUD + assignment. |
| `web/routes/memories.py` | Tag-memory CRUD. (v0.17.x folds into `routes_tags.py`.) |
| `web/routes/checklists.py` | Checklist CRUD + `POST /checklist/run` (auto-driver entrypoint). |
| `web/routes/checkpoints.py` | Bearings checkpoint create/restore/list/delete. |
| `web/routes/templates.py` | Templates CRUD. |
| `web/routes/vault.py` | Read-only markdown surface. |
| `web/routes/regenerate.py` | Regenerate-from-message endpoint. |
| `web/routes/reorg.py` | Session-reorg analyze + apply. |
| `web/routes/spawn_from_reply.py` | Spawn paired chat from a reply. |
| `web/routes/reply_actions.py` | Inline reply-action execution. |
| `web/routes/uploads.py` | File upload + index. |
| `web/routes/artifacts.py` | Artifact register + serve (split into `session_router` + `serve_router` per v0.17.x). |
| `web/routes/fs.py` | FS-picker walk under `fs.allow_root`. |
| `web/routes/shell.py` | `/api/shell/open` argv dispatch. |
| `web/routes/commands.py` | Slash-command palette scan. |
| `web/routes/preferences.py` | Per-user preferences (theme, density, etc.). |
| `web/routes/pending.py` | `.bearings/pending.toml` operations. |
| `web/routes/diag.py` | Diagnostic introspection. |
| `web/routes/health.py` | `/api/health` liveness. |
| `web/routes/metrics.py` | Prometheus scrape. |
| `web/routes/history.py` | `history.jsonl` reader. |
| `web/routes/config.py` | `/api/ui-config` runtime knob exposure. |
| `web/routes/routing.py` | **NEW.** Spec §9 — tag rules CRUD + reorder, system rules CRUD, `/api/routing/preview`. |
| `web/routes/quota.py` | **NEW.** Spec §9 — `/api/quota/current`, `/refresh`, `/history`. |
| `web/routes/usage.py` | **NEW.** Spec §9 — `/api/usage/by_model`, `/by_tag`, `/override_rates`. |
| `web/ws/agent.py` | Per-session agent WS. |
| `web/ws/sessions.py` | Sidebar-list pubsub WS. |
| `web/models/sessions.py` | Pydantic shapes for `routes/sessions.py`. |
| `web/models/messages.py` | … and so on, one models module per route module. |
| `web/models/routing.py` | **NEW.** Request/response DTOs for routing/quota/usage routes. |

**In each `routes/` module:** thin handler bodies — argument parsing,
permission check, single domain call, response formatting. **Out of
every `routes/` module:** business logic. The handler-stays-thin
directive from coding-standards §Code Quality is enforced by the
auditor: every route function ≤40 lines, and any helper that grew up
inside a route module gets moved into `agent/`.

**Diff vs v0.17.x:** v0.17.x's `api/` has 30 `routes_*.py` modules
hanging off the package root + a `models/` subpackage. The rebuild
uses `web/routes/` and `web/ws/` subpackages so the package root has
~6 files (`app.py`, `runner_factory.py`, `middleware.py`, `auth.py`,
`static.py`, `__init__.py`); deeper modules are reachable via
`from bearings.web.routes import sessions; ...router`.

#### 1.1.6 `bearings.bearings_dir` — directory-context contract

**Responsibility:** the on-disk `.bearings/` directory schema and its
read/write/lifecycle. v0.17.x has 10 modules here; many are <60 lines
and the package surface is opaque. Consolidate to four:

| Module | Responsibility |
|---|---|
| `bearings_dir/contract.py` | `manifest.toml` / `state.toml` / `pending.toml` schema. Pydantic models, version-schema-version constants, validation helpers. (Renamed from `schema.py`.) |
| `bearings_dir/io.py` | Atomic read/write helpers; tempfile-and-rename. |
| `bearings_dir/lifecycle.py` | `note_directory_context_start`, `history.jsonl` append/cap, stale-state revalidation. |
| `bearings_dir/onboarding.py` | First-time onboarding ritual + brief composition + `bearings__dir_init` tool body. (Consolidates v0.17.x's `auto_onboard.py` + `brief.py` + `onboard.py` + `on_open.py` + `init_dir.py` + `check.py`.) |
| `bearings_dir/pending.py` | Pending-ops backing for the route. |

**In:** the on-disk contract for `~/Projects/<X>/.bearings/`.
**Out:** the system-prompt layer wiring (lives in `agent/prompt.py`,
which calls `bearings_dir.lifecycle.read_brief(...)` per turn).

#### 1.1.7 `bearings.metrics` — Prometheus + telemetry

**Responsibility:** instrumentation. Lifted from v0.17.x's flat
`metrics.py` (40 lines) to a package so spec §8 telemetry counters
(advisor calls, override events, quota-downgrade events) have a place
to grow without bloating one file.

| Module | Counters/gauges |
|---|---|
| `metrics/instruments.py` | Prometheus `Counter` / `Gauge` declarations. |
| `metrics/__init__.py` | Re-exports for ergonomic `from bearings.metrics import *_total`. |

#### 1.1.8 `bearings.migrations` — one-shot cutover scripts

**Responsibility:** scripts that run *outside* the running app —
specifically `migrate_v0_17_to_v0_18.py` per item 3.2.

Not a Python package the runtime imports; lives under `migrations/`
sibling to `src/`. Item 3.2's executor lays this down.

### 1.2 Frontend top-level packages under `frontend/src/lib/`

The rebuild keeps SvelteKit + Tailwind + shiki + marked, the Svelte 5
runes store pattern, and the API-typed-client convention. The
restructure is in `components/` (currently 60+ files at one level
with mixed feature scope) and the addition of routing/quota/usage
component groups per spec §6 + §10.

| Group | Responsibility |
|---|---|
| `lib/api/` | Typed fetch clients, one file per backend route group. Adds: `routing.ts`, `quota.ts`, `usage.ts`. |
| `lib/agent.svelte.ts` | Agent-WS client + reducer entrypoint. Replays `since_seq` cursor. |
| `lib/stores/` | Svelte 5 runes stores. Adds: `routing.svelte.ts`, `quota.svelte.ts`, `usage.svelte.ts`, `override_rates.svelte.ts`. v0.17.x's `stores/conversation/reducer.ts` subdir collapses into a single `stores/conversation.svelte.ts` (the reducer is one logical thing; one file). |
| `lib/components/conversation/` | `Conversation.svelte`, `ConversationHeader.svelte` (incl. quota bars per spec §10), `ConversationComposer.svelte`, `MessageTurn.svelte`, `CheckpointGutter.svelte`, `LiveTodos.svelte`, `RoutingBadge.svelte` (NEW per spec §5). |
| `lib/components/sidebar/` | `SessionList.svelte` + items + closed-group + header + `SidebarSearch.svelte` + `BulkActionBar.svelte` + `sessionListHelpers.ts`. |
| `lib/components/inspector/` | `Inspector.svelte` shell + `ContextMeter.svelte` + `TokenMeter.svelte` + `InspectorAgent.svelte` + `InspectorContext.svelte` + `InspectorInstructions.svelte` + `InspectorRouting.svelte` (NEW) + `InspectorUsage.svelte` (NEW). |
| `lib/components/settings/` | Kept from v0.17.x (`settings/` + `settings/sections/`). |
| `lib/components/checklist/` | `ChecklistView.svelte` + `ChecklistChat.svelte`. |
| `lib/components/routing/` | **NEW.** `RoutingPreview.svelte`, `QuotaBars.svelte`, `RecostDialog.svelte`, `RoutingRuleEditor.svelte`, `RuleRow.svelte`, `TestAgainstMessageDialog.svelte`. Per spec §6, §7, §10. |
| `lib/components/vault/` | Vault panel + memories editor. |
| `lib/components/reorg/` | `ReorgPicker.svelte`, `ReorgProposalEditor.svelte`, `ReorgAuditDivider.svelte`, `ReorgUndoToast.svelte`. |
| `lib/components/menus/` | `CommandMenu.svelte`, `CheatSheet.svelte`, `FolderPicker.svelte`, `TemplatePicker.svelte`, `SessionPickerModal.svelte`, `TagFilterPanel.svelte`, `TagEdit.svelte`. |
| `lib/components/icons/` | Kept. |
| `lib/components/modals/` | `ApprovalModal.svelte`, `AskUserQuestionModal.svelte`, `NewSessionForm.svelte`, `SessionEdit.svelte`, `PermissionModeSelector.svelte`, `ModelSelect.svelte`. |
| `lib/components/feedback/` | `FeedbackButton.svelte`, `BackendStatusBanner.svelte`, `StopUndoInline.svelte`, `AuthGate.svelte`. |
| `lib/components/common/` | `CollapsibleBody.svelte`, `DataView.svelte`, `DataViewHarness.svelte`, `VirtualItem.svelte`, `VirtualItemHarness.svelte`. |
| `lib/components/pending/` | `PendingOpRow.svelte`, `PendingOpsBadge.svelte`, `PendingOpsCard.svelte`. Kept. |
| `lib/context-menu/` | Kept (already coherent: `palette` + `registry` + `actions/` + `positioning` + `keyboard` + `stub`/`undo` toasts). |
| `lib/keyboard/` | Kept. |
| `lib/actions/` | Svelte actions. Kept. |
| `lib/themes/` | Kept. |
| `lib/utils/` | Pure helpers. Kept. |
| `lib/render.ts`, `lib/turns.ts`, `lib/linkify.ts`, `lib/models.ts`, `lib/attachments.ts`, `lib/input-history.ts` | Leaf utility modules. Kept. |
| `routes/` | SvelteKit route tree under `frontend/src/routes/`. Kept. |

**Diff vs v0.17.x:** v0.17.x has 60+ files directly inside
`components/` plus four small subdirs (`settings/`, `context-menu/`,
`pending/`, `icons/`). The rebuild groups by feature surface (per
spec §10's UI map) so a frontend executor on 2.4 (new-session dialog)
opens `components/routing/` + `components/modals/NewSessionForm.svelte`,
not "scroll the flat folder until the right name appears."

---

## 2. Class boundaries

Each canonical class lives in one file, with one responsibility,
expressible in a single sentence. Where v0.17.x has a god-class with
mixin-shaped subdivisions, the rebuild names the consolidation
explicitly. Where v0.17.x's split was load-bearing (different lifecycle,
different DI surface), the rebuild keeps it.

### 2.1 Backend canonical classes

| Class | Module | Responsibility |
|---|---|---|
| `Settings` | `config/settings.py` | Root pydantic model; loads from TOML at the XDG path; parses env-var prefix `BEARINGS_`. |
| `RoutingDecision` (frozen dataclass) | `agent/routing.py` | Spec Appendix A. Immutable result of evaluate(). |
| `RoutingRule` / `SystemRoutingRule` (frozen dataclasses) | `db/routing.py` | DB-row mirrors. |
| `QuotaSnapshot` (frozen dataclass) | `agent/quota.py` | `quota_snapshots` row mirror. |
| `QuotaPoller` | `agent/quota.py` | Owns the 5-minute background task; exposes `latest_snapshot` getter; cooperates with `app.state.shutdown`. |
| `OverrideAggregator` | `agent/override_aggregator.py` | Rolling 14-day per-rule override-rate computation. Cached snapshot read by `routes/usage.py`. |
| `AgentSession` | `agent/session.py` | Wraps a single Claude turn end-to-end. **Single class, no mixins.** Constructor takes a `SessionConfig`. Owns `stream(prompt) -> AsyncIterator[AgentEvent]`, `interrupt()`, `set_permission_mode()`, `set_model()`. |
| `SessionConfig` (frozen dataclass) | `agent/session.py` | Replaces v0.17.x's 14-positional-arg `AgentSession.__init__`. Fields: `session_id`, `working_dir`, `model`, `decision: RoutingDecision`, `db: aiosqlite.Connection | None`, `sdk_session_id: str | None`, `permission_mode`, `thinking`, `setting_sources`, `inherit_mcp_servers`, `inherit_hooks`, `tool_output_cap_chars`, `enable_bearings_mcp`, `enable_precompact_steering`, `enable_researcher_subagent`, `max_budget_usd`. |
| `SessionRunner` | `agent/runner.py` | Owns one session's worker task, prompt queue, ring buffer, subscriber set, idle-reap signal. Long-lived; survives WS disconnect. |
| `RunnerRegistry` | `agent/registry.py` | App-scoped fleet keyed by session id. Owns idle reaper. Construction via DI: takes a `RunnerFactory` Protocol so it never imports `web/`. |
| `ApprovalBroker` | `agent/approval.py` | Future-map for `can_use_tool`. Resolves on user click, runner shutdown, or `request_stop`. |
| `Driver` | `agent/auto_driver.py` | Autonomous checklist driver. **Single class, no mixins.** Per-instance state (`_stop`, `_items_completed`, …) + private methods (`_save_snapshot`, `_drive_item`, `_spawn_leg`, `_run_turn_for_item`). Outer loop in `drive()`. ≤400 lines. |
| `DriverRuntime` (Protocol) | `agent/auto_driver_types.py` | `spawn_leg`, `run_turn`, `teardown_leg`, `last_context_percentage`. |
| `AgentRunnerDriverRuntime` | `agent/auto_driver_runtime.py` | Concrete `DriverRuntime` binding. Takes a `RunnerFactory` injected at construction. |
| `AutoDriverRegistry` | `agent/auto_driver_runtime.py` | Live-driver fleet. Boot-time `rehydrate(app)`. |
| `SessionsBroker` | `agent/sessions_broker.py` | Sidebar-list pubsub. Emits structured dicts (no v0.17.x `SessionOut` lazy import). |
| `ProgressTickerManager` | `agent/progress_ticker.py` | Per-tool-call keepalive. |
| `ToolOutputCoalescer` | `agent/tool_output_coalescer.py` | Per-tool-call delta merging. |
| `LineBuffer` | `agent/line_buffer.py` | UTF-8-safe / ANSI-safe line splitter for streamed bash. |
| `BearingsMcpServer` (factory function, not a class) | `agent/mcp/server.py` | Returns `McpSdkServerConfig`. The "server" is data; per-tool bodies are functions. |
| `RunnerFactory` (Protocol) | `agent/runner.py` | `(session_id: str) -> Awaitable[SessionRunner]`. The class lives in `agent/`; the binding lives in `web/runner_factory.py`. |
| `MessagePersistence` (Protocol) | `agent/persistence.py` | Pure-IO interface so unit tests of `turn_executor.execute_turn` can pass an in-memory fake. |

### 2.2 Frontend canonical "classes" (Svelte 5 stores)

Svelte 5 with runes uses module-level `$state`/`$derived` proxies, not
true classes. The rebuild names each store object the same way it
names a class — one canonical store per concern, one file:

- `agent.svelte.ts` — agent-WS client + per-session conversation
  reducer entrypoint.
- `stores/sessions.svelte.ts` — sidebar list state + `softRefresh`
  poll + `/ws/sessions` subscription.
- `stores/tags.svelte.ts` — tag list + active filter.
- `stores/conversation.svelte.ts` — per-active-session events +
  reducer (single file; v0.17.x's `stores/conversation/reducer.ts`
  subdir collapses).
- `stores/routing.svelte.ts` — **NEW.** Live `RoutingDecision` for
  the active session + tag-rule cache.
- `stores/quota.svelte.ts` — **NEW.** Latest `QuotaSnapshot` + reset
  countdown.
- `stores/usage.svelte.ts` — **NEW.** 7-day headroom series + by-model
  table + advisor-effectiveness aggregate.
- `stores/override_rates.svelte.ts` — **NEW.** Per-rule 14-day rates
  for the "Review:" highlight.

**Invariant:** every store exports a `$state` proxy + a small
imperative API (`refresh()`, `subscribe()`); reducers are pure
functions that take the current state + an event → next state.
Components subscribe via Svelte's `$derived` or via destructuring;
they never reach into another store's internals.

### 2.3 Consolidation decisions cited

These are the v0.17.x god-class / mixin-sprawl shapes the rebuild
explicitly collapses, with rationale:

1. **`bearings.agent.session.*` (7 modules → 1 + 5 sibling helper modules).**
   v0.17.x split `AgentSession` into a 7-module mixin package
   (`_constants`, `_helpers`, `_history_mixin`, `_hooks_mixin`,
   `_events_mixin`, `_stream_mixin`, `_options`, plus `core`) to fit
   §FileSize. The cost: a 484-line `_stream_mixin.py` declares
   type-only abstract stubs of every sibling-mixin method "to keep
   mypy strict happy" because cross-mixin `self.X` calls don't
   resolve at type-check time. Every new method has to be declared in
   N places. The rebuild collapses the class to one file; the genuine
   sub-concerns (history-prefix building, hook construction, event
   translation, per-turn options assembly) move to *neighbor modules
   exporting pure functions*, not mixins. Cross-module calls are
   `build_options(self, prompt)`, not `self._build_options(prompt)`.
   No abstract-stub shells.

2. **`bearings.agent.auto_driver.*` (5 modules → 1 + 1 types module + 1 runtime module).**
   v0.17.x split `Driver` into `_PersistenceMixin`, `_SessionsMixin`,
   `_DispatchMixin` plus a `contracts.py`. Same pattern, same cost.
   Plus the parallel naming bug: `auto_driver/` (the package) and
   `auto_driver_runtime.py` (the binding module) sit in the same
   parent — one is a state machine, the other binds it to FastAPI.
   The rebuild keeps the binding split (legitimate: different
   lifecycle, different DI), but `Driver` itself is one file with
   private methods.

3. **`bearings.db.store` re-export wall.**
   v0.17.x: 12 `_*.py` modules + a `store.py` that re-exports
   ~100 names so callers can write `from bearings.db import store;
   store.create_session(...)`. The rebuild deletes the wall:
   `from bearings.db import sessions; await sessions.create(...)`.
   Two-layer indirection becomes one.

4. **`bearings.api.routes_*` flat layout (30 modules → `web/routes/` subpackage).**
   Mechanical rename + relocation; no logic change.

5. **v0.17.x's `agent → api` lazy-import cycle.**
   `agent/auto_driver_runtime.py` lazy-imports `build_runner` from
   `api/ws_agent.py`; `agent/sessions_broker.py` lazy-imports
   `SessionOut` from `api/models`. The rebuild breaks the cycle by
   lifting `build_runner` to `web/runner_factory.py` and injecting it
   as a `RunnerFactory: Protocol` at app construction; `SessionsBroker`
   emits structured dicts (or its own dataclass) instead of importing
   a Pydantic model from `web/`.

---

## 3. Import graph

The rebuild has six layers, ordered top-to-bottom by dependency. No
upward import is ever permitted.

```
   ┌───────────┐
   │   cli     │   (CLI subcommands)
   └─────┬─────┘
         │
         ▼
   ┌───────────┐
   │   web     │   (FastAPI routes, WS handlers, app factory)
   └─────┬─────┘
         │
         ▼
   ┌───────────┐
   │  agent    │   (domain: SDK glue, runner, prompt, routing, quota, driver)
   └─────┬─────┘
         │
         ▼
   ┌───────────────────────────┐
   │   db   ▒   bearings_dir   │   (storage / on-disk contract — peers, no edges)
   └───────────────┬───────────┘
                   │
                   ▼
   ┌────────────────────────────┐
   │  config   ▒   metrics       │   (leaf — depend only on stdlib + pydantic)
   └────────────────────────────┘
```

### 3.1 Layer rules (binding)

1. **No upward imports.** `db/` does not import from `agent/`;
   `agent/` does not import from `web/`; `web/` does not import from
   `cli/`.
2. **No sibling cycles within a layer.** `db/sessions.py` does not
   import from `db/messages.py` or vice versa; both import from
   `db/_id.py` and the schema. `agent/quota.py` does not import from
   `agent/routing.py` or vice versa; both import their inputs (DB
   queries, frozen dataclasses) from below.
3. **Protocols cross layers; concrete bindings live at the boundary.**
   `RunnerFactory: Protocol` is declared in `agent/runner.py`; the
   FastAPI-aware concrete factory function lives in
   `web/runner_factory.py` and is injected at app construction. The
   `agent` layer never imports `bearings.web.*`.
4. **No lazy imports across layers to break cycles.** If a tool of
   choice (e.g. `import-linter` or a hand-rolled `pre-commit` check)
   sees a function-local cross-layer import, it fails the build. The
   v0.17.x lazy imports listed above are the worked example of why.
5. **Frontend mirrors the same shape.** `lib/api/*` (HTTP
   clients) → `lib/stores/*` (state) → `lib/components/*` (UI). A
   component never fetches; a store never renders. v0.17.x already
   roughly observes this; the audit on item 2.x makes it strict.

### 3.2 Cycles found in v0.17.x and how the rebuild prevents each

| v0.17.x cycle | Rebuild prevention |
|---|---|
| `bearings.agent.auto_driver_runtime` → `bearings.api.ws_agent.build_runner` (lazy import inside `_dispatch_prompt` and `spawn_leg`) | Lift `build_runner` into `bearings.web.runner_factory` (FastAPI-aware). Declare `RunnerFactory: Protocol` in `agent/runner.py`. `AutoDriverRegistry` constructor takes the factory; `web/app.py` lifespan injects it. |
| `bearings.agent.sessions_broker` → `bearings.api.models.SessionOut` (lazy import inside the publisher) | `SessionsBroker` publishes a frozen `SessionRow` dataclass declared in `agent/sessions_broker.py`. The `web/ws/sessions.py` handler consumes the dataclass and re-validates as `SessionOut` at the wire boundary. |
| `bearings.agent.runner` → `bearings.agent.runner_subscribers` and back (subscribers calls `runner.is_running` etc.) | Runner state moves to a frozen `RunnerStatus` dataclass passed to the subscribers helper as an arg. Module-level dependency goes one way. |
| Mixin-internal "cycles" within `agent/session/` (each mixin calls `self.X` declared on a sibling mixin) | Eliminated: the class is one file with one MRO. |

### 3.3 Layer rule enforcement

`pre-commit` hook (item 0.1's tooling) runs `import-linter` (or
equivalent — `lint-imports` with a small contract file) on every
commit. Layer contracts are declared as `forbidden` rules:

- `bearings.db.*` may not import `bearings.agent.*` or
  `bearings.web.*` or `bearings.cli.*`.
- `bearings.agent.*` may not import `bearings.web.*` or
  `bearings.cli.*`.
- `bearings.web.*` may not import `bearings.cli.*`.
- `bearings.bearings_dir.*` may not import `bearings.agent.*` or
  `bearings.web.*` or `bearings.cli.*`.

The auditor on every Phase 1+2 item verifies the contract file is
unchanged unless the item explicitly amends it (very rare; would mean
an architectural shift the doc must absorb first).

---

## 4. Key interfaces

These are the dataclasses, Protocols, and TypedDicts at module
boundaries — i.e. the shapes a downstream executor needs to know
verbatim to build their item without reading neighboring source.

### 4.1 `RoutingDecision` (spec Appendix A — verbatim)

```python
# agent/routing.py
from dataclasses import dataclass

@dataclass(frozen=True)
class RoutingDecision:
    executor_model: str                # 'sonnet' | 'haiku' | 'opus' | full ID
    advisor_model: str | None          # 'opus' | None
    advisor_max_uses: int              # 0–N; ignored if advisor_model is None
    effort_level: str                  # 'auto' | 'low' | 'medium' | 'high' | 'xhigh'
    source: str                        # 'tag_rule' | 'system_rule' | 'default' |
                                       # 'manual' | 'quota_downgrade' |
                                       # 'manual_override_quota' | 'unknown_legacy'
    reason: str
    matched_rule_id: int | None
    evaluated_rules: list[int]
    quota_state_at_decision: dict[str, float]  # {'overall_used_pct': .., 'sonnet_used_pct': ..}
```

### 4.2 `RoutingRule` / `SystemRoutingRule`

```python
# db/routing.py
@dataclass(frozen=True)
class RoutingRule:
    id: int
    tag_id: int
    priority: int
    enabled: bool
    match_type: Literal['keyword', 'regex', 'length_gt', 'length_lt', 'always']
    match_value: str | None
    executor_model: str
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    reason: str
    created_at: int
    updated_at: int

@dataclass(frozen=True)
class SystemRoutingRule:
    id: int
    priority: int
    enabled: bool
    match_type: Literal['keyword', 'regex', 'length_gt', 'length_lt', 'always']
    match_value: str | None
    executor_model: str
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    reason: str
    seeded: bool
    created_at: int
    updated_at: int
```

### 4.3 `QuotaSnapshot`

```python
# agent/quota.py
@dataclass(frozen=True)
class QuotaSnapshot:
    captured_at: int                # unix seconds
    overall_used_pct: float | None  # 0.0–1.0 (None when /usage unreachable)
    sonnet_used_pct: float | None
    overall_resets_at: int | None
    sonnet_resets_at: int | None
    raw_payload: str                # JSON, forward-compat carrier
```

### 4.4 Pure-function signatures at boundaries

```python
# agent/routing.py
def evaluate(
    message: str,
    tags_with_rules: list[tuple[int, list[RoutingRule]]],
    system_rules: list[SystemRoutingRule],
    quota_snapshot: QuotaSnapshot | None,
) -> RoutingDecision: ...

# agent/quota.py
def apply_quota_guard(
    decision: RoutingDecision,
    snapshot: QuotaSnapshot | None,
) -> RoutingDecision: ...
```

These two functions are pure (no DB, no I/O) so the ≥15 routing /
≥10 quota-guard unit-test bars from item 1.8 are reachable without
fixtures heavier than dataclass literals.

### 4.5 `RunnerFactory` Protocol

```python
# agent/runner.py
from typing import Protocol
from collections.abc import Awaitable

class RunnerFactory(Protocol):
    async def __call__(self, session_id: str) -> "SessionRunner": ...
```

Implementation lives in `web/runner_factory.py:build_runner`. The
`agent` layer takes the Protocol as a constructor arg (in
`AutoDriverRegistry`, in `tool_deny_callback`'s prompt-dispatch
closure, in the `RunnerRegistry.get_or_create` factory= keyword).

### 4.6 `DriverRuntime` Protocol

```python
# agent/auto_driver_types.py
from typing import Protocol

class DriverRuntime(Protocol):
    async def spawn_leg(
        self, *, item: dict[str, Any], leg_number: int, plug: str | None
    ) -> str: ...
    async def run_turn(
        self, *, leg_session_id: str, prompt: str
    ) -> str: ...
    async def teardown_leg(self, *, leg_session_id: str) -> None: ...
    def last_context_percentage(self, leg_session_id: str) -> float | None: ...
```

### 4.7 `AgentEvent` discriminated union

Pydantic models with `type` literal discriminator. Every event
carries `session_id`. The set:

```python
AgentEvent = (
    UserMessage | Token | Thinking
    | ToolCallStart | ToolCallEnd | ToolOutputDelta | ToolProgress
    | MessageStart | MessageComplete
    | ContextUsage | ErrorEvent | TurnReplayed
    | ApprovalRequest | ApprovalResolved
    | TodoWriteUpdate | RoutingBadge  # RoutingBadge is NEW per spec §5
)
```

Spec §5 adds `RoutingBadge` carrying `executor_model`, `advisor_model`,
`advisor_calls_count`, `effort_level`, `routing_source`, `routing_reason`
per assistant message (one event per `MessageComplete`, fan-out only).

`MessageComplete` extends to include the same per-model usage fields:
`executor_input_tokens`, `executor_output_tokens`, `advisor_input_tokens`,
`advisor_output_tokens`, `advisor_calls_count`, `cache_read_tokens`.
v0.17.x's `MessageComplete` carries flat `input_tokens` /
`output_tokens` only; the rebuild keeps those as
`Optional[int]` for tools that read pre-routing-aware data, but the
canonical numbers are per-model.

### 4.8 `SessionConfig`

```python
# agent/session.py
@dataclass(frozen=True)
class SessionConfig:
    session_id: str
    working_dir: str
    decision: RoutingDecision           # carries executor_model, advisor_model, effort
    db: aiosqlite.Connection | None
    sdk_session_id: str | None = None
    permission_mode: PermissionMode | None = None
    thinking: ThinkingConfig | None = None
    setting_sources: list[SettingSource] | None = None
    inherit_mcp_servers: bool = True
    inherit_hooks: bool = True
    tool_output_cap_chars: int = 8000
    enable_bearings_mcp: bool = True
    enable_precompact_steering: bool = True
    enable_researcher_subagent: bool = False
    max_budget_usd: float | None = None
```

`AgentSession.__init__(config: SessionConfig)` is the only constructor
shape. v0.17.x's 14-positional-arg constructor is gone — every call
site builds a `SessionConfig` via keyword args, which mypy validates
field-by-field.

### 4.9 `RoutingPreviewResponse` (spec §9 wire shape)

```python
# web/models/routing.py — TypedDict for the wire payload
class RoutingPreviewResponse(TypedDict):
    executor: str
    advisor: str | None
    advisor_max_uses: int
    effort: str
    source: str
    reason: str
    evaluated_rules: list[int]
    quota_downgrade_applied: bool
```

### 4.10 `AssembledPrompt` / `Layer`

Kept from v0.17.x. Frozen dataclasses; pure assembler output.

```python
# agent/prompt.py
LayerKind = Literal[
    'base', 'session_identity', 'session_description',
    'tag_memory', 'checklist_context', 'checklist_overview',
    'directory_bearings', 'directory_onboarding', 'session',
]

@dataclass(frozen=True)
class Layer:
    name: str
    kind: LayerKind
    content: str

@dataclass(frozen=True)
class AssembledPrompt:
    layers: list[Layer]
    text: str
```

### 4.11 `RunnerStatus`

Kept from v0.17.x as a frozen enum-like dataclass, but with an extra
field carrying the active `RoutingDecision` so the WS `runner_status`
frame can render the routing badge on the first paint after reconnect.

```python
# agent/runner.py
@dataclass(frozen=True)
class RunnerStatus:
    is_running: bool
    is_awaiting_user: bool
    routing_decision: RoutingDecision | None  # NEW; v0.17.x has no routing
```

---

## 5. SDK currency audit

Every platform shift since v0.17.x's `claude-agent-sdk` integration
was last revisited, named here, with *what v0.17.x stands on today*,
*what the rebuild does*, and *which file owns the wiring*. All shifts
verified against current SDK docs via context7 (`/anthropics/claude-agent-sdk-python`,
queried 2026-04-28); Anthropic's library docs are the source of truth
for current option-shape and method names.

| # | Platform shift | v0.17.x stand | Rebuild behavior | Owner module |
|---|---|---|---|---|
| 1 | **Advisor tool primitive** (`advisor_20260301`, generally available behind beta header `advisor-tool-2026-03-01`; executor consults Opus mid-generation in a single API call; default `max_uses=5`) | No advisor concept anywhere. Sessions are single-model. | `RoutingDecision.advisor_model` non-null → `agent/options.py` adds `advisor-tool-2026-03-01` to `betas`, registers the advisor (the SDK exposes the tool to the executor when the beta header is present), wires `advisor_max_uses` from the decision. The executor decides when to consult per spec §2; Bearings observes via `model_usage` and emits a `RoutingBadge` per turn with the count. | `agent/options.py`, `agent/persistence.py`, `agent/events.py:RoutingBadge` |
| 2 | **Beta headers** (`betas: list[str]` on `ClaudeAgentOptions`) | Not used. `ClaudeAgentOptions` constructed without `betas`. | `agent/options.py:build_options` always sets `betas=[...]` computed from the active routing decision. The advisor-tool beta ID is the spec-pinned `advisor-tool-2026-03-01` constant in `config/constants.py` so a future bump touches one symbol. | `agent/options.py`, `config/constants.py` |
| 3 | **`model_usage` shape** (per-model breakdown on `ResultMessage`) | `MessageComplete` persists flat `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_creation_tokens` (see v0.17.x `agent/events.py`). No per-model split. | New `messages` columns from spec §5 added day 1 (no ALTER chain): `executor_input_tokens`, `executor_output_tokens`, `advisor_input_tokens`, `advisor_output_tokens`, `advisor_calls_count`, `cache_read_tokens`. `agent/persistence.py:persist_assistant_turn` reads `result.model_usage` (the SDK exposes per-model token counts on the result message) and writes the columns. `MessageComplete` Pydantic model carries the same fields on the wire. | `agent/persistence.py`, `agent/events.py`, `db/messages.py`, `db/schema.sql` |
| 4 | **Effort levels** (`effort: 'low' \| 'medium' \| 'high' \| 'max'` direct field on `ClaudeAgentOptions`) | Not set (v0.17.x predates the field). The CLI's `CLAUDE_CODE_EFFORT_LEVEL=auto` env-var path is also unwired. | `RoutingDecision.effort_level` ∈ `{auto, low, medium, high, xhigh}` (spec vocabulary) maps to SDK `effort` literal via a table in `config/constants.py`: `auto → omit (let SDK pick) ; low → 'low' ; medium → 'medium' ; high → 'high' ; xhigh → 'max'`. **Decision rationale:** the spec uses `auto`/`xhigh` because that's the user-facing labelling the routing rules are written against; the SDK exposes `effort` as a hard field with `low/medium/high/max`. Putting the translation in `constants.py` means a future SDK literal addition (e.g. `auto` becomes a real value) is a one-line table edit. | `agent/options.py`, `config/constants.py` |
| 5 | **`fallback_model`** (`fallback_model: str | None`) | Not set. v0.17.x sessions have no automatic tier-down. | `agent/options.py:build_options` always sets `fallback_model` to the executor's tier-down: `sonnet → haiku`, `opus → sonnet`, `haiku → haiku` (no further). Mapping is a `dict[str, str]` constant in `config/constants.py`. The SDK auto-falls-back if the primary model is unavailable; spec doesn't elaborate further. | `agent/options.py`, `config/constants.py` |
| 6 | **Subagent auto-select** (Anthropic auto-selects Haiku for the Explore subagent; spec §3 priority 30 codifies this) | v0.17.x registers a `researcher` subagent with `model="inherit"` so the parent's model also runs the subagent. | Keep `model="inherit"` on the `researcher` AgentDefinition so the parent's executor runs it (avoids double-Opus when an Opus parent invokes Task). The "Haiku for Explore" auto-select happens at the *parent's routing layer* via the spec §3 priority-30 rule (`keyword: explore, find where, ...`) → executor=haiku, advisor=opus. **Decision rationale:** pinning Haiku on the AgentDefinition would override the auto-select; routing handles the same intent at the spec layer where the user can edit it. | `agent/options.py` (researcher AgentDefinition unchanged), `db/schema.sql` (priority-30 seed) |
| 7 | **Streaming events** (`include_partial_messages=True` opens a `StreamEvent` partials channel; `text_delta` and (where supported by the model) `thinking_delta` partials interleave; not all models emit `thinking_delta` — the streamed-this-msg flag must track per-block-type so a non-streamed thinking block in a final `AssistantMessage` is not mistakenly suppressed) | v0.17.x already uses `include_partial_messages=True`, has the per-block-type `streamed_text` / `streamed_thinking` flags in `_stream_mixin.py`, and translates partials in `_events_mixin.py`. | Kept verbatim (the v0.17.x logic is correct against current SDK); `agent/translate.py` re-houses the same translation as pure functions. The auditor on item 1.2 verifies the per-block-type-flag invariant via a regression test using a recorded SDK response stream where `text_delta` fires but `thinking_delta` doesn't. | `agent/session.py`, `agent/translate.py` |
| 8 | **`ClaudeSDKClient.set_model()`** (mid-session executor swap; new in current SDK) | Not used. Mid-session model change in v0.17.x means tear-down-runner-and-rebuild. | New endpoint `PATCH /api/sessions/{id}/model` calls `runner.set_model(name)` which forwards to `client.set_model(name)` on the live `ClaudeSDKClient`. Persists to `sessions.model`. The spec §7 manual-switch flow opens the re-cost confirmation client-side; the backend just applies. **Decision rationale:** preserving the live client preserves the SDK session — no second `resume=` round-trip, no fresh subprocess. | `agent/runner.py`, `agent/session.py`, `web/routes/sessions.py` |
| 9 | **`ClaudeSDKClient.set_permission_mode()`** | Already used in v0.17.x. | Kept. `runner.set_permission_mode()` forwards as before. | unchanged |
| 10 | **`ClaudeSDKClient.get_context_usage()` (camelCase keys: `percentage`, `totalTokens`, `maxTokens`)** | Already used. | Kept; `agent/translate.py` adapts to snake_case for the wire `ContextUsage` event as before. | `agent/translate.py` |
| 11 | **`ClaudeSDKClient.get_server_info()` / `get_mcp_status()`** | Not used. | New diagnostic surface: `web/routes/diag.py:GET /api/diag/server` returns the SDK's reported slash-commands list and MCP status, useful for "is the bearings MCP server actually attached?" debugging. Out of v0.18.0 scope is *exposing* it in the frontend; the route exists for the next wave. | `web/routes/diag.py` |
| 12 | **`enable_file_checkpointing`** (SDK-side file-snapshot checkpointing) | Not used. v0.17.x has its own `checkpoints` table with named/restorable snapshots. | **Decision: keep Bearings' own checkpoints in v0.18.0.** SDK-side checkpointing is automatic per-write; Bearings' user-facing checkpoint is a *named* snapshot the user creates intentionally. The semantics differ enough that conflating them costs more than it saves. Filed as `TODO.md` follow-up: investigate whether SDK checkpointing can replace `checkpoints/restore` automatic-restore semantics in a v1.x. | `db/checkpoints.py` (kept), `TODO.md` (follow-up) |
| 13 | **`sandbox=SandboxSettings(...)`** (SDK-side bash sandboxing) | Not used. v0.17.x has its own streaming bash via the in-process MCP server. | **Decision: keep Bearings' bash + add SDK sandbox in a follow-up.** The streaming-bash MCP tool gives Bearings the live tool-output deltas the UI depends on; SDK sandbox is orthogonal but does not deliver line-by-line streaming. v0.18.0 ships the streaming MCP bash; sandbox enablement filed in `TODO.md`. | `agent/mcp/streaming_bash.py` (kept), `TODO.md` (follow-up) |
| 14 | **`output_format={"type":"json_schema", ...}`** + `ResultMessage.structured_output` | Not used. v0.17.x's `enable_llm_reorg_analyze` parses LLM JSON by hand. | **Decision: out of v0.18.0 scope.** The LLM-reorg analyzer is feature-flag-off by default in v0.17.x; the spec doesn't require it. v0.18.0 keeps the feature gate off and the hand-parser as a regression-equivalent path. Adopting `output_format` is a v1.x cleanup. Filed in `TODO.md`. | n/a |
| 15 | **`task_budget={"total": N}`** | Not used. v0.17.x has `max_budget_usd`. | Kept: `max_budget_usd` is the user-facing cap (dollars on PAYG, cosmetic on subscription). `task_budget` is a token-count cap; on subscription auth it's not what the user thinks about (they think in quota %, which the quota-guard handles per spec §4). Out of v0.18.0 scope. | n/a |
| 16 | **`extra_args={...}` CLI passthrough** | Not used. | Out of v0.18.0 scope. | n/a |

The rebuild runs against the SDK pin in CLAUDE.md (`claude-agent-sdk~=0.1.69`,
compatible-release). When the SDK ships a new minor that adds an
explicit `auto` effort literal or moves the advisor beta to GA-without-
header, this audit gets re-walked and `config/constants.py` absorbs the
delta in one place.

### 5.1 Sources cited (context7 traversal)

- `/anthropics/claude-agent-sdk-python` — `ClaudeAgentOptions`
  configuration (every option named in the table above is keyed off
  the canonical option-set returned by the docs).
- `/anthropics/claude-agent-sdk-python` — `ClaudeSDKClient` API
  surface (`set_model`, `set_permission_mode`, `interrupt`,
  `get_context_usage`, `get_server_info`, `get_mcp_status`).
- `/anthropics/claude-agent-sdk-python` — `AgentDefinition`
  (subagent description / prompt / tools / model / `maxTurns` /
  `disallowedTools`; note the camelCase on the dataclass field
  names — both `maxTurns` and `disallowedTools` carry through to the
  CLI, so the rebuild stays on snake_case for its own field surface
  and only flips to camelCase at the SDK boundary).
- `docs/model-routing-v1-spec.md` Appendix A and §5 — `RoutingDecision`
  shape, per-message column set, advisor beta header ID.

---

## 6. Divergences from v0.17.x — appendix

Inline citations above name the divergence at the point it lives.
This appendix collects what doesn't fit elsewhere — divergences-of-
omission (something v0.17.x does that the rebuild deliberately drops),
plus the cross-cutting renames whose justifications didn't have a
natural single home.

### 6.1 Divergences-of-omission (v0.17.x has it; rebuild deliberately omits)

| What v0.17.x does | Why the rebuild drops it |
|---|---|
| `bearings.db.store` re-export wall (`store.create_session`, `store.attach_tag`, …) | Two-layer indirection; no caller benefits. See §2.3 #3. |
| `agent/session/_constants.py` + `_helpers.py` + `_options.py` + four mixin modules | Mixin sprawl driven by §FileSize-cap satisfaction, not concern boundary. Replaced with one canonical `agent/session.py` + neighbor modules exporting pure functions. |
| `agent/auto_driver/` 5-module package + `auto_driver_runtime.py` parallel name | Same pattern, same cost. Replaced with `agent/auto_driver.py` (single file) + `agent/auto_driver_types.py` + `agent/auto_driver_runtime.py`. |
| `from bearings.api.ws_agent import build_runner` lazy imports inside `agent/auto_driver_runtime.py` | Hides a layer violation. Replaced by `RunnerFactory: Protocol` injection at app construction (§3.2). |
| `from bearings.api.models import SessionOut` lazy import inside `agent/sessions_broker.py` | Same. Replaced by `agent` layer publishing its own dataclass; `web` revalidates at the wire boundary. |
| `routes_*.py` flat at `api/` root (30 modules) | Mechanical: subpackage `web/routes/` reads better. |
| `bearings_dir/{onboard, on_open, auto_onboard, brief, init_dir, check}.py` (six small modules) | Combined into `bearings_dir/onboarding.py` — the six modules answer the same surface (first-time flow + brief composition). |
| Inline numeric defaults inside `config.py` Pydantic field declarations | Audit on item 0.5 fails any inline literal in subsequent items; making `config/constants.py` the single source of truth makes the audit a grep. |
| `bearings.uploads_gc` as a top-level module | Only the CLI calls it; moves under `cli/gc.py`. |
| `bearings.menus` as a top-level module | Hot-reloaded never; consolidated as a small helper inside `web/routes/config.py`. |
| `bearings.profiles` as a top-level module | Profile presets live under `config/profiles.py`. |
| Inline `_BundleStaticFiles` (200 lines) inside `server.py` | Lifted to `web/static.py` so `web/app.py` is a thin factory. |

### 6.2 Renames adopted as a set

The rebuild renames `api` → `web`, `agent/approval_broker.py` →
`agent/approval.py`, `agent/checklist_sentinels.py` →
`agent/sentinel.py`, `agent/_artifacts.py` → `agent/artifacts.py`,
`agent/_attachments.py` → `agent/attachments.py`,
`agent/mcp_tools.py` → `agent/mcp/server.py`,
`bearings_dir/schema.py` → `bearings_dir/contract.py`. Each rename
is a one-word fix where the v0.17.x name carries a vestigial prefix
(`_`, `api`) or a redundant suffix (`_broker`, `_tools`). No behavior
change.

### 6.3 Convergences kept consciously

These are v0.17.x shapes the rebuild keeps because they are right —
named here so the audit can verify they are conscious convergences,
not lazy ones.

| Kept | Why |
|---|---|
| `claude-agent-sdk~=0.1.69` compatible-release pin | Already chosen by CLAUDE.md; SDK currency audit confirms the surface used is current. |
| Pydantic for wire shapes | Stable, mypy-strict friendly, integrates with FastAPI. |
| `aiosqlite` for the DB | Single-writer SQLite + WAL is the right choice for a localhost tool. |
| `RunnerRegistry` keyed by session id with idle-reap | Decouples session lifecycle from WS lifecycle. The pattern is correct; only the constructor's `RunnerFactory` injection is new. |
| Layered system-prompt assembler with per-turn re-read | Edits to tag memories / session instructions take effect on the next turn without runner respawn; the re-read-per-turn pattern is correct. |
| `include_partial_messages=True` + per-block-type streamed flag | Correct against current SDK; the per-type flag is load-bearing for models whose `thinking_delta` partials don't fire. |
| `ResultMessage.total_cost_usd` as the PAYG cost source | Spec §11 confirms this. |
| Bearings in-process MCP server with `bearings__get_tool_output` + streaming bash + `bearings__dir_init` | Three real tools, each with a real consumer; structure unchanged, only the file layout under `agent/mcp/` is new. |
| Per-session WS subscriber model with ring buffer + `since_seq` replay | Correct; reconnects work. |
| Per-session `ApprovalBroker` future map | Correct shape for `can_use_tool`. |

### 6.4 Convergences NOT kept (renamed for clarity)

These are v0.17.x shapes the rebuild keeps the *behavior* of, but
renames the *carrier* so the audit doesn't flag a near-copy as
unintentional:

- `_artifacts.py` → `artifacts.py` (leading underscore implied module-private, but `agent/persist.py` and `web/routes/artifacts.py` both depend on it; not module-private).
- `_attachments.py` → `attachments.py` (same).
- `checklist_sentinels.py` → `sentinel.py` (the "checklist_" prefix duplicates the parent package name; `from bearings.agent import sentinel` reads correctly).

### 6.5 Architectural uncertainties (deferred-review triggers)

Per the autonomy contract: code-uncertainty escalation in a design
doc is the doc's content. Naming each uncertainty here, with the
chosen path and the trigger that re-opens it.

1. **`effort='auto'` translation.** The SDK's `effort` literal does
   not include `auto` as of the queried docs. The spec writes rules
   in `auto`/`low`/`medium`/`high`/`xhigh` because that's the
   user-facing vocabulary. Decision: omit the `effort` field when
   `auto`, map `xhigh → 'max'` per §5 #4. **Re-open trigger:** SDK
   adds an `auto` literal, OR Anthropic deprecates `xhigh` /
   renames `max`. Item 0.5's `config/constants.py:EFFORT_TABLE`
   is the single edit point.

2. **`set_model()` mid-session vs runner rebuild.** The rebuild
   uses `client.set_model()` per spec §7. **Re-open trigger:**
   `set_model()` turns out to silently re-cost the conversation
   history at the new model's rate (spec §7 admits this estimate is
   approximate; if the SDK does the re-cost server-side anyway,
   surfacing the estimate becomes more important not less). Owner:
   item 1.2's executor verifies via integration test against a
   recorded SDK response.

3. **Advisor wire-up.** The current SDK docs name the advisor as a
   beta-tool primitive but don't show an explicit dataclass field
   for `advisor_max_uses`. The rebuild assumes the SDK auto-attaches
   the advisor when the beta header is present and the executor
   discovers it via tool-list introspection; `advisor_max_uses` is
   enforced by the executor at runtime per spec §2 (the executor
   stops calling once it has called `max_uses` times). **Re-open
   trigger:** SDK exposes an explicit advisor-config field; item
   1.8's executor wires it through `agent/options.py` and the audit
   walks every routing call site. If the SDK *requires* a tool
   registration of the advisor name (rather than being-implicitly-
   exposed-by-the-beta-header), `agent/options.py` adds the
   registration alongside the beta-header set.

4. **`agent/runner.py` 450-line ceiling.** The 50-line over-cap
   exception is a smell. **Re-open trigger:** if `runner.py` grows
   past 500 in the rebuild, the worker loop and the subscriber
   plumbing split — `agent/runner_worker.py` for the loop,
   `agent/runner.py` keeps the public class. Item 1.1's auditor
   checks the line count.

5. **`SessionsBroker` dataclass shape.** The rebuild lifts a
   structured dict (or frozen dataclass) up out of v0.17.x's lazy
   `SessionOut` import. The shape is duplicated (broker emits one,
   `web/models/sessions.py` defines another for the wire); they
   must stay in sync. **Re-open trigger:** if a future field is
   added to one without the other, `web/ws/sessions.py`'s consumer
   fails validation on the next published row. The audit on item
   1.1 checks both shapes are derived from the same DB query
   shape (test uses one, validates the other). A Protocol or
   shared `TypedDict` is the next move if the duplication bites.

6. **Override aggregator: in-memory vs DB-backed.** The rolling
   14-day window is computable from `messages` table queries
   (`routing_source = 'manual_override_quota'` etc.). Decision:
   compute on demand with a 60-second cache (per call to
   `routes/usage.py`); no separate aggregation table. **Re-open
   trigger:** the on-demand query gets slow at >100k messages.
   Owner: item 1.8's executor benchmarks; if the query exceeds
   200ms p95, an aggregation table lands in the same item.

7. **`config/constants.py` location of the priority-ladder values.**
   Spec §3's priority-10/20/30/40/50/60/1000 ladder is *seeded into
   the DB* (`system_routing_rules.priority` columns, `seeded=1`).
   The decision: source-of-truth is the DB seed in `db/connect.py`,
   not `config/constants.py` — the user can edit the seeded rules
   after first-run, so a `Final[int]` constant would lie. The
   constants module names the *defaults* the seed populates; the
   live values are read from the DB on every routing evaluation.
   **Re-open trigger:** if a future rebuild wants the rules to be
   non-editable factory defaults, the constants and the seed
   converge into one source. Filed in `TODO.md`.

---

## End of doc

Verification: every Done-when criterion from master item #522 is
addressed in §1–6 above. The self-verification block landing in the
session-final message records the criterion-by-criterion evidence.
