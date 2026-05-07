/**
 * Frontend constants — every magic literal the UI references lives
 * here so a coding-standards review can audit "no inline literals" by
 * grepping for the imported names rather than chasing duplication.
 *
 * The names mirror :mod:`bearings.config.constants` on the backend
 * where the meaning is shared (e.g. session-kind alphabet); the values
 * are duplicated rather than synced because the backend module is
 * Python-only. A drift between the two surfaces is a behavioural bug
 * caught by the backend's :data:`KNOWN_SESSION_KINDS` validator the
 * first time a session of an unknown kind reaches the route.
 */

// ---- API endpoints ---------------------------------------------------------

/** Base path for FastAPI routes; vite.config proxies this to port 8788 in dev. */
export const API_BASE = "/api";

/** ``GET /api/sessions`` — sidebar list source per ``docs/behavior/chat.md``. */
export const API_SESSIONS_ENDPOINT = `${API_BASE}/sessions`;

/** ``GET /api/tags`` — tag list source per ``docs/behavior/chat.md`` §"creates a chat". */
export const API_TAGS_ENDPOINT = `${API_BASE}/tags`;

/** ``GET /api/sessions/{id}/tags`` — per-session tag list. */
export const sessionTagsEndpoint = (sessionId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/tags`;

/**
 * ``GET /api/checklists/{id}`` — bundled overview (items + active run)
 * per :func:`bearings.web.routes.checklists.get_overview`. The
 * ChecklistView (item 2.7) reads this on mount + re-reads while a run
 * is live so the status line ticks per ``docs/behavior/checklists.md``
 * §"Run-control surface".
 */
export const apiChecklistEndpoint = (checklistId: string): string =>
  `${API_BASE}/checklists/${encodeURIComponent(checklistId)}`;

/** ``POST /api/checklists/{id}/items`` — create a new item. */
export const apiChecklistItemsEndpoint = (checklistId: string): string =>
  `${apiChecklistEndpoint(checklistId)}/items`;

/**
 * ``…/api/checklist-items/{id}`` — base path for the per-item routes.
 * Subpaths the client appends: ``/check``, ``/uncheck``, ``/block``,
 * ``/unblock``, ``/link``, ``/unlink``, ``/legs``, ``/move``,
 * ``/indent``, ``/outdent``, ``/spawn-chat`` (item 1.7's paired-chat
 * spawn route).
 */
export const apiChecklistItemEndpoint = (itemId: number): string =>
  `${API_BASE}/checklist-items/${itemId}`;

/**
 * ``…/api/checklists/{id}/run`` — base path for run-control routes:
 * ``/start``, ``/stop``, ``/pause``, ``/resume``, ``/skip-current``,
 * ``/status``.
 */
export const apiChecklistRunEndpoint = (checklistId: string): string =>
  `${apiChecklistEndpoint(checklistId)}/run`;

/**
 * ``GET /api/sessions/{id}/messages`` — per-session transcript fetch
 * surface (item 1.9; ``src/bearings/web/routes/messages.py``). The
 * SvelteKit client reads it once on session-select to hydrate the
 * conversation pane with the persisted history; live deltas arrive
 * over the WebSocket below.
 */
export const sessionMessagesEndpoint = (sessionId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/messages`;

/** ``GET /api/messages/{id}`` — single-row fetch (inspector "Why this model?"). */
export const messageEndpoint = (messageId: string): string =>
  `${API_BASE}/messages/${encodeURIComponent(messageId)}`;

/** ``PATCH /api/messages/{id}/pinned`` — pin or unpin a message bubble (G3). */
export const messagePinnedEndpoint = (messageId: string): string =>
  `${messageEndpoint(messageId)}/pinned`;

/** ``PATCH /api/messages/{id}/hidden`` — hide or show a message from context (G3). */
export const messageHiddenEndpoint = (messageId: string): string =>
  `${messageEndpoint(messageId)}/hidden`;

/** ``DELETE /api/messages/{id}`` — delete a message (G3). */
export const messageDeleteEndpoint = (messageId: string): string => messageEndpoint(messageId);

/** ``POST /api/messages/{id}/move`` — re-parent a message to another session (G3). */
export const messageMoveEndpoint = (messageId: string): string =>
  `${messageEndpoint(messageId)}/move`;

/**
 * ``POST /api/sessions/{parentId}/spawn_from_reply/{messageId}``
 * (gap-cycle-03-007). Creates a paired chat seeded with a blockquote
 * of the clicked assistant message.
 */
export const spawnFromReplyEndpoint = (parentSessionId: string, messageId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(parentSessionId)}/spawn_from_reply/${encodeURIComponent(messageId)}`;

/**
 * ``POST /api/checkpoints`` / ``GET /api/checkpoints?session_id=...`` (G6).
 * Per ``docs/behavior/chat.md`` §"Slash commands" — the user creates
 * checkpoints intentionally; the gutter chip renders the list.
 */
export const API_CHECKPOINTS_ENDPOINT = `${API_BASE}/checkpoints`;

/** ``DELETE /api/checkpoints/{id}`` — delete one checkpoint (G6). */
export const checkpointEndpoint = (checkpointId: string): string =>
  `${API_BASE}/checkpoints/${encodeURIComponent(checkpointId)}`;

/**
 * ``POST /api/checkpoints/{id}/fork`` — clone the source session +
 * copy messages up to & including the anchor into a new session (G6).
 * Per ``docs/behavior/context-menus.md`` §"Checkpoint (gutter chip)"
 * the primary action on a checkpoint is ``checkpoint.fork``.
 */
export const checkpointForkEndpoint = (checkpointId: string): string =>
  `${checkpointEndpoint(checkpointId)}/fork`;

/**
 * ``GET /api/templates`` — list all templates alphabetically (G7).
 * ``POST /api/templates`` — create a new template (G7).
 */
export const API_TEMPLATES_ENDPOINT = `${API_BASE}/templates`;

/** ``GET / PATCH / DELETE /api/templates/{id}`` — single template (G7). */
export const templateEndpoint = (templateId: number): string =>
  `${API_BASE}/templates/${templateId}`;

/**
 * ``POST /api/sessions/{id}/prompt`` — composer submit surface per
 * ``docs/behavior/prompt-endpoint.md``. Body shape: ``{ content: str }``;
 * 202 Accepted ack body: ``{ queued: bool, session_id: str }``.
 */
export const sessionPromptEndpoint = (sessionId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/prompt`;

/**
 * ``POST /api/sessions/{id}/approvals/{request_id}`` — resolve a
 * pending ``can_use_tool`` approval (Slice A4). Body shape:
 * ``{ approved: bool, answer?: str }``. 204 No Content on success.
 */
export const sessionApprovalEndpoint = (sessionId: string, requestId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/approvals/${encodeURIComponent(requestId)}`;

/**
 * ``POST /api/sessions/{id}/stop`` — cancel the current in-flight turn.
 * Returns 204 No Content on success.
 */
export const sessionStopEndpoint = (sessionId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/stop`;

/**
 * ``PATCH /api/sessions/{id}/model`` — swap the executor model mid-session
 * (spec §7). The server persists the new model and recycles the live SDK
 * supervisor; the next prompt re-spawns with ``--model <new>``.
 */
export const sessionModelEndpoint = (sessionId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/model`;

/**
 * ``POST /api/sessions/{src}/reorg/merge?target={dst}`` — merge src
 * into dst (gap-cycle-03-008).
 */
export const sessionReorgMergeEndpoint = (srcId: string, dstId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(srcId)}/reorg/merge?target=${encodeURIComponent(dstId)}`;

/**
 * ``GET /api/sessions/{id}/reorg/audits`` — list persistent merge-audit
 * rows for a destination session (gap-cycle-03-009).
 */
export const sessionReorgAuditsEndpoint = (sessionId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/reorg/audits`;

/**
 * ``DELETE /api/sessions/{id}/reorg/audits/{auditId}`` — undo a merge
 * operation and remove its audit row (gap-cycle-03-009).
 */
export const sessionReorgAuditEndpoint = (sessionId: string, auditId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/reorg/audits/${encodeURIComponent(auditId)}`;

/**
 * ``GET /api/sessions/{id}/tool_calls`` — persisted tool-call rows for
 * one or more assistant message ids (gap-cycle-03-012). Accepts repeated
 * ``?message_ids=ID`` query params to narrow the result to a specific
 * page of messages. The conversation pane calls this alongside
 * :func:`listMessages` on session-open so drawer rows are visible even
 * when the ring buffer no longer holds the original streaming events.
 */
export const sessionToolCallsEndpoint = (sessionId: string): string =>
  `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/tool_calls`;

/**
 * ``GET /api/commands`` — slash-command list for the composer typeahead
 * (item 2.3). No session scoping — the scanner merges user + project
 * locations server-side.
 */
export const API_COMMANDS_ENDPOINT = `${API_BASE}/commands`;

/**
 * ``GET /api/preferences`` + ``PATCH /api/preferences`` — singleton
 * user-preferences row (item 3.2).
 */
export const API_PREFERENCES_ENDPOINT = `${API_BASE}/preferences`;

/**
 * ``GET/POST/DELETE /api/preferences/avatar`` — serve / upload / remove the
 * user's profile avatar (gap-cycle-03-011).
 */
export const API_PREFERENCES_AVATAR_ENDPOINT = `${API_BASE}/preferences/avatar`;

/**
 * ``POST /api/preferences/sync_from_system`` — populate display_name from
 * ``$USER`` and avatar from ``~/.face`` (gap-cycle-03-011).
 */
export const API_PREFERENCES_SYNC_ENDPOINT = `${API_BASE}/preferences/sync_from_system`;

/**
 * ``POST /api/import/bearings`` — import all data from the original
 * Bearings database into Bearings-v1. Copies sessions, messages, tags,
 * and related data. Rows with duplicate IDs are skipped.
 */
export const API_IMPORT_BEARINGS_ENDPOINT = `${API_BASE}/import/bearings`;

/**
 * ``GET /api/history/search?q=<term>`` — full-text search over sessions
 * and messages (item 2.4).
 */
export const API_HISTORY_SEARCH_ENDPOINT = `${API_BASE}/history/search`;

/**
 * Debounce window (ms) for the sidebar search input. Mirrors
 * :data:`bearings.config.constants.HISTORY_SEARCH_DEBOUNCE_MS`.
 */
export const HISTORY_SEARCH_DEBOUNCE_MS = 300;

/**
 * UI strings for the sidebar search overlay (item 2.4).
 */
export const SIDEBAR_SEARCH_STRINGS = {
  placeholder: "Search sessions and messages…",
  ariaLabel: "Search sessions and messages",
  closeLabel: "Close search",
  emptyResults: "No results.",
  loadingLabel: "Searching…",
  sessionKindLabel: "session",
  messageKindLabel: "message",
} as const;

/**
 * Hard cap on a single prompt submission, mirroring the backend's
 * :data:`bearings.config.constants.PROMPT_CONTENT_MAX_CHARS` (64 000).
 * The Composer enforces this client-side so the user gets immediate
 * feedback rather than a 422 round-trip.
 */
export const PROMPT_CONTENT_MAX_CHARS = 64_000;

/**
 * ``POST /api/routing/preview`` — new-session dialog's reactive
 * routing preview surface (spec §6 + §9). Body shape: ``{ tags:
 * int[], message: str }``; response shape: ``RoutingPreviewOut`` per
 * ``src/bearings/web/models/routing.py`` mirrored on
 * :interface:`RoutingPreview` in ``api/routing.ts``.
 */
export const API_ROUTING_PREVIEW_ENDPOINT = `${API_BASE}/routing/preview`;

/**
 * ``GET /api/quota/current`` — latest snapshot for the in-dialog
 * QuotaBars (spec §8 / §9 + §10 "Quota bars in the session header").
 * Response shape mirrored on :interface:`QuotaSnapshot` in
 * ``api/quota.ts``.
 */
export const API_QUOTA_CURRENT_ENDPOINT = `${API_BASE}/quota/current`;

/**
 * ``GET /api/quota/history?days=7`` — rolling-window quota snapshots
 * for the InspectorUsage "Headroom remaining" chart (spec §7
 * "Quota efficiency" + §10 "Headroom remaining chart"). Response
 * shape: ``QuotaSnapshot[]`` (oldest-first per
 * :func:`bearings.web.routes.quota.get_history`).
 */
export const API_QUOTA_HISTORY_ENDPOINT = `${API_BASE}/quota/history`;

/**
 * ``GET /api/usage/by_model?period=week`` — InspectorUsage by-model
 * table source (spec §7 "Quota efficiency" + §10 "By model table").
 * Response shape: ``UsageByModelRow[]`` per
 * :class:`bearings.web.models.usage.UsageByModelRow`, mirrored on
 * :interface:`UsageByModelRow` in ``api/usage.ts``.
 */
export const API_USAGE_BY_MODEL_ENDPOINT = `${API_BASE}/usage/by_model`;

/**
 * ``GET /api/usage/override_rates?days=14`` — InspectorUsage
 * "Rules to review" source (spec §8 "Override-rate calculation"
 * + §10 "Rules to review list" — rules with override rate > 30 %
 * over the last 14 days). Mirrored on :interface:`OverrideRateOut`
 * in ``api/usage.ts``.
 */
export const API_USAGE_OVERRIDE_RATES_ENDPOINT = `${API_BASE}/usage/override_rates`;

/**
 * ``GET /api/diag/server`` — server diagnostics including the Bearings
 * version string. Fetched lazily by :func:`feedback.fetchVersion` on
 * the first feedback-button click (gap-cycle-01-008). Response shape:
 * :class:`bearings.web.models.diag.ServerDiagOut`.
 */
export const API_DIAG_SERVER_ENDPOINT = `${API_BASE}/diag/server`;

/**
 * ``GET /api/vault`` — bucketed list of plans + todos per
 * ``docs/behavior/vault.md`` §"When the user opens the vault". Re-scans
 * the filesystem on every request (vault.md §"Failure modes" — "Stale
 * mtime"). Item 1.5 (``src/bearings/web/routes/vault.py``).
 */
export const API_VAULT_ENDPOINT = `${API_BASE}/vault`;

/**
 * ``GET /api/vault/search?q=...`` — case-insensitive substring search
 * across every vault doc (vault.md §"Search semantics"). Mirrored on
 * :interface:`SearchResult` in ``api/vault.ts``.
 */
export const API_VAULT_SEARCH_ENDPOINT = `${API_BASE}/vault/search`;

/**
 * ``GET /api/vault/by-path?path=...`` — open one doc by absolute path;
 * the linkifier handler dispatches here when a chat message body
 * references a vault path (vault.md §"Tag association" — "When a vault
 * doc's path appears inside a chat message body … the linkifier
 * renders it as a clickable anchor. Clicking the anchor opens the doc
 * in the vault pane in-place").
 */
export const API_VAULT_BY_PATH_ENDPOINT = `${API_BASE}/vault/by-path`;

/**
 * ``GET /api/vault/{id}`` — open one doc by cache id. The vault list
 * surface uses this to fetch the body + redaction ranges when a row is
 * selected (vault.md §"When the user opens the vault" — "Selecting a
 * row opens the doc in a reading panel").
 */
export const vaultDocEndpoint = (vaultId: number): string => `${API_BASE}/vault/${vaultId}`;

/**
 * ``…/api/tags/{tag_id}/memories`` — base path for memory CRUD scoped
 * to one tag (item 1.4; ``src/bearings/web/routes/memories.py``).
 * GET returns the per-tag list (with optional ``?only_enabled=true``
 * filter for the prompt-assembler consumer); POST creates a new
 * memory under the tag. Per-doc folded behavior (chat.md +
 * checklists.md + vault.md silent on the editor surface itself,
 * arch §1.1.3 — "tag memories as system-prompt fragments").
 */
export const tagMemoriesEndpoint = (tagId: number): string =>
  `${API_TAGS_ENDPOINT}/${tagId}/memories`;

/**
 * ``…/api/memories/{id}`` — direct addressable surface for a single
 * memory (GET / PATCH / DELETE). The dual-surface (per-tag + direct)
 * matches v0.17.x's UI which shows the editor in two places — inside
 * the per-tag panel and as a flat list.
 */
export const memoryEndpoint = (memoryId: number): string => `${API_BASE}/memories/${memoryId}`;

// ---- WebSocket streaming surface ------------------------------------------

/**
 * Per-session WebSocket path the runtime fans out
 * :class:`bearings.agent.events.AgentEvent` frames over (item 1.2;
 * ``src/bearings/web/streaming.py``). Vite's dev proxy forwards
 * ``/ws/*`` to the FastAPI backend on the configured port.
 */
export const sessionStreamPath = (sessionId: string): string =>
  `/ws/sessions/${encodeURIComponent(sessionId)}`;

/**
 * Resume cursor parameter — mirrors :data:`bearings.web.streaming.SINCE_SEQ_QUERY_PARAM`.
 * The reconnect path appends ``?since_seq=<n>`` so the server replays
 * everything past ``n`` from its ring buffer per
 * ``docs/behavior/tool-output-streaming.md`` §"Reconnect / replay".
 */
export const WS_SINCE_SEQ_QUERY_PARAM = "since_seq";

/**
 * Frame ``kind`` values mirror :data:`bearings.web.serialize.FRAME_KIND_*`.
 * The discriminator literal a parsed envelope carries — used by
 * :func:`parseStreamFrame` in ``api/streaming.ts`` to dispatch to the
 * event vs heartbeat branch without re-deciding spelling at the call
 * site.
 */
export const WS_FRAME_KIND_EVENT = "event";
export const WS_FRAME_KIND_HEARTBEAT = "heartbeat";

/**
 * Sessions-broadcast WebSocket path (item 2.6).
 * Mirrors ``/ws/sessions`` in
 * :func:`bearings.web.routes.ws_sessions.sessions_broadcast_ws`.
 */
export const WS_SESSIONS_PATH = "/ws/sessions";

/**
 * WebSocket close code emitted by the backend when authentication fails
 * or the session token has expired. When the sessions-broadcast socket
 * closes with this code, ``BackendStatusBanner`` stays hidden so the
 * banner does not double-up with the AuthGate UI.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Error states" "Auth required".
 */
export const WS_CLOSE_CODE_AUTH_FAILURE = 4401;

/**
 * Duration (ms) a WebSocket disconnect must persist before the
 * ``BackendStatusBanner`` becomes visible.
 *
 * The grace period suppresses the banner during brief blips (routine
 * server restarts, transient network hiccups) so the UI does not flash
 * "Backend unreachable" on every fast reconnect.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Error states"
 * "Backend unreachable".
 */
export const BACKEND_UNREACHABLE_THRESHOLD_MS = 5_000;

// ---- Session-kind alphabet (mirrors backend ``KNOWN_SESSION_KINDS``) ------

/** Chat-kind session — composer + transcript per ``docs/behavior/chat.md``. */
export const SESSION_KIND_CHAT = "chat";

/** Checklist-kind session — structured-list pane per ``docs/behavior/checklists.md``. */
export const SESSION_KIND_CHECKLIST = "checklist";

/** The full alphabet; iterated by the kind-indicator helper below. */
export const KNOWN_SESSION_KINDS = [SESSION_KIND_CHAT, SESSION_KIND_CHECKLIST] as const;

export type SessionKind = (typeof KNOWN_SESSION_KINDS)[number];

// ---- Tag conventions (mirrors backend ``TAG_GROUP_SEPARATOR``) ------------

/**
 * Slash-namespace separator on tag names — ``bearings/architect`` →
 * group ``bearings``, leaf ``architect``. Mirrors the backend's
 * :data:`bearings.config.constants.TAG_GROUP_SEPARATOR`.
 */
export const TAG_GROUP_SEPARATOR = "/";

// ---- UI strings ------------------------------------------------------------

/**
 * UI string table — pulled out of components per coding-standards
 * §"i18n-ready string tables". A future locale layer can swap the
 * record's values without touching component bodies. Keys are stable
 * identifiers; values are the English presentation strings.
 */
/**
 * Conversation-pane string table — chat.md §"opens an existing chat"
 * + §"What a message turn looks like" presentation strings, factored
 * out of components per coding-standards "i18n-ready string tables".
 */
export const CONVERSATION_STRINGS = {
  emptyTranscript: "No messages yet. Send one to start the turn.",
  loadingTranscript: "Loading conversation…",
  loadFailed: "Couldn't load the transcript.",
  toolDrawerLabel: "Tool calls",
  toolDrawerOpenLabel: "Open tool calls",
  toolDrawerCloseLabel: "Close tool calls",
  toolDrawerJumpLabel: "⤴ TOOLS",
  toolStatusOk: "Completed",
  toolStatusError: "Failed",
  toolStatusRunning: "Running",
  toolOutputExpand: "Show full output",
  toolOutputCollapse: "Collapse output",
  // Behavior doc §"Very-long-output truncation rules" — wording mirrors
  // backend STREAM_TRUNCATION_MARKER_TEMPLATE for visual consistency.
  truncationLabel: "[truncated — more bytes elided]",
  routingBadgeTooltipFallback: "Routing reason unavailable",
  pairedChatBreadcrumbPrefix: "↳",
  pairedChatBreadcrumbDeleted: "(checklist deleted)",
  pairedChatBreadcrumbAriaLabel: "Paired checklist breadcrumb",
  errorBubbleLabel: "Error",
  scrollToBottomLabel: "↓ Jump to bottom",
  stopTurnLabel: "■ Stop",
  stopTurnAriaLabel: "Stop the current turn",
  // Item 1.3 pagination affordance.
  loadOlderLabel: "Load older messages",
  loadingOlder: "Loading…",
  // Item 1.4 turn_replayed annotation — user row inline badge.
  turnResumedLabel: "↻ resumed",
  // Phase 1 conversation UX
  reopenSessionLabel: "Reopen session",
  errorHintLabel: "Try sending a new message to continue.",
  askForMoreDetailLabel: "Ask for more detail",
  askForMoreDetailPrompt: "Can you expand on that in more detail?",
  // gap-cycle-03-007 — spawn-from-reply pill label on assistant bubbles.
  spawnPillLabel: "＋ SPAWN",
  spawnPillAriaLabel: "Spawn a new chat from this reply",
  // Phase 4 error recovery
  recoverLabel: "Recover",
  recoveringLabel: "Recovering…",
} as const;

/**
 * String table for the sent-attachment chips row on a user bubble
 * (gap-cycle-01-015). Centralised here per coding-standards §"i18n-ready
 * string tables".
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"What a message turn looks
 * like" — attachment chips at the bottom of the user bubble.
 */
export const SENT_ATTACHMENT_STRINGS = {
  chipsAreaAriaLabel: "Attached files",
} as const;

/**
 * Height threshold (px) above which ``CollapsibleBody`` clamps content
 * and shows the fold affordance (gap-cycle-01-010).
 *
 * A comfortable reading height that prevents a single long turn from
 * dominating the viewport. Anchored to
 * ``docs/behavior/chat.md`` §"CollapsibleBody".
 */
export const COLLAPSIBLE_BODY_THRESHOLD_PX = 320;

/**
 * Pixel height of the CSS ``mask-image`` fade zone at the bottom of a
 * folded ``CollapsibleBody`` (gap-cycle-01-010). Matches v0.17.x
 * observable behavior.
 */
export const COLLAPSIBLE_BODY_FADE_PX = 64;

/**
 * String table for the ``CollapsibleBody`` fold affordance.
 *
 * Centralised here per coding-standards "i18n-ready string tables".
 * Anchored to ``docs/behavior/chat.md`` §"CollapsibleBody".
 */
export const COLLAPSIBLE_BODY_STRINGS = {
  showFull: "Show full",
  collapse: "Collapse",
} as const;

/**
 * Global command palette strings (Phase 5).
 * Anchored to ``docs/behavior/keyboard-shortcuts.md`` §"Command palette".
 */
export const COMMAND_PALETTE_STRINGS = {
  title: "Command palette",
  ariaLabel: "Global command palette",
  searchPlaceholder: "Search actions…",
  closeLabel: "Close",
  noResults: "No actions match",
} as const;

/**
 * String table for the live todos panel (item 2.1).
 *
 * Centralised here so the component stays logic-only and any
 * copy changes happen in one place.
 */
export const LIVE_TODOS_STRINGS = {
  panelLabel: "Todos",
  panelCollapseAriaLabel: "Collapse todos panel",
  panelExpandAriaLabel: "Expand todos panel",
  emptyLabel: "No active todos",
  statusCompleted: "completed",
  statusInProgress: "in progress",
  statusPending: "pending",
  priorityHigh: "high",
  priorityMedium: "medium",
  priorityLow: "low",
} as const;

/**
 * Soft display cap on a single tool-call's body. Behavior doc
 * (``docs/behavior/tool-output-streaming.md`` §"Very-long-output
 * truncation rules") prescribes a soft cap that folds the middle
 * inside an inline expander while keeping head/tail bookends visible.
 * Mirrors the backend ``DEFAULT_TOOL_OUTPUT_CAP_CHARS`` (8000) so the
 * UI cap and the persistence cap agree by default — a runaway tool
 * past the persistence hard cap (1 MiB) is also past this display
 * cap, so the UI's truncation marker only renders when the persisted
 * body itself is truncated.
 */
export const CHAT_TOOL_OUTPUT_SOFT_CAP_CHARS = 8000;

/**
 * Page size for cursor-based message pagination (item 1.3).
 *
 * Mirrors :data:`bearings.config.constants.MESSAGE_PAGE_SIZE` (100).
 * Session-open fetches the last N messages; each ``loadOlder()`` call
 * walks back N more. 100 rows keeps the initial payload well under the
 * OOM threshold for long-running sessions.
 */
export const MESSAGE_PAGE_SIZE = 100;

/**
 * String table for the subscription token-usage meter (gap-cycle-01-017).
 *
 * Rendered in the conversation header in place of the dollar figure when
 * the server is configured with ``billing.mode = "subscription"``.
 * Colours parallel the quota-bar thresholds (spec §10).
 */
export const TOKEN_METER_STRINGS = {
  ariaLabel: "Session token usage",
  inputLabel: "in",
  outputLabel: "out",
  /** Aria-label for the yellow-threshold warning state. */
  warnAriaLabel: "Approaching quota limit",
  /** Aria-label for the red-threshold danger state. */
  dangerAriaLabel: "Quota nearly exhausted",
} as const;

/**
 * String table for the context/token meter header strip (item 2.2).
 */
export const CONTEXT_METER_STRINGS = {
  ariaLabel: "Context usage meter",
  /** Percentage label suffix shown next to the number. */
  pctSuffix: "%",
  tokensLabel: "tokens",
  cacheLabel: "cache",
  /** Aria label for the warn band that appears near the auto-compact threshold. */
  warnAriaLabel: "Approaching auto-compact threshold",
} as const;

/**
 * Auto-compact warn band: show warning when context is within this many
 * percentage-points of the auto-compact threshold (item 2.2).
 *
 * Example: threshold at 80% capacity → warn when percentage > 65%.
 * When no threshold is set, falls back to warning above
 * ``(100 - CONTEXT_METER_WARN_BAND_PCT)``%.
 */
export const CONTEXT_METER_WARN_BAND_PCT = 15;

/**
 * Per-session WS reconnect ring buffer cap (arch §1.1.2).
 *
 * Mirrors ``RING_BUFFER_MAX`` in ``src/bearings/config/constants.py``
 * (``Final[int] = 5000``). Shown in the AccentCard "Recovery armed"
 * label (gap-cycle-01-019). Must be kept in sync with the backend
 * constant manually — the two modules do not share a config surface.
 */
export const WS_RING_BUFFER_CAP = 5_000;

/**
 * String table for the conversation-level AccentCards strip
 * (gap-cycle-01-019).
 *
 * Two value-add info cards rendered above the message list:
 * - Card 1 (token caching) — "Saved X% tokens — N vs M cached".
 * - Card 2 (WS recovery) — "Recovery armed — Up to 5000 events buffered".
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"AccentCards".
 */
export const ACCENT_CARDS_STRINGS = {
  /** Aria-label for the cards strip wrapper. */
  ariaLabel: "Conversation value-add indicators",
  /** Card 1 — token cache savings. */
  cacheSavedLabel: "Saved",
  cachePctSuffix: "%",
  cacheSavingsLabel: "tokens",
  cacheVsLabel: "vs",
  cacheSuffix: "cached",
  /** Card 2 — WS recovery status. */
  recoveryArmedLabel: "Recovery armed",
  recoveryBufferPrefix: "Up to",
  recoveryBufferSuffix: "events buffered",
} as const;

/**
 * UI string table for the conversation header band (gap-cycle-01-005).
 *
 * Covers: title aria-label, severity shield, tag chips, cost indicator,
 * and the quota-bars heading surfaced by the ``QuotaBars`` sub-component
 * when reused in the header (per spec §10 "Quota bars in the session
 * header"). Pulled out of the component per coding-standards
 * §"i18n-ready string tables".
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"When the user opens an
 * existing chat" — the header band item list.
 */
export const CONVERSATION_HEADER_STRINGS = {
  ariaLabel: "Conversation header",
  /** Aria-label for the severity shield chip. */
  severityShieldAriaLabel: "Severity",
  /** Aria-label wrapper for the non-severity tag chips row. */
  tagChipsAriaLabel: "Attached tags",
  /**
   * Currency prefix for the total-cost indicator (chat.md §"total-cost /
   * context-window indicator" — cost expressed in USD).
   */
  costPrefix: "$",
  /** Aria-label for the total-cost readout span. */
  costAriaLabel: "Total session cost",
} as const;

/**
 * Base URL for the GitHub ``issues/new`` form. The feedback utility
 * (:func:`feedback.buildFeedbackUrl`) appends query-encoded parameters
 * for the issue title, body, and labels. Bearings does not POST any
 * data — the browser opens the form and the user submits manually
 * (Beryndil standards §17 / gap-cycle-01-008).
 */
export const FEEDBACK_GITHUB_ISSUES_URL =
  "https://github.com/Beryndil/Bearings/issues/new";

/**
 * UI strings for :component:`FeedbackButton` (gap-cycle-01-008).
 */
export const FEEDBACK_BUTTON_STRINGS = {
  /** ``aria-label`` on the ``<button>`` element. */
  ariaLabel: "Send feedback",
  /** Tooltip shown on hover (``title`` attribute). */
  tooltip: "Report an issue or send feedback",
} as const;

/**
 * ``rel`` attribute for outbound anchors per chat.md §"Conversation
 * rendering" — "rendered as anchors that open in a new tab with
 * ``noopener noreferrer``". Pulled out of the linkifier so a future
 * security review can grep one place rather than chasing call sites.
 */
export const CHAT_LINK_REL = "noopener noreferrer";

/**
 * Composer copy — surfaced by ``Composer.svelte`` (the chat input
 * footer). Behaviour doc anchor: ``docs/behavior/chat.md``
 * §"Composer & message submission".
 */
export const COMPOSER_STRINGS = {
  textareaAriaLabel: "Message composer",
  textareaPlaceholder:
    "Send a prompt (Enter · Shift+Enter for newline · / for commands · drop files to attach)",
  sendButtonLabel: "Send",
  sendButtonAriaLabel: "Send message",
  sending: "Sending…",
  sendFailed: "Couldn't send the message.",
  sessionClosedHint: "This session is closed — reopen it to send a message.",
} as const;

/**
 * Checkpoint gutter copy (G6) — surfaced by ``CheckpointGutter.svelte``.
 * Behaviour doc anchor: ``docs/behavior/context-menus.md``
 * §"Checkpoint (gutter chip)".
 */
export const CHECKPOINT_GUTTER_STRINGS = {
  gutterAriaLabel: "Checkpoints",
  /** Synthesised label echo when /checkpoint is typed without an argument. */
  defaultLabelHint: "Checkpoint",
  /** Toast / inline status when the checkpoint create call fails. */
  createFailed: "Couldn't create checkpoint.",
  /** Toast when there is no message to anchor a checkpoint at. */
  createNoAnchor: "Checkpoint needs at least one message to anchor.",
} as const;

/** String table for the slash-command typeahead palette (item 2.3). */
export const COMMAND_MENU_STRINGS = {
  ariaLabel: "Slash command menu",
  noResults: "No matching commands",
  sourceLabels: {
    user_commands: "User",
    user_skills: "Skill",
    project_commands: "Project",
  } as Record<string, string>,
} as const;

export const SIDEBAR_STRINGS = {
  heading: "Bearings",
  versionTag: "v1.0.0",
  newSessionLabel: "New Session",
  newSessionAriaLabel: "Start a new session",
  navAriaLabel: "Primary",
  navSessions: "Sessions",
  navTags: "Tags",
  navMemories: "Memories",
  navVault: "Vault",
  navVaultAriaLabel: "Open vault (plans + TODOs)",
  navAnalytics: "Analytics",
  navSettings: "Settings",
  sessionsLabel: "Session list",
  tagFilterLabel: "Filter by tag",
  tagFilterClearLabel: "Clear filter",
  emptySessionList: "No sessions match the current filter.",
  emptySessionListUnfiltered: "No sessions yet.",
  loadingSessions: "Loading sessions…",
  loadFailed: "Couldn't load sessions.",
  ungroupedTagsLabel: "(ungrouped)",
  pinnedIndicatorAriaLabel: "Pinned",
  unviewedDotAriaLabel: "Unviewed",
  closedIndicatorAriaLabel: "Closed",
  errorPendingIndicatorAriaLabel: "Needs attention",
  /** Activity pip — per-row state descriptions (gap-cycle-08-001). */
  activityPipRedAriaLabel: "Awaiting your input",
  activityPipOrangeAriaLabel: "Agent running",
  activityPipGreenAriaLabel: "New output — unviewed",
  closedGroupLabel: "Closed",
  closedToggleExpandLabel: (count: number) => `Closed (${count})`,
  closedToggleAriaExpanded: "Hide closed sessions",
  closedToggleAriaCollapsed: "Show closed sessions",
  reopenButtonLabel: "Reopen",
  reopenButtonAriaLabelTemplate: (title: string) => `Reopen session "${title}"`,
  reopenFailedLabel: "Couldn't reopen — try again.",
  kindIndicatorAriaLabels: {
    [SESSION_KIND_CHAT]: "Chat session",
    [SESSION_KIND_CHECKLIST]: "Checklist session",
  } as const satisfies Record<SessionKind, string>,
  /** Selection bar — shown when ≥1 session is selected via multi-select. */
  multiSelectBarLabel: (count: number) => `${count} session${count === 1 ? "" : "s"} selected`,
  multiSelectBarClearLabel: "Cancel",
  multiSelectBarAriaLabel: "Multi-select actions",
  /** Sort-control toggle (below TagFilterPanel). */
  sortControlAriaLabel: "Session sort order",
  sortLastActionLabel: "Last action",
  sortGroupedLabel: "Grouped",
  /** Sidebar identity block — button aria-label and display-name fallback (gap-cycle-08-002). */
  identityBlockAriaLabel: "Open Settings",
  identityBlockFallbackName: "Operator",
  /** Templates button — sidebar affordance for the template picker (gap-cycle-08-007). */
  templatesButtonLabel: "Templates…",
  templatesButtonAriaLabel: "Open template picker",
} as const;

/**
 * UI strings for the sidebar system-status card (gap-cycle-08-006).
 *
 * The card pins two always-visible health rows at the sidebar bottom
 * (above the identity block) so users dwelling in the sidebar can
 * answer "system OK?" without scanning the full-width status bar.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Sidebar system-status card".
 */
export const SYSTEM_STATUS_CARD_STRINGS = {
  /** ``aria-label`` for the card container. */
  cardAriaLabel: "System status",
  /** Label for the WebSocket connection row. */
  connectionRowLabel: "Connection",
  /** Connection value when WS state is ``'open'``. */
  connectionConnected: "Connected",
  /** Connection value when WS state is ``'closed'`` or ``'error'``. */
  connectionDisconnected: "Disconnected",
  /** Label for the Claude reachability row. */
  claudeRowLabel: "Claude",
  /** Claude-reachability value when WS state is ``'open'``. */
  claudeReachable: "Reachable",
  /** Claude-reachability value when WS state is ``'closed'`` or ``'error'``. */
  claudeUnreachable: "Unreachable",
} as const;

// ---- Routing preview + quota guard tunings --------------------------------

/**
 * Debounce window for the new-session dialog's reactive routing
 * preview (spec §6 — "Typing in the first-message field re-evaluates
 * rules in real time (debounced ~300ms)"). Mirrors the backend's
 * :data:`bearings.config.constants.ROUTING_PREVIEW_DEBOUNCE_MS`
 * (``src/bearings/config/constants.py:65``); value duplicated rather
 * than synced because the backend module is Python-only.
 */
export const ROUTING_PREVIEW_DEBOUNCE_MS = 300;

// ---- Pending operations (gap-cycle-01-004; keyboard-shortcuts §Help) --------

/**
 * ``GET /api/fs/read`` — read a utf-8 file under an allow-root.
 * Used by the pending-ops store to load ``.bearings/pending.toml``
 * for the active session's working directory.
 */
export const API_FS_READ_ENDPOINT = `${API_BASE}/fs/read`;

/**
 * ``GET /api/health`` — server liveness + readiness snapshot. Used by
 * the Settings Privacy section to display the resolved data directory
 * path (gap-cycle-07-003).
 */
export const API_HEALTH_ENDPOINT = `${API_BASE}/health`;

/**
 * ``POST /api/shell/exec`` — dispatch an argv via the backend shell
 * allowlist (``xdg-open`` et al.).  Used by context-menu shell-open
 * actions per ``docs/behavior/context-menus.md`` §"Shell-open
 * integration".
 */
export const API_SHELL_EXEC_ENDPOINT = `${API_BASE}/shell/exec`;

/**
 * ``POST /api/pending/{name}/resolve?directory=<abs>`` — remove the
 * named entry from ``.bearings/pending.toml`` (resolved semantic).
 * Per ``docs/behavior/bearings-cli.md`` §"HTTP action endpoints".
 */
export const pendingResolveEndpoint = (name: string): string =>
  `${API_BASE}/pending/${encodeURIComponent(name)}/resolve`;

/**
 * ``DELETE /api/pending/{name}?directory=<abs>`` — remove the named
 * entry from ``.bearings/pending.toml`` (dismissed semantic).
 * Per ``docs/behavior/bearings-cli.md`` §"HTTP action endpoints".
 */
export const pendingDismissEndpoint = (name: string): string =>
  `${API_BASE}/pending/${encodeURIComponent(name)}`;

/**
 * UI strings for the pending-operations floating card (toggled by
 * ``Ctrl+Shift+O`` per ``docs/behavior/keyboard-shortcuts.md`` §"Help").
 */
export const PENDING_OPS_CARD_STRINGS = {
  cardAriaLabel: "Pending operations",
  cardHeading: "Pending Operations",
  closeLabel: "Close",
  closeAriaLabel: "Close pending operations",
  emptyLabel: "No pending operations.",
  loadingLabel: "Loading…",
  loadErrorLabel: "Couldn't load pending operations.",
  actionErrorLabel: "Action failed — try again.",
  badgeAriaLabel: (count: number) =>
    `${count} pending operation${count === 1 ? "" : "s"} — click to view`,
  ageLabel: (seconds: number): string => {
    if (seconds < 60) return `${seconds}s ago`;
    const m = Math.floor(seconds / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  },
} as const;

// ---- Shell-open notification (gap-cycle-03-002) -----------------------------

/**
 * UI strings for the transient shell-operation error toast
 * (``ShellOpNotification.svelte``).
 */
export const SHELL_OP_NOTIFICATION_STRINGS = {
  /** Prefix prepended before the server ``detail`` message. */
  errorPrefix: "Shell open failed: ",
  dismissAriaLabel: "Dismiss notification",
} as const;

// ---- General-purpose undo toast (gap-cycle-05-002) -------------------------

/**
 * UI strings for the general-purpose undo toast (``UndoToast.svelte``).
 *
 * Action-specific messages (e.g. "Session archived") are plain strings
 * passed directly to ``undoStore.push({ message, inverse })``.  The
 * constants below are the per-action message strings so each call site
 * has a single source of truth.
 */
export const UNDO_TOAST_STRINGS = {
  undoLabel: "Undo",
  undoingLabel: "Undoing…",
  dismissAriaLabel: "Dismiss",
  /** Message shown after session.archive completes. */
  sessionArchived: "Session archived",
  /** Message shown after checkpoint.delete completes. */
  checkpointDeleted: "Checkpoint deleted",
  /** Message shown after tag_chip.detach completes. */
  tagRemoved: "Tag removed",
  /** Message shown after multi_select.close completes. */
  sessionsArchived: (count: number) => `${count} session${count === 1 ? "" : "s"} archived`,
} as const;

// ---- Template picker (gap-cycle-01-002; keyboard-shortcuts §Create) --------

/**
 * UI strings for the template picker dropdown (toggled by the ``t`` chord
 * per ``docs/behavior/keyboard-shortcuts.md`` §"Create").
 */
export const TEMPLATE_PICKER_STRINGS = {
  heading: "Templates",
  emptyLabel: "No saved templates.",
  loadingLabel: "Loading templates…",
  loadErrorLabel: "Couldn't load templates.",
  instantiateErrorPrefix: "Couldn't create session:",
  closeLabel: "Close",
  deleteLabel: "Delete template",
  deleteConfirmMessage: (name: string) => `Delete template "${name}"? This cannot be undone.`,
  deleteConfirmLabel: "Delete",
  deleteCancelLabel: "Cancel",
  ariaLabel: "Template picker",
} as const;

/** String table for :class:`SessionPickerModal` (gap-cycle-03-008). */
export const SESSION_PICKER_STRINGS = {
  mergePickerTitle: "Merge into…",
  mergePickerSubtitle: (srcTitle: string) =>
    `Select a destination session to merge "${srcTitle}" into.`,
  mergePickerSearchPlaceholder: "Filter sessions…",
  mergePickerLoading: "Loading sessions…",
  mergePickerEmpty: "No other sessions found.",
  mergePickerMsgCount: "msgs",
  mergePickerCancel: "Cancel",
} as const;

/**
 * Quota-bar yellow / red transition thresholds (spec §4 + §10 —
 * "yellow at 80% used, red at 95%"). Mirrors the backend's
 * :data:`QUOTA_BAR_YELLOW_PCT` / :data:`QUOTA_BAR_RED_PCT`
 * (``src/bearings/config/constants.py:81-82``). Values are fractions
 * in ``[0.0, 1.0]`` so they line up with the
 * ``overall_used_pct`` / ``sonnet_used_pct`` shape on the API.
 */
export const QUOTA_BAR_YELLOW_PCT = 0.8;
export const QUOTA_BAR_RED_PCT = 0.95;

/**
 * Routing-source values mirrored from
 * :data:`bearings.config.constants.KNOWN_ROUTING_SOURCES` (spec §App
 * A enum). The dialog reads ``quota_downgrade`` to decide when to
 * render the downgrade banner with the "Use anyway" override;
 * InspectorRouting (item 2.6) reads every value to render the
 * source label inside "Why this model?".
 */
export const ROUTING_SOURCE_TAG_RULE = "tag_rule";
export const ROUTING_SOURCE_SYSTEM_RULE = "system_rule";
export const ROUTING_SOURCE_DEFAULT = "default";
export const ROUTING_SOURCE_MANUAL = "manual";
export const ROUTING_SOURCE_QUOTA_DOWNGRADE = "quota_downgrade";
export const ROUTING_SOURCE_MANUAL_OVERRIDE_QUOTA = "manual_override_quota";
export const ROUTING_SOURCE_UNKNOWN_LEGACY = "unknown_legacy";

/**
 * Full routing-source alphabet. Mirrors backend
 * :data:`bearings.config.constants.KNOWN_ROUTING_SOURCES` (spec §App
 * A). Iterated by the InspectorRouting "Why this model?" surface so
 * a future source addition lights up automatically.
 */
export const KNOWN_ROUTING_SOURCES = [
  ROUTING_SOURCE_TAG_RULE,
  ROUTING_SOURCE_SYSTEM_RULE,
  ROUTING_SOURCE_DEFAULT,
  ROUTING_SOURCE_MANUAL,
  ROUTING_SOURCE_QUOTA_DOWNGRADE,
  ROUTING_SOURCE_MANUAL_OVERRIDE_QUOTA,
  ROUTING_SOURCE_UNKNOWN_LEGACY,
] as const;
export type RoutingSource = (typeof KNOWN_ROUTING_SOURCES)[number];

// ---- Routing-rule CRUD endpoints (spec §9) ------------------------------

/**
 * ``GET /api/tags/{id}/routing`` / ``POST /api/tags/{id}/routing`` —
 * tag-rule list + create surfaces consumed by
 * :class:`RoutingRuleEditor` (item 2.8) per spec §9. Mirrors
 * :func:`bearings.web.routes.routing.list_tag_rules` /
 * :func:`create_tag_rule`.
 */
export const tagRoutingRulesEndpoint = (tagId: number): string =>
  `${API_BASE}/tags/${tagId}/routing`;

/**
 * ``PATCH /api/routing/{id}`` / ``DELETE /api/routing/{id}`` — tag-rule
 * update + delete surfaces (spec §9). The backend reserves
 * ``PATCH /api/routing/system/{id}`` for system rules (item 1.8
 * decided-and-documented).
 */
export const tagRoutingRuleEndpoint = (ruleId: number): string => `${API_BASE}/routing/${ruleId}`;

/**
 * ``PATCH /api/tags/{id}/routing/reorder`` — re-stamp tag-rule
 * priorities to match the supplied id order (spec §9).
 */
export const tagRoutingReorderEndpoint = (tagId: number): string =>
  `${API_BASE}/tags/${tagId}/routing/reorder`;

/**
 * ``GET /api/routing/system`` / ``POST /api/routing/system`` —
 * system-rule list + create surfaces (spec §9).
 */
export const API_SYSTEM_ROUTING_RULES_ENDPOINT = `${API_BASE}/routing/system`;

/**
 * ``PATCH /api/routing/system/{id}`` / ``DELETE …`` — system-rule
 * update + delete surfaces (spec §9). Spec §9 does NOT enumerate a
 * dedicated system-rule reorder endpoint; the editor re-stamps
 * priorities by issuing per-rule PATCHes (decided-and-documented in
 * :class:`RoutingRuleEditor`).
 */
export const systemRoutingRuleEndpoint = (ruleId: number): string =>
  `${API_BASE}/routing/system/${ruleId}`;

// ---- Routing match-type alphabet (mirrors backend) -----------------------

/**
 * Match-type alphabet per spec §3:
 *
 * - ``keyword`` — case-insensitive substring against the first user
 *   message; ``match_value`` is comma-separated; any match triggers.
 * - ``regex`` — ``re.IGNORECASE`` regex against the first user
 *   message. Invalid regex disables the rule (spec §3 "Invalid
 *   regexes disable the rule and surface an error in the editor").
 * - ``length_gt`` / ``length_lt`` — message length in characters
 *   compared against ``int(match_value)``.
 * - ``always`` — unconditional; used as the lowest-priority fallback
 *   in system rules (priority 1000 in the seeded set per spec §3).
 *
 * Values mirror the backend
 * :data:`bearings.config.constants.KNOWN_ROUTING_MATCH_TYPES` (spec
 * §3 schema CHECK constraint). Drift between the two surfaces is a
 * behavioural bug caught by the backend's ``CHECK`` clause the first
 * time a rule of an unknown type reaches the route.
 */
export const ROUTING_MATCH_TYPE_KEYWORD = "keyword";
export const ROUTING_MATCH_TYPE_REGEX = "regex";
export const ROUTING_MATCH_TYPE_LENGTH_GT = "length_gt";
export const ROUTING_MATCH_TYPE_LENGTH_LT = "length_lt";
export const ROUTING_MATCH_TYPE_ALWAYS = "always";
export const KNOWN_ROUTING_MATCH_TYPES = [
  ROUTING_MATCH_TYPE_KEYWORD,
  ROUTING_MATCH_TYPE_REGEX,
  ROUTING_MATCH_TYPE_LENGTH_GT,
  ROUTING_MATCH_TYPE_LENGTH_LT,
  ROUTING_MATCH_TYPE_ALWAYS,
] as const;
export type RoutingMatchType = (typeof KNOWN_ROUTING_MATCH_TYPES)[number];

/**
 * Rule-kind discriminator for the ``RoutingRuleEditor`` ``kind`` prop
 * — the editor branches on this to pick the tag-rule vs system-rule
 * endpoint set. Mirrors the ``rule_kind`` column on
 * :class:`OverrideRateOut` (item 1.8 override-rate aggregator).
 *
 * The full alphabet (``ROUTING_RULE_KIND_SYSTEM``,
 * ``KNOWN_ROUTING_RULE_KINDS``, ``RoutingRuleKind``) is deliberately
 * not re-exported in v1 — the editor's ``Props`` union is the single
 * consumer of the system-side discriminant and binds the literal
 * ``"system"`` directly. The full alphabet returns when a second
 * consumer (a kind-aware filter, a future API client) needs it.
 */
export const ROUTING_RULE_KIND_TAG = "tag";

/**
 * Default ``priority`` for a freshly added rule. Mirrors the backend
 * column defaults (``DEFAULT 100`` on tag rules, ``DEFAULT 1000`` on
 * system rules) per spec §3 schema. Tag rules pack at 100; new
 * system rules slot at 500 — between the seeded keyword/length rules
 * (10–60) and the ``always`` fallback (1000) so user-added rules
 * appear neither at the very top nor below the workhorse default.
 */
export const ROUTING_RULE_DEFAULT_PRIORITY_TAG = 100;
export const ROUTING_RULE_DEFAULT_PRIORITY_SYSTEM = 500;

/**
 * Default ``advisor_max_uses`` for a freshly added rule (mirrors
 * spec §2 default-policy table — Sonnet executor, the rule editor's
 * starting executor → 5 advisor calls). Backend default is also 5
 * via the ``advisor_max_uses INTEGER DEFAULT 5`` column on both rule
 * tables (spec §3 schema).
 */
export const ROUTING_RULE_DEFAULT_ADVISOR_MAX_USES = 5;

// ---- Routing-rule editor strings (spec §3 + §10) ------------------------

/**
 * UI strings for :class:`RoutingRuleEditor` + :class:`RuleRow` +
 * :class:`TestAgainstMessageDialog` (item 2.8). Cites spec §3 (rule
 * editing surface) + §10 ("Modified: Routing rule editor" widget +
 * the deterministic "Test against message" dialog) + §8 ("Review:"
 * highlight prefix on rules whose override rate exceeds
 * :data:`OVERRIDE_RATE_REVIEW_THRESHOLD`).
 *
 * Pulled out of components per coding-standards
 * §"i18n-ready string tables".
 */
export const ROUTING_EDITOR_STRINGS = {
  // Top-level pane labels (spec §10 "Modified: Routing rule editor").
  paneAriaLabelTag: "Tag routing rules",
  paneAriaLabelSystem: "System routing rules",
  headingTag: "Tag routing rules",
  headingSystem: "System routing rules",
  loading: "Loading routing rules…",
  loadFailed: "Couldn't load routing rules.",
  saveFailed: "Couldn't save the rule.",
  reorderFailed: "Couldn't reorder rules.",
  emptyTag: "No tag rules yet — add one to override the system defaults.",
  emptySystem: "No system rules yet — add one as a global fallback.",
  addRuleLabel: "Add rule",
  // Per spec §8: "Rules with override_rate > 0.30 over the last 14 days
  // are surfaced in the routing rule editor as 'Review:' highlighted
  // rows." The prefix is the literal string the spec calls out.
  reviewPrefix: "Review:",
  reviewTooltipTemplate: "Override rate {pct}% over the last {days} days — review this rule.",
  // Per-row column labels (spec §10 row layout — priority, match-type,
  // match-value, executor, advisor, enabled, effort, reason).
  rowAriaLabelTemplate: "Routing rule {ruleId}",
  rowDragHandleAriaLabel: "Drag to reorder",
  rowPriorityLabel: "Priority",
  rowMatchTypeLabel: "Match",
  rowMatchValueLabel: "Value",
  rowMatchValuePlaceholderKeyword: "comma-separated keywords",
  rowMatchValuePlaceholderRegex: "case-insensitive regex",
  rowMatchValuePlaceholderLength: "length threshold (chars)",
  rowMatchValueDisabledAlways: "(no value — always matches)",
  rowMatchValueInvalidRegex: "Invalid regex — rule disabled until fixed.",
  rowExecutorLabel: "Executor",
  rowAdvisorLabel: "Advisor",
  rowAdvisorMaxUsesLabel: "Max calls",
  rowEffortLabel: "Effort",
  rowReasonLabel: "Reason",
  rowReasonPlaceholder: "Explain why this rule fires (shown in UI when matched).",
  rowEnabledLabel: "Enabled",
  rowSeededIndicatorLabel: "Seeded",
  rowSeededIndicatorTitle: "Shipped default rule — disable rather than delete.",
  // Per-row action labels (spec §10 "Right-click ⋮: Test against
  // message, Duplicate, Disable, Delete").
  actionTestLabel: "Test against message",
  actionDuplicateLabel: "Duplicate",
  actionDisableLabel: "Disable",
  actionEnableLabel: "Enable",
  actionDeleteLabel: "Delete",
  actionDeleteConfirmTemplate: "Delete this rule? This cannot be undone.",
  actionMenuAriaLabel: "Rule actions",
  // Test-against-message dialog (spec §10: "deterministic dialog —
  // it evaluates the rule's match condition against pasted text and
  // shows the resulting routing decision. No LLM call. Test inputs
  // are not stored").
  testDialogTitle: "Test against message",
  testDialogAriaLabel: "Test rule against message",
  testDialogIntro:
    "Paste a message to evaluate against this rule. The check runs locally — no LLM, no save.",
  testDialogMessageLabel: "Message",
  testDialogMessagePlaceholder: "Paste the first user message here…",
  testDialogEvaluateLabel: "Evaluate",
  testDialogCloseLabel: "Close",
  testDialogResultMatched: "Rule matched.",
  testDialogResultMissed: "Rule did not match.",
  testDialogResultExecutorLabel: "Would route to executor",
  testDialogResultAdvisorLabel: "Advisor",
  testDialogResultEffortLabel: "Effort",
  testDialogResultReasonLabel: "Reason",
  testDialogInvalidRegex: "Invalid regex — fix the rule before testing.",
  // Match-type display labels (spec §3 alphabet → user-visible).
  matchTypeLabels: {
    [ROUTING_MATCH_TYPE_KEYWORD]: "keyword",
    [ROUTING_MATCH_TYPE_REGEX]: "regex",
    [ROUTING_MATCH_TYPE_LENGTH_GT]: "length >",
    [ROUTING_MATCH_TYPE_LENGTH_LT]: "length <",
    [ROUTING_MATCH_TYPE_ALWAYS]: "always",
  } as const satisfies Record<RoutingMatchType, string>,
} as const;

// ---- Inspector usage / override-rate windows + thresholds ----------------

/**
 * InspectorUsage headroom-chart window (spec §7 "Quota efficiency" +
 * §10 "Headroom remaining chart" — "rolling 7-day plot of overall
 * bucket and Sonnet bucket consumption, with reset markers").
 * Mirrors backend :data:`USAGE_HEADROOM_WINDOW_DAYS` in
 * ``src/bearings/config/constants.py:97`` so the chart range and the
 * ``GET /api/quota/history?days=N`` default agree.
 */
export const USAGE_HEADROOM_WINDOW_DAYS = 7;

/**
 * Override-rate "Review:" threshold (spec §8 — "Rules with
 * override_rate > 0.30 over the last 14 days are surfaced ... as
 * 'Review:' highlighted rows" + §10 "Rules to review list — rules
 * with override rate > 30 % in the last 14 days, click to jump to
 * the rule editor"). Mirrors backend
 * :data:`OVERRIDE_RATE_REVIEW_THRESHOLD` in
 * ``src/bearings/config/constants.py:87``.
 */
export const OVERRIDE_RATE_REVIEW_THRESHOLD = 0.3;

/**
 * Override-rate rolling window (spec §8 + §10). Mirrors backend
 * :data:`OVERRIDE_RATE_WINDOW_DAYS` in
 * ``src/bearings/config/constants.py:92``.
 */
export const OVERRIDE_RATE_WINDOW_DAYS = 14;

// ---- Routing alphabet (mirrors backend ``KNOWN_*``) -----------------------

/**
 * Two-axis routing selector alphabets per spec §3 (rule eval inputs)
 * + §6 (the new-session dialog selectors). Mirrors the backend's
 * :data:`KNOWN_EXECUTOR_MODELS` and :data:`KNOWN_EFFORT_LEVELS`
 * (``src/bearings/config/constants.py:224, 236``). The
 * advisor-axis null choice is encoded as
 * :const:`ADVISOR_MODEL_NONE` so a templated ``<select>`` carries it
 * without a sentinel literal.
 */
export const EXECUTOR_MODEL_SONNET = "sonnet";
export const EXECUTOR_MODEL_HAIKU = "haiku";
export const EXECUTOR_MODEL_OPUS = "opus";
export const KNOWN_EXECUTOR_MODELS = [
  EXECUTOR_MODEL_SONNET,
  EXECUTOR_MODEL_HAIKU,
  EXECUTOR_MODEL_OPUS,
] as const;
export type ExecutorModel = (typeof KNOWN_EXECUTOR_MODELS)[number];

export const ADVISOR_MODEL_OPUS = "opus";
export const ADVISOR_MODEL_NONE = "" as const;
export const KNOWN_ADVISOR_MODELS = [ADVISOR_MODEL_NONE, ADVISOR_MODEL_OPUS] as const;
export type AdvisorModelChoice = (typeof KNOWN_ADVISOR_MODELS)[number];

export const EFFORT_LEVEL_AUTO = "auto";
const EFFORT_LEVEL_LOW = "low";
const EFFORT_LEVEL_MEDIUM = "medium";
const EFFORT_LEVEL_HIGH = "high";
const EFFORT_LEVEL_XHIGH = "xhigh";
export const KNOWN_EFFORT_LEVELS = [
  EFFORT_LEVEL_AUTO,
  EFFORT_LEVEL_LOW,
  EFFORT_LEVEL_MEDIUM,
  EFFORT_LEVEL_HIGH,
  EFFORT_LEVEL_XHIGH,
] as const;
export type EffortLevel = (typeof KNOWN_EFFORT_LEVELS)[number];

/**
 * Default ``advisor.max_uses`` for the new-session dialog (spec §2
 * "Default policy" table — Sonnet executor → 5, Haiku executor → 3,
 * Opus executor → no advisor). Mirrors backend
 * :data:`DEFAULT_ADVISOR_MAX_USES_SONNET` /
 * :data:`DEFAULT_ADVISOR_MAX_USES_HAIKU`.
 */
export const DEFAULT_ADVISOR_MAX_USES_SONNET = 5;
export const DEFAULT_ADVISOR_MAX_USES_HAIKU = 3;

/**
 * Approximate input-token pricing (USD per 1 M tokens) for each executor
 * model (spec §7 recost estimate, spec §13 risk 4 "off by ±20%").
 *
 * Used only for the mid-session model-switch confirmation dialog.  The
 * dialog copy explicitly labels all numbers "estimated."  These rates
 * reflect Anthropic's published list prices as of v1.1; pin-bump if
 * pricing changes materially.
 *
 * Values: Sonnet 4.6 → $3.00/M, Haiku 4.5 → $0.80/M, Opus 4.7 → $15.00/M.
 */
export const MODEL_INPUT_RATES_USD_PER_MILLION: Record<ExecutorModel, number> = {
  [EXECUTOR_MODEL_SONNET]: 3.0,
  [EXECUTOR_MODEL_HAIKU]: 0.8,
  [EXECUTOR_MODEL_OPUS]: 15.0,
};

// ---- Inspector tab alphabet + string table -------------------------------

/**
 * Inspector subsection identifiers — the tab strip on
 * :class:`Inspector` (right column of the app shell, per
 * ``docs/architecture-v1.md`` §1.2 inspector decomposition) renders
 * one button per id.
 *
 * Item 2.5 ships the first three (Agent / Context / Instructions);
 * item 2.6 lights up Routing / Usage by populating their bodies and
 * extending :data:`KNOWN_INSPECTOR_TABS`. The IDs themselves live here
 * so the shell never refers to a tab by inline string literal — a new
 * id is added by editing this file, not by patching the shell.
 *
 * The values are stable wire-shaped strings (lowercase ASCII, no
 * whitespace) so a future ``?inspector_tab=<id>`` deep-link or a
 * keyboard-shortcut binding can address a tab without a translation
 * table.
 */
export const INSPECTOR_TAB_AGENT = "agent";
export const INSPECTOR_TAB_CONTEXT = "context";
export const INSPECTOR_TAB_INSTRUCTIONS = "instructions";
/**
 * Files subsection — aggregated view of every file path the agent
 * has touched in the active session (gap-cycle-09-003). The shell
 * switches on this id to render :class:`InspectorFiles`.
 */
export const INSPECTOR_TAB_FILES = "files";
/**
 * Changes subsection (gap-cycle-09-004) — lists every WRITE-side
 * tool call (``Edit`` / ``Write`` / ``NotebookEdit``) made in the
 * active session, sorted most-recent first. The shell switches on
 * this id to render :class:`InspectorChanges`.
 */
export const INSPECTOR_TAB_CHANGES = "changes";
/**
 * Metrics subsection (gap-cycle-09-005) — two cards: token totals
 * (Input / Output / Cache read / Cache write) and tool-call counters
 * (Total / Running / Failed / Total elapsed). Per-session granularity.
 * Inserted between Changes and Routing to preserve adjacency with the
 * other per-session content tabs; app-wide rollups (Routing / Usage)
 * remain at the end of the strip.
 */
export const INSPECTOR_TAB_METRICS = "metrics";
/**
 * Routing subsection (spec §10 "Modified: Inspector 'Routing'
 * subsection"). Lit by item 2.6 — the Inspector shell switches on
 * the id to render :class:`InspectorRouting`.
 */
export const INSPECTOR_TAB_ROUTING = "routing";
/**
 * Usage subsection (spec §10 "New: Usage tab in the inspector").
 * Lit by item 2.6 — the Inspector shell switches on the id to
 * render :class:`InspectorUsage`.
 */
export const INSPECTOR_TAB_USAGE = "usage";

/**
 * Tabs the inspector exposes. Item 2.6 appended ``"routing"`` and
 * ``"usage"`` (per spec §10 inspector decomposition) — the shell's
 * body switch grew two cases; the tab strip itself iterates this
 * tuple so the new tabs appear without further refactor.
 */
export const KNOWN_INSPECTOR_TABS = [
  INSPECTOR_TAB_AGENT,
  INSPECTOR_TAB_CONTEXT,
  INSPECTOR_TAB_INSTRUCTIONS,
  INSPECTOR_TAB_FILES,
  INSPECTOR_TAB_CHANGES,
  INSPECTOR_TAB_METRICS,
  INSPECTOR_TAB_ROUTING,
  INSPECTOR_TAB_USAGE,
] as const;
export type InspectorTabId = (typeof KNOWN_INSPECTOR_TABS)[number];

/**
 * Default tab the inspector lands on when the user first selects a
 * session. ``Agent`` is chosen because it is the only subsection whose
 * surface (executor model, working dir) the user already saw mirrored
 * in the conversation header — opening on ``Agent`` is a natural
 * continuation, not a context switch.
 *
 * The default is a constant rather than a runtime preference because
 * theme-style per-device persistence is item 2.9's surface; v1 of the
 * inspector uses an in-memory selection that resets across reloads.
 *
 * The literal value mirrors :const:`INSPECTOR_TAB_AGENT` deliberately —
 * the same string carries two distinct meanings (the *id* of the agent
 * tab vs the *default* the inspector boots into), and the constants
 * stay separate so a future change to the default can flip this one
 * value without re-pointing every reference to ``INSPECTOR_TAB_AGENT``
 * (which is the agent tab's identity, not the default policy). The
 * type cast keeps knip from flagging the literal as a structural
 * duplicate of the other ``"agent"`` export.
 */
export const DEFAULT_INSPECTOR_TAB = "agent" as InspectorTabId;

/**
 * ``localStorage`` key that persists the user's active inspector tab
 * across page reloads (gap-cycle-09-002). Value is one of the
 * :data:`KNOWN_INSPECTOR_TABS` literals; defaults to
 * :data:`DEFAULT_INSPECTOR_TAB` when absent or unrecognised.
 *
 * Uses the ``bearings-v1:`` namespace to match the other per-device
 * preference keys (:data:`SESSION_SORT_STORAGE_KEY`,
 * :data:`AUTH_TOKEN_STORAGE_KEY`).
 */
export const INSPECTOR_TAB_STORAGE_KEY = "bearings-v1:inspector-tab";

/**
 * Inspector string table — chat.md §"opens an existing chat" cites
 * the inspector as a sibling pane to the conversation; chat.md
 * §"What the user does NOT see in chat" enumerates Routing + Usage
 * as inspector subsections and cross-references the per-message
 * timeline.  chat.md is silent on the user-facing copy of the
 * Agent / Context / Instructions subsections — implementation here
 * follows the architecture-v1.md §1.2 decomposition (one component
 * per subsection) plus the ``SessionOut`` shape from
 * ``api/sessions.ts`` for the field labels. Behavioral gap recorded
 * in the executor's self-verification block per plan
 * §"Behavioral gap escalation".
 */
export const INSPECTOR_STRINGS = {
  paneAriaLabel: "Inspector",
  tabStripAriaLabel: "Inspector subsections",
  emptySession: "Select a session to inspect.",
  missingSession: "The selected session is no longer loaded — pick another from the sidebar.",
  tabLabels: {
    [INSPECTOR_TAB_AGENT]: "Agent",
    [INSPECTOR_TAB_CONTEXT]: "Context",
    [INSPECTOR_TAB_INSTRUCTIONS]: "Instructions",
    [INSPECTOR_TAB_FILES]: "Files",
    [INSPECTOR_TAB_CHANGES]: "Changes",
    [INSPECTOR_TAB_METRICS]: "Metrics",
    [INSPECTOR_TAB_ROUTING]: "Routing",
    [INSPECTOR_TAB_USAGE]: "Usage",
  } as const satisfies Record<InspectorTabId, string>,
  // Agent subsection — exposes the active session's agent config.
  // Items 2.6 + 1.8 add advisor / effort / fallback fields by widening
  // ``SessionOut`` and surfacing the new columns here.
  agentHeading: "Agent",
  agentModelLabel: "Executor model",
  agentPermissionModeLabel: "Permission mode",
  agentPermissionModeUnset: "(default)",
  agentWorkingDirLabel: "Working directory",
  agentMaxBudgetLabel: "Budget cap (USD)",
  agentMaxBudgetUnset: "no cap",
  agentTotalCostLabel: "Total cost (USD)",
  agentMessageCountLabel: "Messages",
  // Context subsection — mirrors the context-window / cost data the
  // header band carries (chat.md §"opens an existing chat") in the
  // inspector's longer-form layout. The system-prompt + tag-default
  // overlays + vault attachments parts of the Context subsection are
  // gated on items 1.4 / 1.5 / 1.7 surfacing the assembled context
  // over the API; rendered here as a placeholder section so 2.5 ships
  // a complete shell.
  contextHeading: "Context",
  contextSessionTitleLabel: "Title",
  contextDescriptionLabel: "Description",
  contextDescriptionEmpty: "(no description)",
  contextLastContextPctLabel: "Last context-window pressure",
  contextLastContextTokensLabel: "Last context tokens",
  contextLastContextMaxLabel: "Context-window max",
  contextLastContextNotSeen: "no turn observed yet",
  contextAssembledHeading: "Assembled context",
  contextAssembledPlaceholder:
    "System prompt, tag-default overlays, and vault attachments surface here once the assembled-context API lands (items 1.4 / 1.5 / 1.7).",
  // Instructions subsection — exposes ``session_instructions`` from
  // the SessionOut shape. ``null`` / empty renders the empty-state copy.
  instructionsHeading: "Instructions",
  instructionsBodyLabel: "Session instructions",
  instructionsEmpty: "No per-session instructions set.",
  instructionsEditButton: "Edit…",
  // Files subsection (gap-cycle-09-003) — derives rows from
  // conversationStore.turns via path-key extraction on each
  // ToolCallView. The three path keys (file_path, notebook_path,
  // path) mirror the v17 FilesTab logic; Bash and Glob are skipped.
  filesHeading: "Files Touched",
  filesEmptyHeading: "No files touched yet",
  filesEmptyBody:
    "A row appears each time the agent reads, writes, edits, or greps a specific file path.",
  // Changes subsection (gap-cycle-09-004) — one row per Write-side tool
  // call (Edit / Write / NotebookEdit), sorted most-recent first.
  changesHeading: "Changes",
  changesEmptyHeading: "No changes yet",
  changesEmptyBody:
    "A row appears each time the agent writes a new file, edits an existing file, or modifies a notebook cell.",
  // Metrics subsection (gap-cycle-09-005) — per-session token totals +
  // tool-call counters. Token data comes from the conversation store's
  // accumulated ``session*Tokens`` counters (input, output, cache-read).
  // Cache-write is not yet emitted by the v18 backend; its cell renders
  // ``—`` until the backend surfaces ``cache_creation_tokens``.
  metricsTokenTotalsHeading: "Token totals",
  metricsTokenInputLabel: "Input",
  metricsTokenOutputLabel: "Output",
  metricsTokenCacheReadLabel: "Cache read",
  metricsTokenCacheWriteLabel: "Cache write",
  metricsTokenCacheWriteUnavailable: "—",
  metricsToolCallsHeading: "Tool calls",
  metricsToolCallsTotalLabel: "Total",
  metricsToolCallsRunningLabel: "Running",
  metricsToolCallsFailedLabel: "Failed",
  metricsToolCallsElapsedLabel: "Total elapsed",
  metricsToolCallsElapsedEmpty: "—",
  metricsAnalyticsLink: "View cross-session rollups →",
  // Routing subsection (spec §10 "Modified: Inspector 'Routing'
  // subsection"). The current-decision card surfaces the four
  // routing-decision fields the spec lists; the timeline + advisor
  // totals + quota delta read the per-message routing/usage projection
  // from item 1.9. The "Why this model?" expandable per assistant
  // message renders the rule eval chain (source + matched_rule_id +
  // reason) — the full ``evaluated_rules`` list is a future widening
  // (item 1.9 surfaces ``matched_rule_id`` only on the wire today).
  routingHeading: "Routing",
  routingLoading: "Loading routing data…",
  routingError: "Couldn't load routing data.",
  routingEmpty: "No assistant turns yet — routing data appears after the first reply.",
  routingCurrentHeading: "Current routing",
  routingCurrentExecutorLabel: "Executor",
  routingCurrentAdvisorLabel: "Advisor",
  routingCurrentAdvisorNone: "(none)",
  routingCurrentEffortLabel: "Effort",
  routingCurrentSourceLabel: "Source",
  routingCurrentReasonLabel: "Reason",
  routingTotalsHeading: "Session totals",
  routingTotalsAdvisorCallsLabel: "Advisor calls",
  routingTotalsAdvisorTokensLabel: "Advisor tokens",
  routingTotalsExecutorTokensLabel: "Executor tokens",
  routingQuotaDeltaHeading: "Quota delta this session",
  routingQuotaDeltaOverallLabel: "Overall bucket",
  routingQuotaDeltaSonnetLabel: "Sonnet bucket",
  routingTimelineHeading: "Per-message timeline",
  routingTimelineEmpty: "No assistant messages with routing data yet.",
  routingTimelineWhyLabel: "Why this model?",
  routingTimelineMatchedRuleLabel: "Matched rule",
  routingTimelineNoMatchedRule: "(no rule — fallback default)",
  // Routing-source presentation labels (spec §App A enum). Mirror the
  // wire alphabet via :const:`KNOWN_ROUTING_SOURCES`.
  routingSourceLabels: {
    [ROUTING_SOURCE_TAG_RULE]: "Tag rule",
    [ROUTING_SOURCE_SYSTEM_RULE]: "System rule",
    [ROUTING_SOURCE_DEFAULT]: "Default",
    [ROUTING_SOURCE_MANUAL]: "Manual",
    [ROUTING_SOURCE_QUOTA_DOWNGRADE]: "Quota downgrade",
    [ROUTING_SOURCE_MANUAL_OVERRIDE_QUOTA]: "Manual override (quota)",
    [ROUTING_SOURCE_UNKNOWN_LEGACY]: "Unknown (legacy)",
  } as const satisfies Record<RoutingSource, string>,
  // Usage subsection (spec §10 "New: Usage tab in the inspector").
  // Strings match the four widgets the spec enumerates: headroom
  // chart, by-model table, advisor-effectiveness widget, rules-to-
  // review list.
  usageHeading: "Usage",
  usageLoading: "Loading usage data…",
  usageError: "Couldn't load usage data.",
  usageHeadroomHeading: "Headroom remaining",
  usageHeadroomCaption: "Rolling 7-day plot of overall + Sonnet bucket consumption.",
  usageHeadroomEmpty: "No quota snapshots in the last 7 days.",
  usageHeadroomOverallLabel: "Overall",
  usageHeadroomSonnetLabel: "Sonnet",
  usageHeadroomCapturedAtLabel: "Captured at",
  usageByModelHeading: "By model",
  usageByModelEmpty: "No per-model token totals in the last 7 days.",
  usageByModelColModel: "Model",
  usageByModelColRole: "Role",
  usageByModelColInputTokens: "Input",
  usageByModelColOutputTokens: "Output",
  usageByModelColAdvisorCalls: "Advisor calls",
  usageByModelColCacheReadTokens: "Cache read",
  usageByModelColSessions: "Sessions",
  usageAdvisorEffectivenessHeading: "Advisor effectiveness",
  usageAdvisorEffectivenessEmpty:
    "Not enough data — the advisor effectiveness widget needs at least one session with advisor calls.",
  usageAdvisorEffectivenessCallsPerSessionLabel: "Calls per session",
  usageAdvisorEffectivenessShareLabel: "Advisor token share",
  usageAdvisorEffectivenessQualReadLabel: "Read",
  usageAdvisorEffectivenessQualPulling: "Advisor is pulling its weight.",
  usageAdvisorEffectivenessQualMarginal: "Advisor contribution is marginal.",
  usageAdvisorEffectivenessQualUnused: "Advisor is rarely consulted.",
  usageRulesToReviewHeading: "Rules to review",
  usageRulesToReviewCaption: "Rules whose override rate exceeded 30% over the last 14 days.",
  usageRulesToReviewEmpty: "No rules over the review threshold — routing is healthy.",
  usageRulesToReviewColKind: "Kind",
  usageRulesToReviewColRuleId: "Rule",
  usageRulesToReviewColRate: "Override rate",
  usageRulesToReviewColFired: "Fired",
  usageRulesToReviewColOverridden: "Overridden",
} as const;

// ---- Session-edit modal string table -------------------------------------

/**
 * UI strings for the SessionEdit modal (gap-cycle-10-001).
 *
 * The modal exposes Title, Description, Budget USD, Tags, and Session
 * instructions fields. AI-title-suggestion (✨) is intentionally out of
 * scope — it depends on the absent anthropic backend (cycle 1 gap-020
 * root cause); see ``docs/behavior/chat.md`` §"SessionEdit modal" for
 * the documented carve-out.
 */
export const SESSION_EDIT_MODAL_STRINGS = {
  title: "Edit session",
  ariaLabel: "Edit session modal",
  titleLabel: "Title",
  titlePlaceholder: "Session title",
  descriptionLabel: "Description",
  descriptionPlaceholder: "Short description (optional)",
  budgetLabel: "Budget cap (USD)",
  budgetPlaceholder: "No cap",
  tagsLabel: "Tags",
  tagInputPlaceholder: "Type to filter or create a tag…",
  tagCreateHint: (name: string): string => `Press Enter to create "${name}"`,
  tagNoMatches: "No matching tags — press Enter to create",
  instructionsLabel: "Session instructions",
  instructionsPlaceholder: "Per-session instructions injected into every prompt (optional)",
  saveButton: "Save",
  savingButton: "Saving…",
  cancelButton: "Cancel",
  errorPrefix: "Save failed:",
} as const;

// ---- New-session dialog string table -------------------------------------

/**
 * UI strings for the new-session dialog (chat.md §"creates a chat" +
 * spec §6 layout + spec §8 quota banner copy). Pulled out of the
 * components per coding-standards §"i18n-ready string tables".
 */
export const NEW_SESSION_STRINGS = {
  dialogTitle: "New Session",
  dialogAriaLabel: "New session dialog",
  routingHeading: "Routing (auto-resolved from tags + first message)",
  executorLabel: "Executor",
  advisorLabel: "Advisor",
  advisorEnabledLabel: "enabled",
  advisorMaxUsesLabel: "max calls",
  advisorOpusExecutorHint: "Opus is the executor — advisor not needed.",
  advisorOptionNoneLabel: "(none)",
  effortLabel: "Effort",
  routedFromPrefix: "Routed from",
  routedManualOverride: "Manual override",
  firstMessageLabel: "First message",
  firstMessagePlaceholder: "What would you like to start the session with?",
  quotaHeading: "Quota",
  quotaOverallLabel: "overall",
  quotaSonnetLabel: "sonnet",
  quotaUnavailable: "Quota data unavailable",
  quotaResetTooltipPrefix: "Resets at",
  downgradeBannerPrefix: "Routing downgraded to",
  downgradeBannerOverallSuffixTemplate: "(overall quota at {pct}%)",
  downgradeBannerSonnetSuffixTemplate: "(sonnet quota at {pct}%)",
  downgradeUseAnywayLabel: "Use {model} anyway",
  kindToggleAriaLabel: "Session kind",
  kindChatLabel: "Chat",
  kindChecklistLabel: "Checklist",
  cancelLabel: "Cancel",
  submitLabel: "Start Session",
  loadingPreview: "Resolving routing…",
  previewError: "Couldn't resolve routing — try again.",
  // Display labels for executor / advisor / effort options. Capitalised
  // for the dropdown surface; the underlying value is the lowercase
  // wire identifier (``sonnet`` / ``haiku`` / ``opus`` / ``auto`` /
  // ``low`` / ``medium`` / ``high`` / ``xhigh``).
  executorLabels: {
    [EXECUTOR_MODEL_SONNET]: "Sonnet 4.6",
    [EXECUTOR_MODEL_HAIKU]: "Haiku 4.5",
    [EXECUTOR_MODEL_OPUS]: "Opus 4.7",
  } as const satisfies Record<ExecutorModel, string>,
  advisorLabels: {
    [ADVISOR_MODEL_NONE]: "(none)",
    [ADVISOR_MODEL_OPUS]: "Opus 4.6",
  } as const satisfies Record<AdvisorModelChoice, string>,
  effortLabels: {
    [EFFORT_LEVEL_AUTO]: "auto",
    [EFFORT_LEVEL_LOW]: "low",
    [EFFORT_LEVEL_MEDIUM]: "medium",
    [EFFORT_LEVEL_HIGH]: "high",
    [EFFORT_LEVEL_XHIGH]: "xhigh",
  } as const satisfies Record<EffortLevel, string>,
} as const;

// ---- Checklist alphabets (mirrors backend ``KNOWN_*``) --------------------

/**
 * Auto-driver run-state alphabet — mirrors backend
 * :data:`bearings.config.constants.KNOWN_AUTO_DRIVER_STATES`. The
 * AutoDriverControls component branches on the active run's
 * ``state`` to enable / disable the run-control buttons per
 * ``docs/behavior/checklists.md`` §"Run-control surface".
 */
export const AUTO_DRIVER_STATE_IDLE = "idle";
export const AUTO_DRIVER_STATE_RUNNING = "running";
export const AUTO_DRIVER_STATE_PAUSED = "paused";
export const AUTO_DRIVER_STATE_FINISHED = "finished";
// ``errored`` + the full alphabet (``KNOWN_AUTO_DRIVER_STATES``) +
// the ``AutoDriverState`` type are deliberately not exported in v1 —
// the only consumer (AutoDriverControls) reads the four states above
// directly. The backend alphabet (``KNOWN_AUTO_DRIVER_STATES`` in
// :mod:`bearings.config.constants`) stays the source of truth; this
// file re-introduces the mirror when an enum-shaped UI consumer
// arrives.

/**
 * Auto-driver failure-policy alphabet — mirrors backend
 * :data:`bearings.config.constants.KNOWN_AUTO_DRIVER_FAILURE_POLICIES`.
 * The user picks one in the AutoDriverControls dropdown before pressing
 * Start; the choice applies to the next run only.
 */
export const AUTO_DRIVER_FAILURE_POLICY_HALT = "halt";
export const AUTO_DRIVER_FAILURE_POLICY_SKIP = "skip";
export const KNOWN_AUTO_DRIVER_FAILURE_POLICIES = [
  AUTO_DRIVER_FAILURE_POLICY_HALT,
  AUTO_DRIVER_FAILURE_POLICY_SKIP,
] as const;
export type AutoDriverFailurePolicy = (typeof KNOWN_AUTO_DRIVER_FAILURE_POLICIES)[number];

/**
 * Item non-completion category alphabet — mirrors backend
 * :data:`bearings.config.constants.KNOWN_ITEM_OUTCOMES`. Drives the pip
 * color in :class:`SentinelEvent` per
 * ``docs/behavior/checklists.md`` §"Item-status colors".
 */
export const ITEM_OUTCOME_BLOCKED = "blocked";
export const ITEM_OUTCOME_FAILED = "failed";
export const ITEM_OUTCOME_SKIPPED = "skipped";
export const KNOWN_ITEM_OUTCOMES = [
  ITEM_OUTCOME_BLOCKED,
  ITEM_OUTCOME_FAILED,
  ITEM_OUTCOME_SKIPPED,
] as const;
// ``ItemOutcome`` type is not yet referenced by a TS consumer; the
// alphabet is read at runtime via the array. The type is re-introduced
// when a consumer needs the union form.

/**
 * Sentinel-kind alphabet — mirrors backend
 * :data:`bearings.config.constants.KNOWN_SENTINEL_KINDS`. Used by the
 * frontend sentinel parser (``parseSentinels`` in ``sentinel.ts``) to
 * decide which kinds are well-known and which to ignore as malformed
 * per ``docs/behavior/checklists.md`` §"Sentinels".
 */
export const SENTINEL_KIND_ITEM_DONE = "item_done";
export const SENTINEL_KIND_HANDOFF = "handoff";
export const SENTINEL_KIND_FOLLOWUP_BLOCKING = "followup_blocking";
export const SENTINEL_KIND_FOLLOWUP_NONBLOCKING = "followup_nonblocking";
export const SENTINEL_KIND_ITEM_BLOCKED = "item_blocked";
export const SENTINEL_KIND_ITEM_FAILED = "item_failed";
export const KNOWN_SENTINEL_KINDS = [
  SENTINEL_KIND_ITEM_DONE,
  SENTINEL_KIND_HANDOFF,
  SENTINEL_KIND_FOLLOWUP_BLOCKING,
  SENTINEL_KIND_FOLLOWUP_NONBLOCKING,
  SENTINEL_KIND_ITEM_BLOCKED,
  SENTINEL_KIND_ITEM_FAILED,
] as const;
export type SentinelKind = (typeof KNOWN_SENTINEL_KINDS)[number];

/**
 * Spawned-by alphabet for a paired-chat link — mirrors backend
 * :data:`bearings.config.constants.KNOWN_PAIRED_CHAT_SPAWNED_BY`. The
 * link/spawn UI passes ``"user"``; the auto-driver passes
 * ``"driver"`` from server-side code paths only.
 */
export const PAIRED_CHAT_SPAWNED_BY_USER = "user";
// ``PAIRED_CHAT_SPAWNED_BY_DRIVER`` is the backend's enum value for
// auto-driver-spawned chats. The UI never sets it (only the user
// path), but the constant ships in the backend alphabet
// :data:`bearings.config.constants.KNOWN_PAIRED_CHAT_SPAWNED_BY` and
// is re-introduced here when a UI consumer needs to disambiguate the
// two paths.

/**
 * Driver outcome strings observed by the user when the status line
 * freezes — mirrors backend :data:`DRIVER_OUTCOME_*`. The empty-run
 * string is the only outcome the AutoDriverControls fallback path
 * needs today; the others (``Completed`` / ``Halted: max items`` /
 * ``Halted: stopped by user``) are backend-written values that arrive
 * through ``AutoDriverRunOut.outcome`` and are rendered verbatim by
 * :func:`formatStatusLine`.
 */
export const DRIVER_OUTCOME_HALTED_EMPTY = "Halted: empty";

/**
 * Auto-driver run-status poll cadence (ms). Decided-and-documented:
 * ``docs/behavior/checklists.md`` §"Run-control surface" prescribes a
 * live status line ("Running — item 3 of 12, leg 1, 0 failures") that
 * ticks while a run is in flight. Item 1.6 ships the run-row state +
 * the ``GET /api/checklists/{id}`` overview but NOT a per-checklist
 * driver-state WS broker; a future item adds the broker. v1 polls the
 * overview while a run is live so the user observes the status-line
 * ticks. 1500 ms chosen to match the user-perceived liveness of the
 * existing per-session WS heartbeat (``WS_IDLE_PING_INTERVAL_S=15``)
 * scaled for a UI thread that wants finer granularity than the
 * heartbeat-grade keepalive.
 */
export const CHECKLIST_OVERVIEW_POLL_INTERVAL_MS = 1500;

// ---- Checklist string table ----------------------------------------------

/**
 * UI string table for the checklist surfaces (item 2.7). Pulled out of
 * components per coding-standards §"i18n-ready string tables". Anchors
 * for each string trace to behavior docs in inline comments.
 */
export const CHECKLIST_STRINGS = {
  // Top-level pane labels (behavior/checklists.md §"What a checklist is, observably").
  paneAriaLabel: "Checklist pane",
  loadingOverview: "Loading checklist…",
  loadFailed: "Couldn't load this checklist.",
  emptyChecklist: "No items yet — type below to add the first one.",
  addItemPlaceholder: "Add an item…",
  addItemAriaLabel: "Add a new checklist item",
  // Item row labels (behavior/checklists.md §"Item edit / add / delete / reorder").
  itemDragHandleAriaLabel: "Drag to reorder",
  itemCheckboxAriaLabel: "Mark item complete",
  itemCheckboxParentDisabledTitle: "Parent items are derived from their children",
  itemLabelEditAriaLabel: "Edit item label",
  itemNotesToggleLabel: "Notes",
  itemNotesPlaceholder: "Add notes for this item…",
  itemDeleteLabel: "Delete",
  itemDeleteConfirmTemplate: "Delete this item? Children + paired chats will also be removed.",
  // Paired-chat link/spawn labels (behavior/paired-chats.md §"Link / spawn UI").
  pairedChatWorkOnThisLabel: "💬 Work on this",
  pairedChatWorkOnThisAriaLabel: "Spawn a paired chat for this item",
  pairedChatContinueLabel: "Continue working",
  pairedChatContinueAriaLabel: "Open the paired chat for this item",
  pairedChatLinkExistingLabel: "Link existing chat…",
  pairedChatUnlinkLabel: "Unlink chat",
  pairedChatLinkChooseLabel: "Choose a chat to link:",
  pairedChatLinkConfirmLabel: "Link",
  pairedChatLinkCancelLabel: "Cancel",
  pairedChatLinkEmptyLabel: "No open chat sessions to link.",
  pairedChatSpawnFailed: "Couldn't spawn a paired chat.",
  pairedChatLinkFailed: "Couldn't link the chosen chat.",
  // Auto-driver run-control labels (behavior/checklists.md §"Run-control surface").
  runControlsAriaLabel: "Auto-driver run controls",
  runStartLabel: "Start",
  runStopLabel: "Stop",
  runPauseLabel: "Pause",
  runResumeLabel: "Resume",
  runSkipCurrentLabel: "Skip current",
  runFailurePolicyLabel: "On failure",
  runFailurePolicyHaltLabel: "halt run",
  runFailurePolicySkipLabel: "skip & continue",
  runVisitExistingLabel: "Visit existing chats",
  runVisitExistingTitle: "Reuse each item's already-paired chat instead of spawning fresh ones.",
  runStatusIdle: "Idle — press Start to drive the checklist.",
  runStatusEmpty: "Halted: empty",
  // Behavior doc §"Run-control surface" template:
  // "Running — item N of M, leg L, F failures".
  runStatusRunningTemplate:
    "Running — item {currentIndex} of {total}, leg {legs}, {failures} failures",
  runStatusPausedTemplate: "Paused — {completed}/{total} complete, {failures} failures",
  runStatusOutcomeTemplate: "{outcome} — {completed}/{total} complete, {failures} failures",
  // Sentinel-event surface — surfaces the parsed sentinels per
  // behavior/checklists.md §"Sentinels".
  sentinelEventAriaLabel: "Item state",
  sentinelEventTooltipNone: "Not yet attempted by a driver, no paired chat.",
  sentinelEventTooltipSlate: "Has a paired chat, no run currently driving the item.",
  sentinelEventTooltipBlue: "The autonomous driver currently has this item active.",
  sentinelEventTooltipGreen: "Item is checked.",
  sentinelEventTooltipAmber: "Item is blocked.",
  sentinelEventTooltipRed: "Item failed.",
  sentinelEventTooltipGrey: "Item was skipped.",
  // Per-sentinel-kind label (sentinel kind → user-visible chip).
  sentinelKindLabels: {
    item_done: "item done",
    handoff: "handoff",
    followup_blocking: "followup (blocking)",
    followup_nonblocking: "followup (non-blocking)",
    item_blocked: "item blocked",
    item_failed: "item failed",
  } as const satisfies Record<string, string>,
  // Failure-on-item template (mirrors backend
  // ``DRIVER_OUTCOME_HALTED_FAILURE_TEMPLATE``).
  driverOutcomeHaltedFailureTemplate: "Halted: failure on item {itemId}",
  // ChecklistChat surface (behavior/checklists.md §ChecklistChat).
  chatPanelAriaLabel: "Checklist chat",
  chatInputPlaceholder: "Ask about this checklist…",
  chatInputAriaLabel: "Message to checklist agent",
  chatSendLabel: "Send",
  chatSendAriaLabel: "Send message to checklist agent",
} as const;

// ---- Vault (item 2.10; mirrors ``docs/behavior/vault.md``) ----------------

/**
 * Vault-entry kind alphabet — mirrors :data:`bearings.config.constants.
 * VAULT_KIND_PLAN` / :data:`VAULT_KIND_TODO`. Discriminator on every
 * :interface:`VaultEntryOut`. Plans bucket vs Todos bucket per
 * vault.md §"Vault entry types".
 */
export const VAULT_KIND_PLAN = "plan";
export const VAULT_KIND_TODO = "todo";
export const KNOWN_VAULT_KINDS = [VAULT_KIND_PLAN, VAULT_KIND_TODO] as const;
export type VaultKind = (typeof KNOWN_VAULT_KINDS)[number];

/**
 * Vault search result hard cap. Mirrors backend
 * :data:`bearings.config.constants.VAULT_SEARCH_RESULT_CAP`. The
 * frontend reads this only for the UI "showing first N — narrow your
 * query for more" copy (per vault.md §"Search semantics") — the
 * server enforces the cap and round-trips a ``capped`` flag, so the
 * count is presentational rather than authoritative.
 */
export const VAULT_SEARCH_RESULT_CAP = 200;

/**
 * Per-line snippet display cap. Mirrors backend
 * :data:`bearings.config.constants.VAULT_SEARCH_SNIPPET_MAX_CHARS`.
 * The server already trims; the frontend uses this constant to cap
 * the visible snippet column at the same width so a future server
 * widening doesn't blow out the UI without an explicit decision here.
 */
export const VAULT_SEARCH_SNIPPET_MAX_CHARS = 240;

/**
 * Debounce window for the vault-pane search input — vault.md is
 * silent on the exact value (only specifies that the query is
 * "treated as a literal string"). Decided-and-documented at the
 * routing-preview cadence (300 ms) so two reactive search surfaces
 * across the app feel the same; revisit if the server-side rescan
 * latency makes 300 ms feel sluggish.
 */
export const VAULT_SEARCH_DEBOUNCE_MS = 300;

/**
 * Mask glyph for masked redaction ranges in the reading panel.
 * Mirrors backend :data:`bearings.config.constants.
 * VAULT_REDACTION_MASK_GLYPH` so the on-wire detection and the
 * client mask render identically (vault.md §"Redaction rendering" —
 * "replaces the visible text with a `••••••••` mask").
 */
export const VAULT_REDACTION_MASK_GLYPH = "••••••••";

/**
 * UI strings for the vault pane. Pulled out of the component per
 * coding-standards "i18n-ready string tables".
 */
export const VAULT_STRINGS = {
  paneAriaLabel: "Vault",
  paneHeading: "Vault",
  searchAriaLabel: "Search vault",
  searchPlaceholder: "Search plans + todos…",
  loading: "Loading vault…",
  loadFailed: "Couldn't load the vault index.",
  emptyAll: "Vault is empty.",
  emptyConfigTemplate: "No plans found under {plan_roots}. No TODO.md files match {todo_globs}.",
  plansHeading: "Plans",
  todosHeading: "Todos",
  searchEmptyResults: "No matches.",
  searchCappedTemplate: "Showing first {n} — narrow your query for more.",
  searchHitTemplate: "{kind} · line {line}",
  selectedReadingPanelLabel: "Reading panel",
  selectedEmpty: "Select a doc to read.",
  selectedReadFailed: "Unable to read.",
  selectedTruncated: "Doc was very large — body truncated server-side.",
  copyMarkdownLink: "Copy as Markdown link",
  copyBody: "Copy doc body",
  pasteMarkdownLinkIntoComposer: "Paste link into composer",
  pasteBodyIntoComposer: "Paste body into composer",
  redactionShow: "Show",
  redactionHide: "Hide",
  redactionAriaLabel: "Toggle redacted value",
  pasteToastLinkPasted: "Pasted link into composer",
  pasteToastBodyPasted: "Pasted body into composer",
  pasteToastClipboardLink: "Copied Markdown link",
  pasteToastClipboardBody: "Copied doc body",
  pasteToastNoActiveSession: "No active chat session — open one first.",
  // Per vault.md §"CRUD flow" the vault is read-only — no create /
  // update / delete affordances in the UI. The string table
  // intentionally omits any "delete doc" / "rename doc" / "new doc"
  // labels so a coding-standards search cannot turn one up.
} as const;

// ---- Memories editor (item 2.10; folds across chat.md / checklists.md / vault.md) ----

/**
 * Tag-memory title length cap. Mirrors backend
 * :data:`bearings.config.constants.TAG_MEMORY_TITLE_MAX_LENGTH`.
 * The editor surfaces a character counter against this bound so a
 * 422 from the API surface is unreachable through the form path.
 */
export const TAG_MEMORY_TITLE_MAX_LENGTH = 200;

/**
 * Tag-memory body length cap. Mirrors backend
 * :data:`bearings.config.constants.TAG_MEMORY_BODY_MAX_LENGTH`.
 * Memories are system-prompt fragments per arch §1.1.3; the cap
 * bounds any single fragment so a runaway memory cannot saturate
 * the prompt-prime budget.
 */
export const TAG_MEMORY_BODY_MAX_LENGTH = 30_000;

/**
 * UI strings for the memories editor. Memories are user-authored
 * tag-scoped system-prompt fragments per arch §1.1.3 (vault is
 * read-only — see :const:`VAULT_STRINGS`). Pulled out of the
 * component per coding-standards "i18n-ready string tables".
 */
export const MEMORIES_STRINGS = {
  paneAriaLabel: "Memories editor",
  paneHeading: "Memories",
  tagSelectorLabel: "Tag",
  tagSelectorPlaceholder: "Pick a tag…",
  tagSelectorEmpty: "No tags yet — create one in the new-session dialog.",
  loading: "Loading memories…",
  loadFailed: "Couldn't load memories for this tag.",
  emptyForTag: "No memories yet on this tag.",
  newButtonLabel: "New memory",
  saveButtonLabel: "Save",
  cancelButtonLabel: "Cancel",
  deleteButtonLabel: "Delete",
  editButtonLabel: "Edit",
  enabledToggleLabel: "Enabled",
  enabledHelp: "Disabled memories are hidden from the prompt assembler.",
  titleLabel: "Title",
  titlePlaceholder: "Short summary…",
  bodyLabel: "Body",
  bodyPlaceholder: "System-prompt fragment for this tag…",
  validationTitleRequired: "Title is required.",
  validationTitleTooLong: "Title is too long.",
  validationBodyRequired: "Body is required.",
  validationBodyTooLong: "Body is too long.",
  deleteConfirmTemplate: "Delete memory {title}? This cannot be undone.",
  pickTagFirst: "Pick a tag to view its memories.",
  characterCountTemplate: "{used} / {max}",
} as const;

// ---- Themes (item 2.9; mirrors ``docs/behavior/themes.md`` §"Theme picker UI") ----

/**
 * The four themes shipped in v1. Evergreen (forest-green, flat) is the
 * v0.17.x visual-parity default added for the skinning pass. Identifiers
 * are wire-shaped strings written into ``data-theme`` on the document
 * root and into the localStorage value; adding another theme means
 * appending one entry to this alphabet plus a matching CSS variable
 * block in :file:`src/app.css`.
 */
export const THEME_EVERGREEN = "evergreen";
export const THEME_MIDNIGHT_GLASS = "midnight-glass";
export const THEME_DEFAULT = "default";
export const THEME_PAPER_LIGHT = "paper-light";

export const KNOWN_THEMES = [
  THEME_EVERGREEN,
  THEME_MIDNIGHT_GLASS,
  THEME_DEFAULT,
  THEME_PAPER_LIGHT,
] as const;
export type ThemeId = (typeof KNOWN_THEMES)[number];

/**
 * Mobile-chrome / address-bar color per theme — written to the
 * ``<meta name="theme-color">`` tag on theme change per
 * ``docs/behavior/themes.md`` §"What gets re-themed live". Values
 * mirror the ``--bearings-surface-0`` rgb tuple from
 * :file:`frontend/src/app.css` rendered as a hex literal so the
 * runtime can write a single ``#rrggbb`` string into the meta content
 * without a CSS-variable read.
 */
export const THEME_COLOR_HEX: Record<ThemeId, string> = {
  [THEME_EVERGREEN]: "#0e131b",
  [THEME_MIDNIGHT_GLASS]: "#0e1729",
  [THEME_DEFAULT]: "#111827",
  [THEME_PAPER_LIGHT]: "#faf7f0",
} as const;

/**
 * ``data-theme`` attribute name + storage key. Pulled out as named
 * constants so tests + boot script + runtime store agree by import,
 * not by literal duplication. The ``-v1`` suffix on the storage key
 * lets a future migration rotate the namespace without trampling the
 * old value (the old key reads as missing, the OS fallback applies,
 * the runtime writes the v2 namespace on next pick).
 */
export const THEME_DATA_ATTR_NAME = "data-theme";
export const THEME_STORAGE_KEY = "bearings-theme-v1";
export const THEME_META_NAME = "theme-color";

/**
 * localStorage key prefix for per-session composer drafts.
 *
 * Full key: ``${COMPOSER_DRAFT_KEY_PREFIX}${sessionId}``.
 *
 * The ``bearings-v1:`` namespace keeps Bearings keys grouped and
 * separated from other apps that may share the same origin; the
 * ``draft:`` infix identifies the subsystem. Plain UTF-8 value —
 * no JSON wrapper, the draft is always a plain string.
 */
export const COMPOSER_DRAFT_KEY_PREFIX = "bearings-v1:draft:";

/**
 * localStorage key for the sidebar session-sort preference.
 *
 * Value is one of the ``SESSION_SORT_*`` literals. Defaults to
 * ``SESSION_SORT_LAST_ACTION`` when absent.
 */
export const SESSION_SORT_STORAGE_KEY = "bearings-v1:session-sort";

/** Sort sessions as a flat list ordered by ``updated_at DESC``. */
export const SESSION_SORT_LAST_ACTION = "last_action" as const;
/** Sort sessions grouped alphabetically by tag (original behaviour). */
export const SESSION_SORT_GROUPED = "grouped" as const;

export type SessionSortMode = typeof SESSION_SORT_LAST_ACTION | typeof SESSION_SORT_GROUPED;

/**
 * Theme picker + Appearance section UI strings. Anchors to
 * ``docs/behavior/themes.md`` §"Theme picker UI" (option labels +
 * caption) + §"Failure modes" (toast copy).
 */
export const THEME_STRINGS = {
  appearanceHeading: "Appearance",
  pickerLabel: "Theme",
  pickerAriaLabel: "Theme",
  pickerCaption: "Saved per device. Applies immediately.",
  saveFailedToast: "Couldn't save your theme — try again.",
  themeLabels: {
    [THEME_EVERGREEN]: "Evergreen (forest-green, flat)",
    [THEME_MIDNIGHT_GLASS]: "Midnight Glass (warm-navy, glass panels)",
    [THEME_DEFAULT]: "Default (Tailwind classic dark)",
    [THEME_PAPER_LIGHT]: "Paper Light (cream, flat)",
  } as const satisfies Record<ThemeId, string>,
} as const;

// ---- Display timezone (gap-cycle-07-006) ----

/**
 * localStorage key for the per-device display timezone preference.
 * NOT round-tripped to /api/preferences — each device keeps its own tz.
 * Absence in localStorage means "Auto" (browser default).
 */
export const DISPLAY_TIMEZONE_STORAGE_KEY = "bearings:display:timezone";

/**
 * Curated IANA timezone list for Settings → Appearance.
 * "Auto" is a sentinel meaning "use the browser default" — it is never
 * written to localStorage; its absence is the canonical representation.
 */
export const KNOWN_DISPLAY_TIMEZONES = [
  "Auto",
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Asia/Tokyo",
  "Asia/Shanghai",
] as const;

export type DisplayTimezone = (typeof KNOWN_DISPLAY_TIMEZONES)[number];

/** Human-readable labels for each timezone option shown in the select. */
export const DISPLAY_TIMEZONE_LABELS: Record<DisplayTimezone, string> = {
  Auto: "Auto (browser default)",
  UTC: "UTC",
  "America/New_York": "America/New York (ET)",
  "America/Chicago": "America/Chicago (CT)",
  "America/Denver": "America/Denver (MT)",
  "America/Los_Angeles": "America/Los Angeles (PT)",
  "Europe/London": "Europe/London (GMT/BST)",
  "Europe/Paris": "Europe/Paris (CET/CEST)",
  "Asia/Tokyo": "Asia/Tokyo (JST)",
  "Asia/Shanghai": "Asia/Shanghai (CST)",
};

/** UI strings for the timezone control in Settings → Appearance. */
export const TIMEZONE_STRINGS = {
  timezoneLabel: "Display timezone",
  timezoneCaption: "Saved per device. Timestamps re-render immediately.",
} as const;

// ---- Preferences / defaults (item 3.2) ----

/**
 * Valid ``permission_mode`` literals accepted by the SDK, mirrored from
 * :data:`bearings.config.constants.KNOWN_SDK_PERMISSION_MODES`.
 * Exposed here so the Defaults section in ``/settings`` can build a
 * typed ``<select>`` without duplicating the list.
 */
export const KNOWN_PERMISSION_MODES = [
  "default",
  "acceptEdits",
  "plan",
  "bypassPermissions",
  "dontAsk",
  "auto",
] as const;
export type PermissionMode = (typeof KNOWN_PERMISSION_MODES)[number];

/** Human-readable labels for permission mode values. */
export const PERMISSION_MODE_LABELS: Record<PermissionMode, string> = {
  default: "Default",
  acceptEdits: "Accept edits",
  plan: "Plan only",
  bypassPermissions: "Bypass permissions",
  dontAsk: "Don't ask",
  auto: "Auto",
};

/** Preferences section UI strings. */
export const PREFERENCES_STRINGS = {
  defaultsHeading: "Defaults",
  defaultsLede: "Pre-fill the new-session form. Leave a field blank to use the system default.",
  themeLabel: "Default theme",
  modelLabel: "Default model",
  permissionModeLabel: "Default permission mode",
  workingDirLabel: "Default working directory",
  saveButton: "Save defaults",
  savedFeedback: "Saved.",
  saveError: "Couldn't save — try again.",
  loadError: "Couldn't load preferences.",
  modelPlaceholder: "(use routing rules)",
  permissionModePlaceholder: "(SDK default)",
  workingDirPlaceholder: "/path/to/project",
} as const;

/** Profile / identity section UI strings (gap-cycle-03-011). */
export const PROFILE_STRINGS = {
  heading: "Profile",
  lede: "Your identity shown in the sidebar and status bar.",
  displayNameLabel: "Display name",
  displayNamePlaceholder: "Your name",
  avatarLabel: "Profile picture",
  uploadButton: "Upload image",
  removeButton: "Remove",
  syncButton: "Sync from system",
  syncLede: "Copies your $USER and ~/.face into the display name and avatar.",
  saveButton: "Save profile",
  savedFeedback: "Saved.",
  saveError: "Couldn't save — try again.",
  loadError: "Couldn't load profile.",
  syncError: "Sync failed — try again.",
  uploadError: "Upload failed — try again.",
  removeError: "Couldn't remove avatar.",
  avatarAlt: "Profile picture",
  avatarFallbackAriaLabel: "No profile picture set",
} as const;

/** Notifications section UI strings (gap-cycle-07-001). */
export const NOTIFICATION_STRINGS = {
  heading: "Notifications",
  toggleLabel: "Notify when Claude finishes replying",
  footnoteUnsupported: "Your browser does not support desktop notifications.",
  footnoteDenied:
    "Blocked in browser settings — re-allow notifications for this site, then re-toggle.",
  permissionDeniedError: "Browser denied notification permission — toggle rolled back.",
} as const;

/** Authentication section UI strings for Settings (gap-cycle-07-002). */
export const AUTH_SECTION_STRINGS = {
  heading: "Authentication",
  lede: "Your auth token is stored on this device only — it is never sent to the Bearings server as a preference.",
  tokenLabel: "Auth token",
  tokenPlaceholder: "Leave empty if the server has auth disabled",
} as const;

/** Privacy section UI strings for Settings (gap-cycle-07-003). */
export const PRIVACY_STRINGS = {
  heading: "Privacy",
  telemetryLine: "Your data stays on this device",
  telemetryLinkLabel: "No telemetry — audit the promise",
  telemetryLinkHref: "https://github.com/Beryndil/Bearings/blob/main/TELEMETRY.md",
  dataDirLabel: "Data directory",
  dataDirLoading: "Loading…",
  dataDirError: "Couldn't load data directory.",
  openDirButton: "Open data dir",
  openDirOpened: "Opened",
  openDirCopied: "Path copied",
  /** Footnote shown after clipboard fallback naming the config key to set. */
  clipboardFallbackNote:
    "To open in a file manager, add xdg-open to shell.allowed_commands in ~/.config/bearings/config.toml",
  openDirError: "Couldn't open or copy the data directory path.",
} as const;

/**
 * UI strings for the Help section of the Settings page
 * (gap-cycle-07-004).
 *
 * Five rows rendered in one card:
 * 1. Keyboard shortcuts — opens the cheat-sheet overlay.
 * 2. README — external link to the GitHub project README.
 * 3. Documentation — external link to the GitHub docs folder.
 * 4. Report a bug — opens a pre-filled GitHub ``issues/new`` (bug).
 * 5. Request a feature — opens a pre-filled GitHub ``issues/new``
 *    (feature).
 *
 * The two feedback rows do not POST any data; the browser opens the
 * GitHub form and the user submits manually (Beryndil standards §17).
 */
export const HELP_SECTION_STRINGS = {
  heading: "Help",
  keyboardShortcutsLabel: "Keyboard shortcuts",
  keyboardShortcutsHint: "Open the cheat sheet",
  readmeLabel: "README",
  readmeHref: "https://github.com/Beryndil/Bearings#readme",
  docsLabel: "Documentation",
  docsHref: "https://github.com/Beryndil/Bearings/tree/main/docs",
  reportBugLabel: "Report a bug",
  requestFeatureLabel: "Request a feature",
} as const;

/**
 * UI strings for the About section of the Settings page
 * (gap-cycle-07-005).
 *
 * Two sub-sections:
 *
 * **Hero** (centered column):
 * - BearingsMark logo at 48 px
 * - "Bearings" title
 * - Release version line (from ``GET /api/diag/server``)
 * - One-line tagline
 * - Clickable "by Beryndil" byline → developer link
 * - /about_beryndil.png photo at 80 × 80 rounded
 * - "Buy Me a Cup of Coffee" CTA → same developer link
 *
 * **Identity card** (rows):
 * - Build → formatted build-mtime or "dev build" fallback
 * - Repository → GitHub repo link
 * - License → MIT, GitHub LICENSE link
 * - Credits → CREDITS.md GitHub link
 */
export const ABOUT_SECTION_STRINGS = {
  heading: "About",
  /** "Bearings" product name rendered in the hero. */
  productName: "Bearings",
  tagline: "Localhost web UI for Claude Code agent sessions.",
  /** Version placeholder while ``GET /api/diag/server`` resolves. */
  versionLoading: "v…",
  versionUnavailable: "version unavailable",
  /** "by Beryndil" byline label. */
  bylineLabel: "by Beryndil",
  /** URL for the byline link and the coffee CTA. */
  developerUrl: "https://hardknocks.university/developer.html",
  /** Alt text for the developer photo. */
  photoAlt: "Beryndil",
  /** CTA eyebrow (above the card title). */
  coffeeEyebrow: "Enjoy Bearings?",
  coffeeLabel: "Buy Me a Cup of Coffee",
  /** Identity card row labels. */
  buildLabel: "Build",
  /** "dev build" fallback when build_mtime is null or non-finite. */
  buildFallback: "dev build",
  repositoryLabel: "Repository",
  repositoryHref: "https://github.com/Beryndil/Bearings",
  repositoryLinkLabel: "github.com/Beryndil/Bearings",
  licenseLabel: "License",
  licenseLinkLabel: "MIT",
  licenseHref: "https://github.com/Beryndil/Bearings/blob/main/LICENSE",
  creditsLabel: "Credits",
  creditsLinkLabel: "CREDITS.md",
  creditsHref: "https://github.com/Beryndil/Bearings/blob/main/CREDITS.md",
} as const;

/** UI strings for the PermissionModeSelector header dropdown (item 3.3). */
export const PERMISSION_MODE_SELECTOR_STRINGS = {
  ariaLabel: "Permission mode",
  labelPrefix: "Mode:",
  saveError: "Couldn't update permission mode.",
} as const;

/** UI strings for the ModelSelector header dropdown (spec §7). */
export const MODEL_SELECTOR_STRINGS = {
  ariaLabel: "Executor model",
  labelPrefix: "Model:",
  saveError: "Couldn't update model.",
} as const;

/**
 * UI strings for the ModelSwitchDialog confirmation modal (spec §7).
 *
 * Templates use ``{from}``, ``{to}``, ``{tokens}``, ``{cost}``
 * placeholders that the component fills at render time.
 */
export const MODEL_SWITCH_DIALOG_STRINGS = {
  ariaLabel: "Switch executor model",
  /** "Switch executor: Sonnet 4.6 → Opus 4.7" */
  titleTemplate: "Switch executor: {from} → {to}",
  /**
   * "This will re-cost ~38,000 input tokens of conversation history at
   * Opus 4.7 rates."  Shown when ``last_context_tokens`` is available.
   */
  recostBodyTemplate:
    "This will re-cost ~{tokens} input tokens of conversation history at {to} rates.",
  /**
   * Shown instead of the recost line when the session has not yet
   * completed a turn (``last_context_tokens`` is null).
   */
  recostBodyUnknown: "Context window size is unknown — cost estimate unavailable.",
  /** "Estimated additional cost: ~$0.57" */
  estimatedCostTemplate: "Estimated additional cost: ~${cost}",
  cancelLabel: "Cancel",
  switchLabel: "Switch",
  switchingLabel: "Switching…",
  switchError: "Couldn't switch model — try again.",
} as const;

// ---- Keyboard shortcuts (item 2.9; mirrors ``docs/behavior/keyboard-shortcuts.md``) ----

/**
 * Keybinding action identifiers — every chord listed in the behavior
 * doc §"Bindings (v1)" lands at one of these IDs. The dispatch layer
 * looks up a registered handler by id, so a future menu entry / palette
 * row can fire the same id and inherit the chord automatically.
 */
export const KEYBINDING_ACTION_NEW_CHAT_DEFAULTS = "create.new_chat_with_defaults";
export const KEYBINDING_ACTION_NEW_CHAT_BARE = "create.new_chat_bare";
export const KEYBINDING_ACTION_TOGGLE_TEMPLATE_PICKER = "create.toggle_template_picker";
export const KEYBINDING_ACTION_SIDEBAR_DOWN = "navigate.sidebar_down";
export const KEYBINDING_ACTION_SIDEBAR_UP = "navigate.sidebar_up";
export const KEYBINDING_ACTION_SIDEBAR_DOWN_FORCE = "navigate.sidebar_down_force";
export const KEYBINDING_ACTION_SIDEBAR_UP_FORCE = "navigate.sidebar_up_force";
export const KEYBINDING_ACTION_SIDEBAR_JUMP_PREFIX = "navigate.sidebar_jump_";
export const KEYBINDING_ACTION_ESC_CASCADE = "focus.esc_cascade";
export const KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET = "help.toggle_cheat_sheet";
export const KEYBINDING_ACTION_TOGGLE_PENDING_OPS = "help.toggle_pending_ops";
export const KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE = "palette.toggle_command_palette";
export const KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH = "palette.focus_sidebar_search";

/**
 * UI strings for the SettingsShell two-column layout (gap-cycle-07-007).
 *
 * ``statusSaving`` / ``statusSaved`` / ``statusErrorPrefix`` surface in the
 * persistent footer that aggregates save status across the active section's
 * writes.
 */
export const SETTINGS_SHELL_STRINGS = {
  /** Footer label while a PATCH is in flight. */
  statusSaving: "Saving…",
  /** Footer label after a successful PATCH (auto-clears when section switches). */
  statusSaved: "All changes saved",
  /** Prefix prepended to the error message on PATCH failure. */
  statusErrorPrefix: "Failed to save: ",
  /** Fallback when the error has no message string. */
  statusErrorGeneric: "Failed to save.",
} as const;

/**
 * Keybinding-context discriminator — context the chord is *allowed* to
 * fire in. The dispatch routes a chord by inspecting two focus flags
 * (composer focused, modal open) per
 * ``docs/behavior/keyboard-shortcuts.md`` §"Contexts (sidebar focused,
 * conversation focused, modal open)".
 *
 * The full context alphabet (sidebar / conversation / inspector /
 * checklist / context_menu) is implicit in v1 — the dispatcher
 * doesn't tag bindings by named context, it gates on the two flags
 * + the binding's ``global`` field. The full alphabet is reintroduced
 * here when a future binding (e.g. a checklist-only chord) needs the
 * finer-grained routing.
 */

/**
 * Cheat-sheet section ids (the headings in
 * ``docs/behavior/keyboard-shortcuts.md`` §"Bindings (v1)"). The cheat
 * sheet groups every registered binding under one of these.
 */
export const KEYBINDING_SECTION_CREATE = "create";
export const KEYBINDING_SECTION_NAVIGATE = "navigate";
export const KEYBINDING_SECTION_FOCUS = "focus";
export const KEYBINDING_SECTION_HELP = "help";
export const KEYBINDING_SECTION_COMMAND_PALETTE = "command_palette";

/**
 * UI strings for the cheat sheet + section headings. Anchored to
 * ``docs/behavior/keyboard-shortcuts.md`` §"What the user sees".
 */
export const KEYBOARD_SHORTCUT_STRINGS = {
  cheatSheetTitle: "Keyboard shortcuts",
  cheatSheetAriaLabel: "Keyboard shortcuts cheat sheet",
  cheatSheetCloseLabel: "Close",
  sectionLabels: {
    [KEYBINDING_SECTION_CREATE]: "Create",
    [KEYBINDING_SECTION_NAVIGATE]: "Navigate (sidebar)",
    [KEYBINDING_SECTION_FOCUS]: "Focus",
    [KEYBINDING_SECTION_HELP]: "Help",
    [KEYBINDING_SECTION_COMMAND_PALETTE]: "Command palette",
  } as const,
  actionLabels: {
    [KEYBINDING_ACTION_NEW_CHAT_DEFAULTS]: "Open the new-chat dialog",
    [KEYBINDING_ACTION_NEW_CHAT_BARE]: "Open the new-chat dialog (no defaults)",
    [KEYBINDING_ACTION_SIDEBAR_DOWN]: "Move sidebar selection down",
    [KEYBINDING_ACTION_SIDEBAR_UP]: "Move sidebar selection up",
    [KEYBINDING_ACTION_SIDEBAR_DOWN_FORCE]: "Move sidebar selection down (works in inputs)",
    [KEYBINDING_ACTION_SIDEBAR_UP_FORCE]: "Move sidebar selection up (works in inputs)",
    [KEYBINDING_ACTION_ESC_CASCADE]: "Close overlay / blur input",
    [KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET]: "Toggle this cheat sheet",
    [KEYBINDING_ACTION_TOGGLE_PENDING_OPS]: "Toggle the pending-operations card",
    [KEYBINDING_ACTION_TOGGLE_COMMAND_PALETTE]: "Toggle the command palette",
    [KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH]: "Focus the sidebar search field",
    [KEYBINDING_ACTION_TOGGLE_TEMPLATE_PICKER]: "Open the template picker",
  } as const,
  jumpToSlotLabelTemplate: "Jump to sidebar slot {n}",
  duplicateChordError:
    "Duplicate keybinding chord registered — fail-fast at boot per docs/behavior/keyboard-shortcuts.md §Conflict resolution.",
} as const;

// ---- Context menus (item 2.9; mirrors ``docs/behavior/context-menus.md``) ----

/**
 * Context-menu *target* identifiers — each surface that opens its own
 * menu has a stable target id. The action-list registry is keyed by
 * target. Values are wire-shaped strings to match the
 * ``menus.toml`` override contract per
 * ``docs/behavior/context-menus.md`` §"Per-target action lists".
 */
export const MENU_TARGET_SESSION = "session";
export const MENU_TARGET_MESSAGE = "message";
export const MENU_TARGET_TAG = "tag";
export const MENU_TARGET_TAG_CHIP = "tag_chip";
export const MENU_TARGET_TOOL_CALL = "tool_call";
export const MENU_TARGET_CODE_BLOCK = "code_block";
export const MENU_TARGET_LINK = "link";
export const MENU_TARGET_CHECKPOINT = "checkpoint";
export const MENU_TARGET_MULTI_SELECT = "multi_select";
export const MENU_TARGET_ATTACHMENT = "attachment";
export const MENU_TARGET_PENDING_OPERATION = "pending_operation";

export const KNOWN_MENU_TARGETS = [
  MENU_TARGET_SESSION,
  MENU_TARGET_MESSAGE,
  MENU_TARGET_TAG,
  MENU_TARGET_TAG_CHIP,
  MENU_TARGET_TOOL_CALL,
  MENU_TARGET_CODE_BLOCK,
  MENU_TARGET_LINK,
  MENU_TARGET_CHECKPOINT,
  MENU_TARGET_MULTI_SELECT,
  MENU_TARGET_ATTACHMENT,
  MENU_TARGET_PENDING_OPERATION,
] as const;
export type MenuTargetId = (typeof KNOWN_MENU_TARGETS)[number];

/**
 * Section identifiers per ``docs/behavior/context-menus.md`` §"Common
 * behavior across every menu" — actions inside a menu are grouped into
 * fixed sections, rendered top-to-bottom in this order.
 */
export const MENU_SECTION_PRIMARY = "primary";
export const MENU_SECTION_NAVIGATE = "navigate";
export const MENU_SECTION_CREATE = "create";
export const MENU_SECTION_EDIT = "edit";
export const MENU_SECTION_VIEW = "view";
export const MENU_SECTION_COPY = "copy";
export const MENU_SECTION_ORGANIZE = "organize";
export const MENU_SECTION_DESTRUCTIVE = "destructive";

/**
 * Section render order — the menu walks this tuple top-to-bottom and
 * renders one section per non-empty bucket, with a thin rule between
 * non-empty sections.
 */
export const MENU_SECTION_ORDER = [
  MENU_SECTION_PRIMARY,
  MENU_SECTION_NAVIGATE,
  MENU_SECTION_CREATE,
  MENU_SECTION_EDIT,
  MENU_SECTION_VIEW,
  MENU_SECTION_COPY,
  MENU_SECTION_ORGANIZE,
  MENU_SECTION_DESTRUCTIVE,
] as const;
export type MenuSectionId = (typeof MENU_SECTION_ORDER)[number];

// Per-target action ids — public identifiers per the doc's §"Per-target
// action lists" table. ``menus.toml`` references these by id; renaming
// breaks user overrides, so each id is a stable string.
export const MENU_ACTION_SESSION_OPEN_IN_NEW_TAB = "session.open_in_new_tab";
export const MENU_ACTION_SESSION_EDIT = "session.edit";
export const MENU_ACTION_SESSION_RENAME = "session.rename";
export const MENU_ACTION_SESSION_EDIT_TAGS = "session.edit_tags";
export const MENU_ACTION_SESSION_CHANGE_MODEL = "session.change_model";
export const MENU_ACTION_SESSION_DUPLICATE = "session.duplicate";
export const MENU_ACTION_SESSION_SAVE_AS_TEMPLATE = "session.save_as_template";
export const MENU_ACTION_SESSION_FORK_FROM_LAST_MESSAGE = "session.fork.from_last_message";
export const MENU_ACTION_SESSION_PIN = "session.pin";
export const MENU_ACTION_SESSION_UNPIN = "session.unpin";
export const MENU_ACTION_SESSION_ARCHIVE = "session.archive";
export const MENU_ACTION_SESSION_REOPEN = "session.reopen";
export const MENU_ACTION_SESSION_COPY_ID = "session.copy_id";
export const MENU_ACTION_SESSION_COPY_TITLE = "session.copy_title";
export const MENU_ACTION_SESSION_COPY_SHARE_LINK = "session.copy_share_link";
export const MENU_ACTION_SESSION_DELETE = "session.delete";
export const MENU_ACTION_SESSION_EXPORT_JSON = "session.export_json";
export const MENU_ACTION_SESSION_OPEN_IN_TERMINAL = "session.open_in_terminal";
export const MENU_ACTION_SESSION_MERGE_INTO = "session.merge_into";

export const MENU_ACTION_MESSAGE_JUMP_TO_TURN = "message.jump_to_turn";
export const MENU_ACTION_MESSAGE_COPY_CONTENT = "message.copy_content";
export const MENU_ACTION_MESSAGE_COPY_AS_MARKDOWN = "message.copy_as_markdown";
export const MENU_ACTION_MESSAGE_COPY_ID = "message.copy_id";
export const MENU_ACTION_MESSAGE_PIN = "message.pin";
export const MENU_ACTION_MESSAGE_HIDE_FROM_CONTEXT = "message.hide_from_context";
export const MENU_ACTION_MESSAGE_MOVE_TO_SESSION = "message.move_to_session";
export const MENU_ACTION_MESSAGE_SPLIT_HERE = "message.split_here";
export const MENU_ACTION_MESSAGE_FORK_FROM_HERE = "message.fork.from_here";
export const MENU_ACTION_MESSAGE_REGENERATE = "message.regenerate";
export const MENU_ACTION_MESSAGE_REGENERATE_IN_PLACE = "message.regenerate.in_place";
export const MENU_ACTION_MESSAGE_DELETE = "message.delete";

export const MENU_ACTION_TAG_PIN = "tag.pin";
export const MENU_ACTION_TAG_UNPIN = "tag.unpin";
export const MENU_ACTION_TAG_COPY_NAME = "tag.copy_name";
export const MENU_ACTION_TAG_EDIT = "tag.edit";
export const MENU_ACTION_TAG_DELETE = "tag.delete";

export const MENU_ACTION_TAG_CHIP_COPY_NAME = "tag_chip.copy_name";
export const MENU_ACTION_TAG_CHIP_DETACH = "tag_chip.detach";

export const MENU_ACTION_TOOL_CALL_COPY_NAME = "tool_call.copy.name";
export const MENU_ACTION_TOOL_CALL_COPY_INPUT = "tool_call.copy.input";
export const MENU_ACTION_TOOL_CALL_COPY_OUTPUT = "tool_call.copy.output";
export const MENU_ACTION_TOOL_CALL_COPY_ID = "tool_call.copy.id";
export const MENU_ACTION_TOOL_CALL_RETRY = "tool_call.retry";

export const MENU_ACTION_CODE_BLOCK_COPY = "code_block.copy";
export const MENU_ACTION_CODE_BLOCK_COPY_WITH_FENCE = "code_block.copy_with_fence";
export const MENU_ACTION_CODE_BLOCK_SAVE_TO_FILE = "code_block.save_to_file";
export const MENU_ACTION_CODE_BLOCK_OPEN_IN_EDITOR = "code_block.open_in.editor";

export const MENU_ACTION_LINK_COPY_URL = "link.copy_url";
export const MENU_ACTION_LINK_COPY_TEXT = "link.copy_text";
export const MENU_ACTION_LINK_OPEN_NEW_TAB = "link.open_new_tab";
export const MENU_ACTION_LINK_OPEN_IN_EDITOR = "link.open_in.editor";

// Phase 14 — Checkpoint surface.
export const MENU_ACTION_CHECKPOINT_FORK = "checkpoint.fork";
export const MENU_ACTION_CHECKPOINT_COPY_LABEL = "checkpoint.copy_label";
export const MENU_ACTION_CHECKPOINT_COPY_ID = "checkpoint.copy_id";
export const MENU_ACTION_CHECKPOINT_DELETE = "checkpoint.delete";

export const MENU_ACTION_MULTI_SELECT_CLEAR = "multi_select.clear";
export const MENU_ACTION_MULTI_SELECT_TAG = "multi_select.tag";
export const MENU_ACTION_MULTI_SELECT_UNTAG = "multi_select.untag";
export const MENU_ACTION_MULTI_SELECT_CLOSE = "multi_select.close";
export const MENU_ACTION_MULTI_SELECT_EXPORT = "multi_select.export";
export const MENU_ACTION_MULTI_SELECT_DELETE = "multi_select.delete";

// Phase 15 — Attachment surface.
export const MENU_ACTION_ATTACHMENT_COPY_PATH = "attachment.copy_path";
export const MENU_ACTION_ATTACHMENT_COPY_FILENAME = "attachment.copy_filename";
export const MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR = "attachment.open_in.editor";
export const MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER = "attachment.open_in.file_explorer";
export const MENU_ACTION_ATTACHMENT_REMOVE = "attachment.remove";

// Phase 16 — Pending operation surface.
export const MENU_ACTION_PENDING_OPERATION_RESOLVE = "pending_operation.resolve";
export const MENU_ACTION_PENDING_OPERATION_DISMISS = "pending_operation.dismiss";
export const MENU_ACTION_PENDING_OPERATION_COPY_NAME = "pending_operation.copy_name";
export const MENU_ACTION_PENDING_OPERATION_COPY_COMMAND = "pending_operation.copy_command";
export const MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR = "pending_operation.open_in.editor";

/**
 * Context-menu UI strings + per-action labels. Pulled out of
 * components per coding-standards §"i18n-ready string tables".
 *
 * Labels mirror the visible text in
 * ``docs/behavior/context-menus.md`` §"Per-target action lists" tables.
 */
export const CONTEXT_MENU_STRINGS = {
  rootAriaLabel: "Context menu",
  staleTargetMessage: "this object no longer exists.",
  advancedRevealedCaption: "Advanced actions revealed (Shift)",
  destructiveConfirmTitle: "Confirm",
  destructiveCancelLabel: "Cancel",
  destructiveConfirmLabel: "Confirm",
  confirmSuppressCheckboxLabel: "Don't ask again this session",
  actionLabels: {
    [MENU_ACTION_SESSION_OPEN_IN_NEW_TAB]: "Open in new tab",
    [MENU_ACTION_SESSION_EDIT]: "Edit session…",
    [MENU_ACTION_SESSION_RENAME]: "Rename…",
    [MENU_ACTION_SESSION_EDIT_TAGS]: "Edit tags…",
    [MENU_ACTION_SESSION_CHANGE_MODEL]: "Change model for continuation",
    [MENU_ACTION_SESSION_DUPLICATE]: "Duplicate",
    [MENU_ACTION_SESSION_SAVE_AS_TEMPLATE]: "Save as template…",
    [MENU_ACTION_SESSION_FORK_FROM_LAST_MESSAGE]: "Fork from last message",
    [MENU_ACTION_SESSION_PIN]: "Pin session",
    [MENU_ACTION_SESSION_UNPIN]: "Unpin session",
    [MENU_ACTION_SESSION_ARCHIVE]: "Archive session",
    [MENU_ACTION_SESSION_REOPEN]: "Reopen session",
    [MENU_ACTION_SESSION_COPY_ID]: "Copy session ID",
    [MENU_ACTION_SESSION_COPY_TITLE]: "Copy session title",
    [MENU_ACTION_SESSION_COPY_SHARE_LINK]: "Copy share link",
    [MENU_ACTION_SESSION_DELETE]: "Delete session",
    [MENU_ACTION_SESSION_EXPORT_JSON]: "Export session JSON",
    [MENU_ACTION_SESSION_OPEN_IN_TERMINAL]: "Open in terminal",
    [MENU_ACTION_SESSION_MERGE_INTO]: "Merge into…",
    [MENU_ACTION_MESSAGE_JUMP_TO_TURN]: "Scroll into view",
    [MENU_ACTION_MESSAGE_COPY_CONTENT]: "Copy message text",
    [MENU_ACTION_MESSAGE_COPY_AS_MARKDOWN]: "Copy as Markdown",
    [MENU_ACTION_MESSAGE_COPY_ID]: "Copy message ID",
    [MENU_ACTION_MESSAGE_PIN]: "Pin to turn header",
    [MENU_ACTION_MESSAGE_HIDE_FROM_CONTEXT]: "Hide from context window",
    [MENU_ACTION_MESSAGE_MOVE_TO_SESSION]: "Move to session…",
    [MENU_ACTION_MESSAGE_SPLIT_HERE]: "Split here…",
    [MENU_ACTION_MESSAGE_FORK_FROM_HERE]: "Fork from this message",
    [MENU_ACTION_MESSAGE_REGENERATE]: "Regenerate from this message…",
    [MENU_ACTION_MESSAGE_REGENERATE_IN_PLACE]: "Regenerate (rewrite in place)",
    [MENU_ACTION_MESSAGE_DELETE]: "Delete message",
    [MENU_ACTION_TAG_PIN]: "Pin tag",
    [MENU_ACTION_TAG_UNPIN]: "Unpin tag",
    [MENU_ACTION_TAG_COPY_NAME]: "Copy tag name",
    [MENU_ACTION_TAG_EDIT]: "Edit tag…",
    [MENU_ACTION_TAG_DELETE]: "Delete tag",
    [MENU_ACTION_TAG_CHIP_COPY_NAME]: "Copy tag name",
    [MENU_ACTION_TAG_CHIP_DETACH]: "Remove tag from session",
    [MENU_ACTION_TOOL_CALL_COPY_NAME]: "Copy tool name",
    [MENU_ACTION_TOOL_CALL_COPY_INPUT]: "Copy tool input",
    [MENU_ACTION_TOOL_CALL_COPY_OUTPUT]: "Copy tool output",
    [MENU_ACTION_TOOL_CALL_COPY_ID]: "Copy tool call ID",
    [MENU_ACTION_TOOL_CALL_RETRY]: "Retry tool call",
    [MENU_ACTION_CODE_BLOCK_COPY]: "Copy code",
    [MENU_ACTION_CODE_BLOCK_COPY_WITH_FENCE]: "Copy with Markdown fence",
    [MENU_ACTION_CODE_BLOCK_SAVE_TO_FILE]: "Save to file…",
    [MENU_ACTION_CODE_BLOCK_OPEN_IN_EDITOR]: "Open in editor",
    [MENU_ACTION_LINK_COPY_URL]: "Copy link URL",
    [MENU_ACTION_LINK_COPY_TEXT]: "Copy link text",
    [MENU_ACTION_LINK_OPEN_NEW_TAB]: "Open in new tab",
    [MENU_ACTION_LINK_OPEN_IN_EDITOR]: "Open in editor",
    [MENU_ACTION_CHECKPOINT_FORK]: "Fork from here",
    [MENU_ACTION_CHECKPOINT_COPY_LABEL]: "Copy label",
    [MENU_ACTION_CHECKPOINT_COPY_ID]: "Copy checkpoint ID",
    [MENU_ACTION_CHECKPOINT_DELETE]: "Delete checkpoint",
    [MENU_ACTION_MULTI_SELECT_CLEAR]: "Clear selection",
    [MENU_ACTION_MULTI_SELECT_TAG]: "Add tag",
    [MENU_ACTION_MULTI_SELECT_UNTAG]: "Remove tag",
    [MENU_ACTION_MULTI_SELECT_CLOSE]: "Close sessions",
    [MENU_ACTION_MULTI_SELECT_EXPORT]: "Export as JSON",
    [MENU_ACTION_MULTI_SELECT_DELETE]: "Delete sessions",
    [MENU_ACTION_ATTACHMENT_COPY_PATH]: "Copy path",
    [MENU_ACTION_ATTACHMENT_COPY_FILENAME]: "Copy filename",
    [MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR]: "Open in editor",
    [MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER]: "Reveal in file explorer",
    [MENU_ACTION_ATTACHMENT_REMOVE]: "Remove from message",
    [MENU_ACTION_PENDING_OPERATION_RESOLVE]: "Mark resolved",
    [MENU_ACTION_PENDING_OPERATION_DISMISS]: "Dismiss",
    [MENU_ACTION_PENDING_OPERATION_COPY_NAME]: "Copy name",
    [MENU_ACTION_PENDING_OPERATION_COPY_COMMAND]: "Copy command",
    [MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR]: "Open directory in editor",
  } as const,
} as const;

/**
 * UI strings for the approval modals (ApprovalModal + AskUserQuestionModal).
 * Pulled out of components per coding-standards "i18n-ready string tables".
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Approval modal".
 */
export const APPROVAL_STRINGS = {
  /** Generic tool-approval dialog. */
  dialogAriaLabel: "Tool approval required",
  dialogTitle: "Allow tool use?",
  toolNameLabel: "Tool",
  toolInputLabel: "Input",
  allowLabel: "Allow",
  denyLabel: "Deny",
  /** AskUserQuestion variant. */
  askDialogAriaLabel: "Agent question",
  askDialogTitle: "Agent is asking:",
  answerLabel: "Your answer",
  answerPlaceholder: "Type your answer…",
  submitLabel: "Submit",
  /**
   * AskUserQuestion variant — structured ``questions[]`` shape (one or
   * more questions, each with ``options`` and a ``multiSelect`` flag).
   * Distinct from the legacy single-question free-text shape above.
   */
  singleSelectHint: "Pick one",
  multiSelectHint: "Pick one or more",
  validationMissingSelection: "Pick an answer for every question.",
  /**
   * Fallback when neither ``{question}`` nor ``{questions: [...]}`` shape
   * is recognised — the modal pretty-prints the raw input alongside a
   * free-text answer box so the user can still respond.
   */
  unknownShapeNotice: "Question shape not recognised — answer in free text:",
} as const;

/**
 * UI strings for the backend-unreachable sticky banner
 * (``BackendStatusBanner.svelte``).
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Error states"
 * "Backend unreachable".
 */
export const BACKEND_STATUS_BANNER_STRINGS = {
  /** Accessible label for the banner container (role="status"). */
  ariaLabel: "Backend connection status",
  /** Visible message shown while the backend is unreachable. */
  message: "Backend unreachable — retrying",
} as const;

/**
 * localStorage key for the Bearings auth token (gap-cycle-01-007).
 *
 * The ``bearings-v1:`` namespace groups Bearings keys together; ``auth-token``
 * identifies the subsystem.  The value is a raw token string — no JSON wrapper.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Error states"
 * "Auth required / token expired".
 */
export const AUTH_TOKEN_STORAGE_KEY = "bearings-v1:auth-token";

/**
 * UI strings for the auth-gate modal (``AuthGate.svelte``, gap-cycle-01-007).
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Error states"
 * "Auth required / token expired".
 */
export const AUTH_GATE_STRINGS = {
  /** Dialog heading (visible + used as ``aria-labelledby`` target). */
  heading: "Auth required",
  /** Label for the token input. */
  inputLabel: "Paste your token",
  /** Placeholder inside the token input. */
  inputPlaceholder: "sk-ant-…",
  /** Submit button label in the idle state. */
  submit: "Submit",
  /** Submit button label while the save is in-flight. */
  submitting: "Saving…",
} as const;

/**
 * UI strings for the shared data-fetching wrapper
 * (``DataView.svelte``, gap-cycle-01-011).
 *
 * Behaviour anchor: ``docs/behavior/`` §"Error UX" (Beryndil standards §9).
 */
export const DATA_VIEW_STRINGS = {
  /** Accessible label for the loading skeleton region. */
  loadingAriaLabel: "Loading…",
  /** Accessible label for the error region. */
  errorAriaLabel: "Error loading data",
  /** Default error message when the consumer passes a non-empty string. */
  errorFallback: "Something went wrong.",
  /** Retry button label inside the default error state. */
  retryLabel: "Retry",
  /** Accessible label for the empty-state region. */
  emptyAriaLabel: "No items",
  /** Default empty-state copy when no ``empty`` snippet is supplied. */
  emptyFallback: "Nothing here yet.",
} as const;

/**
 * Default IntersectionObserver ``rootMargin`` for ``VirtualItem.svelte``
 * (gap-cycle-01-012). A 200 px vertical buffer pre-mounts rows before
 * they enter the viewport, preventing visible blank flashes on fast
 * scroll.
 */
export const VIRTUAL_ITEM_ROOT_MARGIN = "200px 0px" as const;

/**
 * UI strings for the :component:`TagEdit` modal (gap-cycle-01-016).
 *
 * Behavior anchor: ``docs/behavior/context-menus.md`` §Tag —
 * ``tag.edit`` action opens a modal that lets the operator reassign a
 * tag's class (project / severity / general), update its inheritance
 * fields (``default_model`` / ``working_dir``), and save via PATCH.
 * Severity-class tags surface the inheritance fields disabled-and-cleared
 * because the backend rejects non-null inheritance on severity rows.
 */
export const TAG_EDIT_STRINGS = {
  /** ``aria-label`` for the dialog backdrop. */
  dialogAriaLabel: "Edit tag",
  /** Modal title. */
  title: "Edit tag",
  /** Class selector label. */
  classLabel: "Class",
  /** Option labels for the class selector. */
  classOptions: {
    project: "Project — one per session, drives sidebar grouping",
    severity: "Severity — one per session, drives the header shield",
    general: "Other — free-form, many per session",
  } as const,
  /** Default model selector label. */
  defaultModelLabel: "Default model",
  /** Placeholder for the default model field when no value is set. */
  defaultModelPlaceholder: "e.g. sonnet",
  /** Hint shown below the field when severity is selected. */
  severityInheritanceHint: "Severity tags carry no inherited model or working dir — cleared and disabled.",
  /** Working directory field label. */
  workingDirLabel: "Default working dir",
  /** Placeholder for the working dir field. */
  workingDirPlaceholder: "/home/you/Projects/example",
  /** Submit button label. */
  saveLabel: "Save",
  /** Submit button label while saving. */
  savingLabel: "Saving…",
  /** Cancel button label. */
  cancelLabel: "Cancel",
} as const;

/**
 * How often the ``versionWatcher`` store re-fetches the Bearings version
 * from ``GET /api/diag/server`` (gap-cycle-01-018).
 *
 * One minute is long enough to be invisible to users and short enough to
 * pick up a hot-reload server restart within a reasonable window.
 */
export const STATUS_BAR_VERSION_POLL_INTERVAL_MS = 60_000;

/**
 * UI strings for the bottom status strip (gap-cycle-01-018).
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"App chrome" "Status strip".
 */
export const STATUS_BAR_STRINGS = {
  /** ``aria-label`` for the status bar container. */
  ariaLabel: "Status bar",
  /** Placeholder shown while the version is being fetched. */
  versionLoading: "v…",
  /** ``aria-label`` for the recovery-armed dot. */
  recoveryAriaLabel: "Recovery armed",
  /** ``aria-label`` for the auto-save dot. */
  autoSaveAriaLabel: "Auto-save active",
  /** Connection label when the WebSocket is open. */
  connectionConnected: "connected",
  /** Connection label when the WebSocket is closed or errored. */
  connectionDisconnected: "disconnected",
} as const;

// ---- Derivations -----------------------------------------------------------

/**
 * ``POST /api/uploads`` — single-file upload surface consumed by the
 * composer's drag-drop handler (gap-cycle-03-001;
 * ``src/bearings/web/routes/uploads.py``). Body is
 * ``multipart/form-data`` with one ``file`` part. Returns
 * :class:`bearings.web.models.uploads.UploadOut` on ``201 Created``.
 *
 * Batch uploads are implemented as parallel individual POSTs to this
 * endpoint — the backend exposes no ``/api/uploads/batch`` route in
 * v18. See ``api/uploads.ts`` :func:`uploadFile`.
 */
export const API_UPLOADS_ENDPOINT = `${API_BASE}/uploads`;

/**
 * String table for the composer's in-flight attachment chip row
 * (gap-cycle-03-001).
 *
 * Chips appear between the command-palette dropdown and the textarea
 * while files are uploading; they persist (in done / error state) until
 * the prompt is sent or the chip is removed manually.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"Composer — attachment
 * ingestion".
 */
export const COMPOSER_ATTACHMENT_STRINGS = {
  /** ``aria-label`` for the chips row container. */
  chipsAreaAriaLabel: "Pending attachments",
  /** ``aria-label`` suffix for a chip's remove button — filename is prepended. */
  removeChipAriaLabel: (filename: string) => `Remove ${filename}`,
  /** Inline error shown when the upload POST returns a non-2xx. */
  uploadFailed: "Upload failed.",
  /** Screen-reader label for the spinner shown on an uploading chip. */
  uploadingAriaLabel: "Uploading",
} as const;

/**
 * Split a slash-namespaced tag name into ``[group, leaf]``.
 *
 * - ``"bearings/architect"`` → ``["bearings", "architect"]``;
 * - ``"general"`` → ``[null, "general"]`` (default/ungrouped bucket);
 * - ``"/leading-slash"`` → ``[null, "/leading-slash"]`` (the empty
 *   prefix is treated as ungrouped, matching the backend's
 *   ``Tag.group`` property which returns ``None`` when the separator
 *   appears at index 0 or not at all).
 */
export function splitTagName(name: string): readonly [string | null, string] {
  const sepIndex = name.indexOf(TAG_GROUP_SEPARATOR);
  if (sepIndex <= 0) {
    return [null, name];
  }
  return [name.slice(0, sepIndex), name.slice(sepIndex + 1)];
}
