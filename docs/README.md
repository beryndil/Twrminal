# Bearings — Documentation index

This is the front door to the Bearings doc set. Every doc in the
repo is reachable from here through one of six lookup paths:
[concept](#by-concept), [task](#by-task),
[API route group](#by-api-route-group),
[code package](#by-code-package),
[frontend route](#by-frontend-route), or [behavior topic](#by-behavior-topic).

If you're new to Bearings, read these four pages **in this order**:

1. [concepts.md](concepts.md) — the connected mental model. What
   a session, tag, paired chat, memory, and routing decision
   actually are. ~30 minutes.
2. [guide/getting-started.md](guide/getting-started.md) — install,
   first run, first session. ~10 minutes hands-on.
3. [guide/](guide/) — task-oriented walkthroughs by workflow
   bucket. Skim the ToCs; deep-read the ones for what you're
   doing.
4. [api.md](api.md) — curated HTTP/WS API reference grouped by
   route prefix.

Then dive in by lookup path below.

---

## Document layers

The doc set has **three layers**, each with a different audience:

| Layer | Files | Audience | When to read |
|---|---|---|---|
| **Concepts** | [concepts.md](concepts.md) | Anyone using or working on Bearings | First — to ground every other doc. |
| **Guides** (task-oriented) | [guide/](guide/) — 10 files | End users + new contributors | When you're doing a thing and want the canonical recipe. |
| **Reference** (observable behavior + architecture + API) | [behavior/](behavior/) + [architecture-v1.md](architecture-v1.md) + [model-routing-v1-spec.md](model-routing-v1-spec.md) + [api.md](api.md) + [openapi.json](openapi.json) | Implementers + auditors | When the guide is too coarse and you need wire shapes / class boundaries / numeric thresholds. |

The [audit register at repo root](../V1_FEATURE_AUDIT.md) is a
fourth layer — historical, not user-facing. Cited from concepts.md
as a footnote.

---

## By concept

| Concept | Where it lives |
|---|---|
| Session model + lifecycle | [concepts.md §2](concepts.md#2-the-session-model) · [guide/sessions.md](guide/sessions.md) · [behavior/sessions.md](behavior/sessions.md) · [behavior/chat.md](behavior/chat.md) |
| Tags + classes (project / severity / general) | [concepts.md §3](concepts.md#3-how-tags-drive-everything) · [guide/settings.md §Tags page](guide/settings.md#tags-page-separate-route) |
| Routing v1 (per-tag rules, system rules, advisor, quota guard) | [concepts.md §4](concepts.md#4-routing-v1-in-one-page) · [guide/routing.md](guide/routing.md) · [behavior/routing.md](behavior/routing.md) · [model-routing-v1-spec.md](model-routing-v1-spec.md) |
| Quota guard + override aggregator | [concepts.md §4.4](concepts.md#44-quota-guard) · [guide/routing.md](guide/routing.md) · [guide/analytics.md](guide/analytics.md) |
| Checklists + autonomous driver + sentinels | [concepts.md §5](concepts.md#5-paired-chats-and-checklists) · [guide/checklists.md](guide/checklists.md) · [behavior/checklists.md](behavior/checklists.md) |
| Paired chats + breadcrumbs + cascades | [concepts.md §5.1](concepts.md#51-the-pair-relationship) · [guide/paired-chats.md](guide/paired-chats.md) · [behavior/paired-chats.md](behavior/paired-chats.md) |
| Vault (read-only plans + TODOs) | [concepts.md §6.1](concepts.md#61-the-vault--read-only-plans--todos) · [guide/vault-and-memories.md](guide/vault-and-memories.md) · [behavior/vault.md](behavior/vault.md) |
| Memories (tag-keyed system-prompt overlays) | [concepts.md §6.2](concepts.md#62-memories--tag-keyed-system-prompt-overlays) · [guide/vault-and-memories.md](guide/vault-and-memories.md) · [behavior/memories.md](behavior/memories.md) |
| System-prompt assembly | [concepts.md §6.3](concepts.md#63-the-full-system-prompt-stack) · [guide/inspector.md §Instructions tab](guide/inspector.md#instructions-tab) |
| Inspector (8-tab right drawer) | [guide/inspector.md](guide/inspector.md) · [behavior/chat.md §Inspector pane](behavior/chat.md#inspector-pane-non-routing-subsections) |
| Analytics (bucket attribution + redundancy + plug-length) | [guide/analytics.md](guide/analytics.md) · [BEARINGS_ANALYTICS_v1.md](../BEARINGS_ANALYTICS_v1.md) |
| Themes / keybindings / context menus | [guide/settings.md](guide/settings.md) · [behavior/themes.md](behavior/themes.md) · [behavior/keyboard-shortcuts.md](behavior/keyboard-shortcuts.md) · [behavior/context-menus.md](behavior/context-menus.md) |
| `.bearings/` directory contract | [behavior/bearings-cli.md](behavior/bearings-cli.md) · [architecture-v1.md §1.1.6](architecture-v1.md#116-bearingsbearings_dir--directory-context-contract) |

---

## By task

Alphabetical task index across every guide page.

| Task | Where |
|---|---|
| Add a checklist item | [guide/checklists.md §Add and edit items](guide/checklists.md#add-and-edit-items) |
| Add a tag inline from the new-session dialog | [guide/sessions.md §Creating a session](guide/sessions.md#creating-a-session) |
| Archive (close) a session | [guide/sessions.md §Archive (close) a session](guide/sessions.md#archive-close-a-session) |
| Audit which memories are layered into a session | [guide/vault-and-memories.md §Audit which memories are layered](guide/vault-and-memories.md#audit-which-memories-are-layered) |
| Bulk operations on multiple sessions | [guide/sessions.md §Bulk operations](guide/sessions.md#bulk-operations-on-multiple-sessions) |
| Configure new-session defaults | [guide/settings.md §Defaults section](guide/settings.md#defaults-section) |
| Copy a vault doc body or link | [guide/vault-and-memories.md §Copy a doc body / link](guide/vault-and-memories.md#copy-a-doc-body--link) |
| Create a chat session | [guide/getting-started.md §4](guide/getting-started.md#4-create-your-first-chat-session) · [guide/sessions.md §Creating a session](guide/sessions.md#creating-a-session) |
| Create a checklist session | [guide/checklists.md §Create a checklist session](guide/checklists.md#create-a-checklist-session) |
| Create a memory under a tag | [guide/vault-and-memories.md §Edit or create a memory](guide/vault-and-memories.md#edit-or-create-a-memory-under-a-tag) |
| Create a system-wide routing rule | [guide/routing.md §Create a system-wide fallback rule](guide/routing.md#create-a-system-wide-fallback-rule) |
| Create a tag-specific routing rule | [guide/routing.md §Create a tag-specific routing rule](guide/routing.md#create-a-tag-specific-routing-rule) |
| Delete a session permanently | [guide/sessions.md §Delete a session permanently](guide/sessions.md#delete-a-session-permanently) |
| Detach a paired chat | [guide/paired-chats.md §Detach a paired chat](guide/paired-chats.md#detach-a-paired-chat) |
| Disable a routing rule without deleting it | [guide/routing.md §Disable a rule without deleting it](guide/routing.md#disable-a-rule-without-deleting-it) |
| Drag-drop import multiple session JSONs | [guide/sessions.md §Drag-drop import multiple JSONs](guide/sessions.md#drag-drop-import-multiple-jsons) |
| Edit per-session instructions | [guide/inspector.md §Instructions tab](guide/inspector.md#instructions-tab) |
| Enable / disable a memory | [guide/vault-and-memories.md §Enable / disable a memory](guide/vault-and-memories.md#enable--disable-a-memory) |
| Export a session as JSON | [guide/sessions.md §Export a session as JSON](guide/sessions.md#export-a-session-as-json) |
| Find keyboard shortcuts | [guide/settings.md §Help section](guide/settings.md#help-section) · [behavior/keyboard-shortcuts.md](behavior/keyboard-shortcuts.md) |
| Force a fresh quota snapshot | [guide/routing.md §Force a fresh quota snapshot](guide/routing.md#force-a-fresh-quota-snapshot) |
| Fork a session from a specific message | [guide/sessions.md §Fork a session from a specific message](guide/sessions.md#fork-a-session-from-a-specific-message) |
| Garbage-collect old uploads | [guide/cli.md §`bearings gc uploads`](guide/cli.md#bearings-gc-uploads) |
| Import a session from JSON | [guide/sessions.md §Import a session from JSON](guide/sessions.md#import-a-session-from-json) |
| Install Bearings | [guide/getting-started.md §1](guide/getting-started.md#1-install) |
| Link an existing chat to a checklist leaf | [guide/paired-chats.md §Link an existing chat to a leaf](guide/paired-chats.md#link-an-existing-chat-to-a-leaf) |
| Manage tags | [guide/settings.md §Tags page (separate route)](guide/settings.md#tags-page-separate-route) |
| Mark sessions viewed (clear the green pip) | [guide/sessions.md §Mark sessions viewed](guide/sessions.md#mark-sessions-viewed) |
| Navigate between sessions (j/k, Alt+1..9) | [guide/sessions.md §Navigating between sessions](guide/sessions.md#navigating-between-sessions) |
| Open the inspector | [guide/inspector.md §Opening the inspector](guide/inspector.md#opening-the-inspector) |
| Open the vault | [guide/vault-and-memories.md §Open the vault](guide/vault-and-memories.md#open-the-vault) |
| Override a quota-downgrade banner | [guide/routing.md §Override a quota-downgrade banner](guide/routing.md#override-a-quota-downgrade-banner) |
| Override routing before starting a session | [guide/routing.md §Override routing before start](guide/routing.md#override-routing-before-start) |
| Pin / unpin a session | [guide/sessions.md §Pin / unpin a session](guide/sessions.md#pin--unpin-a-session) |
| Promote a repeated plug to a tag memory | [guide/analytics.md §Promote a repeated plug to a tag memory](guide/analytics.md#promote-a-repeated-plug-to-a-tag-memory) |
| Read advisor effectiveness | [guide/analytics.md §Advisor effectiveness](guide/analytics.md#advisor-effectiveness--rules-to-review) · [guide/inspector.md §Usage tab](guide/inspector.md#usage-tab) |
| Read app-wide token rollups | [guide/inspector.md §Usage tab](guide/inspector.md#usage-tab) · [guide/analytics.md](guide/analytics.md) |
| Read per-message routing badge | [guide/routing.md §Read the routing badge](guide/routing.md#read-the-routing-badge) |
| Read per-session token + tool-call counters | [guide/inspector.md §Metrics tab](guide/inspector.md#metrics-tab) |
| Read the rules-to-review list | [guide/routing.md §Rules-to-review](guide/routing.md#rules-to-review) |
| Read the "Why this model?" debug chain | [guide/routing.md §"Why this model?" debug chain](guide/routing.md#why-this-model-debug-chain) |
| Recover after server restart mid-run | [guide/checklists.md §Recover after a server restart](guide/checklists.md#recover-after-a-server-restart) |
| Rename a session inline | [guide/sessions.md §Rename a session inline](guide/sessions.md#rename-a-session-inline) |
| Reopen a closed session | [guide/sessions.md §Reopen a closed session](guide/sessions.md#reopen-a-closed-session) |
| Run the autonomous driver | [guide/checklists.md §Start the autonomous driver](guide/checklists.md#start-the-autonomous-driver) |
| Run the server | [guide/getting-started.md §2](guide/getting-started.md#2-run-the-server) · [guide/cli.md §`bearings serve`](guide/cli.md#bearings-serve) |
| Save a session as a template | [guide/sessions.md §Save a session as a template](guide/sessions.md#save-a-session-as-a-template) |
| Search the vault | [guide/vault-and-memories.md §Search across plans + TODOs](guide/vault-and-memories.md#search-across-plans--todos) |
| Send whole-list instructions (ChecklistChat) | [guide/checklists.md §Send whole-list instructions](guide/checklists.md#send-whole-list-instructions) |
| Set or rotate the auth token | [guide/settings.md §Authentication section](guide/settings.md#authentication-section) |
| Spawn a new chat from an assistant reply | [guide/sessions.md §Spawn a new chat from an assistant reply](guide/sessions.md#spawn-a-new-chat-from-an-assistant-reply) · [guide/paired-chats.md §Spawn from reply](guide/paired-chats.md#spawn-from-reply) |
| Spawn a paired chat from a checklist leaf | [guide/paired-chats.md §Spawn a paired chat from a leaf](guide/paired-chats.md#spawn-a-paired-chat-from-a-leaf) |
| Stop a turn (with undo grace window) | [guide/getting-started.md §7](guide/getting-started.md#7-stop-a-turn) |
| Suppress an analytics warning | [guide/analytics.md §Suppress a warning you've reviewed](guide/analytics.md#suppress-a-warning-youve-reviewed) |
| Swap the executor mid-session | [guide/routing.md §Swap the executor mid-session](guide/routing.md#swap-the-executor-mid-session) |
| Switch theme | [guide/settings.md §Appearance section](guide/settings.md#appearance-section) |
| TODO.md tooling (open / check / add / recent) | [guide/cli.md §`bearings todo`](guide/cli.md#bearings-todo) |
| View every memory across every tag | [guide/vault-and-memories.md §View every memory](guide/vault-and-memories.md#view-every-memory-across-every-tag) |

---

## By API route group

Cross-reference matrix: each route group ↔ guide page ↔ behavior
doc ↔ frontend code ↔ test files.

| Group | Guide | Behavior | Frontend | Backend |
|---|---|---|---|---|
| [analytics](api.md#analytics) | [guide/analytics.md](guide/analytics.md) | [BEARINGS_ANALYTICS_v1.md](../BEARINGS_ANALYTICS_v1.md) | `frontend/src/lib/components/analytics/` | `src/bearings/web/routes/analytics.py` |
| [checklists](api.md#checklists), [checklist-items](api.md#checklist-items) | [guide/checklists.md](guide/checklists.md) | [behavior/checklists.md](behavior/checklists.md) | `frontend/src/lib/components/checklist/` | `src/bearings/web/routes/checklists.py` · `src/bearings/agent/auto_driver.py` · `src/bearings/agent/sentinel.py` |
| [checkpoints](api.md#checkpoints) | [guide/sessions.md §Fork](guide/sessions.md#fork-a-session-from-a-specific-message) | (no dedicated behavior doc — see chat.md) | `frontend/src/lib/components/conversation/` | `src/bearings/web/routes/checkpoints.py` |
| [commands](api.md#commands) | (slash-command palette) | [behavior/chat.md](behavior/chat.md) | `frontend/src/lib/components/composer/` | `src/bearings/web/routes/commands.py` |
| [diag](api.md#diag) | (operator surface) | (probe scripts) | — | `src/bearings/web/routes/diag.py` |
| [fs](api.md#fs) | (FS picker in dialogs) | — | `frontend/src/lib/components/common/` | `src/bearings/web/routes/fs.py` |
| [health](api.md#health) | (probe surface) | — | — | `src/bearings/web/routes/health.py` |
| [history](api.md#history) | (`.bearings/history.jsonl`) | [behavior/bearings-cli.md](behavior/bearings-cli.md) | — | `src/bearings/web/routes/history.py` · `src/bearings/web/routes/search.py` |
| [import](api.md#import) | [guide/settings.md §Data import](guide/settings.md#data-import-section) | — | `frontend/src/lib/components/sidebar/` | `src/bearings/web/routes/import_db.py` |
| [memories](api.md#memories) | [guide/vault-and-memories.md](guide/vault-and-memories.md) | [behavior/memories.md](behavior/memories.md) | `frontend/src/lib/components/memories/` | `src/bearings/web/routes/memories.py` |
| [messages](api.md#messages) | [guide/sessions.md](guide/sessions.md) | [behavior/chat.md](behavior/chat.md) | `frontend/src/lib/components/conversation/` | `src/bearings/web/routes/messages.py` |
| [metrics](api.md#metrics) | (Prometheus scrape) | — | — | `src/bearings/web/routes/metrics.py` · `src/bearings/metrics/` |
| [pending](api.md#pending) | [guide/cli.md §`bearings pending`](guide/cli.md#bearings-pending) | [behavior/bearings-cli.md](behavior/bearings-cli.md) | `frontend/src/lib/components/pending/` | `src/bearings/web/routes/pending.py` |
| [preferences](api.md#preferences) | [guide/settings.md](guide/settings.md) | [behavior/preferences.md](behavior/preferences.md) | `frontend/src/lib/components/settings/` | `src/bearings/web/routes/preferences.py` |
| [quota](api.md#quota) | [guide/routing.md](guide/routing.md) | [behavior/routing.md §Quota guard](behavior/routing.md) | `frontend/src/lib/components/routing/` | `src/bearings/web/routes/quota.py` · `src/bearings/agent/quota.py` |
| [routing](api.md#routing) | [guide/routing.md](guide/routing.md) | [behavior/routing.md](behavior/routing.md) | `frontend/src/lib/components/routing/` | `src/bearings/web/routes/routing.py` · `src/bearings/agent/routing.py` |
| [sessions](api.md#sessions) | [guide/sessions.md](guide/sessions.md) | [behavior/sessions.md](behavior/sessions.md) · [behavior/chat.md](behavior/chat.md) · [behavior/prompt-endpoint.md](behavior/prompt-endpoint.md) | `frontend/src/lib/components/sidebar/` · `frontend/src/lib/components/conversation/` | `src/bearings/web/routes/sessions.py` · `src/bearings/web/routes/sessions_bulk.py` · `src/bearings/web/routes/spawn_from_reply.py` · `src/bearings/web/routes/reorg.py` |
| [shell](api.md#shell) | (external editor / file manager dispatch) | — | — | `src/bearings/web/routes/shell.py` |
| [tags](api.md#tags), [tag-groups](api.md#tag-groups) | [guide/settings.md §Tags page](guide/settings.md#tags-page-separate-route) | [behavior/sessions.md §Tag](behavior/sessions.md) | `frontend/src/routes/tags/` | `src/bearings/web/routes/tags.py` |
| [templates](api.md#templates) | [guide/sessions.md §Save as template](guide/sessions.md#save-a-session-as-a-template) | — | `frontend/src/lib/components/new_session/` | `src/bearings/web/routes/templates.py` |
| [uploads](api.md#uploads) | [guide/cli.md §`bearings gc`](guide/cli.md#bearings-gc-uploads) | (uploads via composer) | `frontend/src/lib/components/composer/` | `src/bearings/web/routes/uploads.py` |
| [usage](api.md#usage) | [guide/inspector.md §Usage tab](guide/inspector.md#usage-tab) · [guide/analytics.md](guide/analytics.md) | [behavior/routing.md](behavior/routing.md) | `frontend/src/lib/components/inspector/` | `src/bearings/web/routes/usage.py` |
| [vault](api.md#vault) | [guide/vault-and-memories.md](guide/vault-and-memories.md) | [behavior/vault.md](behavior/vault.md) | `frontend/src/lib/components/vault/` | `src/bearings/web/routes/vault.py` |

---

## By code package

| Package | Architecture anchor | Purpose | Behavior touch |
|---|---|---|---|
| `bearings.cli` | [§1.1.1](architecture-v1.md#111-bearingscli--entrypoint-surface) | Typer CLI surface (`serve` / `gc` / `todo`; planned `init` / `window` / `send` / `here` / `pending`) | [behavior/bearings-cli.md](behavior/bearings-cli.md) |
| `bearings.config` | [§1.1.2](architecture-v1.md#112-bearingsconfig--configuration--named-constants) | `Settings` tree + `Final[…]` named constants. Every spec-mandated number lives here. | (no observable doc — internal) |
| `bearings.db` | [§1.1.3](architecture-v1.md#113-bearingsdb--schema--per-concern-queries) | `schema.sql` + per-resource queries. aiosqlite, no ORM. | (consumed by every behavior doc indirectly) |
| `bearings.agent` | [§1.1.4](architecture-v1.md#114-bearingsagent--domain-layer) | SDK loop, runner, routing, quota, override aggregator, MCP server, autonomous driver, sentinels. | [behavior/chat.md](behavior/chat.md) · [behavior/routing.md](behavior/routing.md) · [behavior/checklists.md](behavior/checklists.md) · [behavior/tool-output-streaming.md](behavior/tool-output-streaming.md) · [behavior/prompt-endpoint.md](behavior/prompt-endpoint.md) |
| `bearings.web` | [§1.1.5](architecture-v1.md#115-bearingsweb--httpws-surface) | FastAPI app + `routes/` + `models/` + `ws/` + static-bundle serve. | All HTTP surfaces — see [api.md](api.md). |
| `bearings.bearings_dir` | [§1.1.6](architecture-v1.md#116-bearingsbearings_dir--directory-context-contract) | `.bearings/` directory contract (manifest / state / pending / onboarding). | [behavior/bearings-cli.md](behavior/bearings-cli.md) |
| `bearings.metrics` | [§1.1.7](architecture-v1.md#117-bearingsmetrics--prometheus--telemetry) | Prometheus exposition. | (operator-facing) |
| `bearings.migrations` | (one-shot v0.17→v0.18 cutover) | One-shot DB cutover. | — |

---

## By frontend route

| Route | Page | Guide | Behavior | Components |
|---|---|---|---|---|
| `/` | sidebar + landing | [guide/getting-started.md](guide/getting-started.md) | [behavior/sessions.md](behavior/sessions.md) | `frontend/src/routes/+layout.svelte` |
| `/sessions/[id]` | conversation pane | [guide/sessions.md](guide/sessions.md) | [behavior/chat.md](behavior/chat.md) | `frontend/src/lib/components/conversation/` · `inspector/` · `composer/` |
| `/sessions/new` | new-session dialog | [guide/sessions.md §Creating](guide/sessions.md#creating-a-session) | [behavior/sessions.md](behavior/sessions.md) · [behavior/routing.md](behavior/routing.md) | `frontend/src/lib/components/new_session/` |
| `/tags` | tag manager | [guide/settings.md §Tags page](guide/settings.md#tags-page-separate-route) | [behavior/sessions.md §Tag](behavior/sessions.md) | `frontend/src/routes/tags/` |
| `/memories` | global memories index | [guide/vault-and-memories.md](guide/vault-and-memories.md) | [behavior/memories.md](behavior/memories.md) | `frontend/src/lib/components/memories/` |
| `/vault` | vault browser | [guide/vault-and-memories.md](guide/vault-and-memories.md) | [behavior/vault.md](behavior/vault.md) | `frontend/src/lib/components/vault/` |
| `/analytics` | analytics page | [guide/analytics.md](guide/analytics.md) | [BEARINGS_ANALYTICS_v1.md](../BEARINGS_ANALYTICS_v1.md) | `frontend/src/lib/components/analytics/` |
| `/settings` | settings shell | [guide/settings.md](guide/settings.md) | [behavior/preferences.md](behavior/preferences.md) | `frontend/src/lib/components/settings/` |

Modal surfaces (no dedicated route): `SessionEdit`,
`SessionImport`, `MultiSelectTagPicker`, approval modal, ask-user
modal — see [behavior/modals.md](behavior/modals.md).

---

## By behavior topic

The full reference layer for observable behavior. Sixteen files
under [behavior/](behavior/):

| Topic | File | Cross-ref to guide |
|---|---|---|
| Bearings CLI | [behavior/bearings-cli.md](behavior/bearings-cli.md) | [guide/cli.md](guide/cli.md) |
| Chat conversation pane | [behavior/chat.md](behavior/chat.md) | [guide/sessions.md](guide/sessions.md) · [guide/inspector.md](guide/inspector.md) |
| Checklists + autonomous driver | [behavior/checklists.md](behavior/checklists.md) | [guide/checklists.md](guide/checklists.md) |
| Context menus | [behavior/context-menus.md](behavior/context-menus.md) | [guide/sessions.md](guide/sessions.md) (right-click flows) |
| Keyboard shortcuts | [behavior/keyboard-shortcuts.md](behavior/keyboard-shortcuts.md) | [guide/settings.md §Help](guide/settings.md#help-section) |
| Memories | [behavior/memories.md](behavior/memories.md) | [guide/vault-and-memories.md](guide/vault-and-memories.md) |
| Modals | [behavior/modals.md](behavior/modals.md) | [guide/sessions.md](guide/sessions.md) (SessionEdit, Import) |
| Paired chats | [behavior/paired-chats.md](behavior/paired-chats.md) | [guide/paired-chats.md](guide/paired-chats.md) |
| Preferences + settings shell | [behavior/preferences.md](behavior/preferences.md) | [guide/settings.md](guide/settings.md) |
| Prompt endpoint | [behavior/prompt-endpoint.md](behavior/prompt-endpoint.md) | [api.md §sessions](api.md#sessions) |
| Routing | [behavior/routing.md](behavior/routing.md) | [guide/routing.md](guide/routing.md) |
| Sessions (lifecycle, import/export, bulk) | [behavior/sessions.md](behavior/sessions.md) | [guide/sessions.md](guide/sessions.md) |
| Themes | [behavior/themes.md](behavior/themes.md) | [guide/settings.md §Appearance](guide/settings.md#appearance-section) |
| Tool-output streaming | [behavior/tool-output-streaming.md](behavior/tool-output-streaming.md) | [guide/getting-started.md §5](guide/getting-started.md#5-send-a-message) |
| Vault | [behavior/vault.md](behavior/vault.md) | [guide/vault-and-memories.md](guide/vault-and-memories.md) |
| Issue triage (operator) | [dogfood/issue-triage.md](dogfood/issue-triage.md) | (operator-facing) |
| Deprecation convention | [deprecation-convention.md](deprecation-convention.md) | (contributor-facing) |

---

## See also (out-of-tree)

* [`../README.md`](../README.md) — repo-level reader-facing
  README. Points back at this index.
* [`../CLAUDE.md`](../CLAUDE.md) — the Bearings v1 agent contract:
  branch invariants, quality gates, the OpenAPI regeneration
  recipe, the reference-read protocol.
* [`../CHANGELOG.md`](../CHANGELOG.md) — release history.
* [`../TODO.md`](../TODO.md) — deferred / orphaned work.
* [`../V1_FEATURE_AUDIT.md`](../V1_FEATURE_AUDIT.md) — historical
  ship-blocker register; cited from concepts.md as a footnote.
* [`../UI_AUDIT.md`](../UI_AUDIT.md),
  [`../BEARINGS_ANALYTICS_v1.md`](../BEARINGS_ANALYTICS_v1.md) —
  feature-area audits / specs at the repo root.
