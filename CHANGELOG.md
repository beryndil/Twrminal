# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-04-22

Live-updating session sidebar (Phase 2) — the sidebar now updates in
sub-second time via a server-wide `/ws/sessions` broadcast channel.
The Phase-1 softRefresh poll from v0.6.2 remains as a
belt-and-suspenders reconcile: on every WebSocket (re)connect the
client fires one `softRefresh` to close any window missed while the
socket was down, and the 3-second poll continues to run until the
broadcast has earned trust via metrics / uptime.

### Added

- `bearings.agent.sessions_broker.SessionsBroker` — in-process pubsub
  for the sessions-list channel. Per-subscriber queues are bounded
  at `SUBSCRIBER_QUEUE_MAX = 500`; a subscriber whose queue fills
  gets dropped rather than stalling publishers. Helpers
  `publish_session_upsert` (fetches the live row, emits `delete`
  when the row is gone), `publish_session_delete`, and
  `publish_runner_state`.
- `GET /ws/sessions` (`bearings.api.ws_sessions`) — server-wide
  broadcast endpoint. Auth mirrors `ws_agent` (4401 on token
  failure or missing broker). Frames: `{kind: "upsert", session}`,
  `{kind: "delete", session_id}`, `{kind: "runner_state",
  session_id, is_running}`.
- Runner publishes `upsert` + `runner_state` frames at turn-start and
  again from its `finally` block at turn-end, so the
  currently-running indicator and the sidebar row lifecycle track the
  real runner state without polling.
- `SessionRunner(..., sessions_broker=...)` constructor arg and
  app-lifespan wiring (`app.state.sessions_broker`), plumbed through
  `_build_runner` in `ws_agent.py`.
- Session CRUD routes (`create_session`, `update_session`,
  `close_session`, `reopen_session`, `mark_session_viewed`,
  `delete_session`, `import_session`) publish the matching broker
  event before returning.
- `frontend/src/lib/stores/ws_sessions.svelte.ts` —
  `SessionsWsConnection` with exponential backoff reconnect (base
  1 s, cap 30 s). Exposes `handleFrame` for test harnesses. On every
  `open` it fires one `sessions.softRefresh()` so anything missed
  while the socket was down converges in one shot.
- `SessionStore.applyUpsert`, `applyDelete`, `applyRunnerState` —
  reducers for the broadcast path. `applyUpsert` respects
  local-newer `updated_at`, re-sorts by `updated_at DESC, id DESC`,
  and no-ops under an active tag filter (softRefresh handles
  filtered views). `applyDelete` clears a matching `selectedId`.
  `applyRunnerState` reassigns the `running` Set.
- `sessionsWs.connect()` wired into `+page.svelte` boot alongside
  `startRunningPoll`.

### Notes

- The Phase-1 poll is deliberately kept in place. It will be
  dropped in a later release once the broadcast has earned trust;
  `sessions.softRefresh()` itself stays as the reconnect
  reconciliation path.

## [0.6.2] - 2026-04-22

Live-updating session sidebar (Phase 1). Activity happening in the
background — sessions running without a WS subscription on the
current tab, or sessions already active when the tab loaded — now
surfaces in the sidebar within ~3 s without a page reload. Fixes the
symptom where an actively-running session stayed stuck at its old
list position until the user refreshed.

### Added

- `SessionStore.softRefresh()` — fetches `/api/sessions` with the
  current filter and reconciles against the local list. Rows present
  on the server replace the local copy unless the local `updated_at`
  is strictly newer (protects optimistic `touchSession` / `bumpCost`
  from a flicker while the server catches up). New rows are
  inserted, rows the server no longer returns are dropped, and
  `selectedId` clears if the selected session vanished. Final sort
  mirrors the server's `updated_at DESC, id DESC`.

### Changed

- `startRunningPoll` now fires `listRunningSessions()` and
  `softRefresh()` in parallel each 3 s. Running-badge updates keep
  their existing cadence; the list reconciliation piggybacks on the
  same timer so non-originating activity reaches every open tab
  without a new WS channel. Phase 2 (server-side `/ws/sessions`
  broadcast) is planned — see `TODO.md` — and will supersede the
  poll once landed.
- `add_session_cost` also bumps `sessions.updated_at`. The current
  call path in `runner.py` pairs it with `mark_session_completed`
  (which already bumps), so behavior is unchanged today — but any
  future path that records cost without a MessageComplete now stays
  sort-correct by default.

## [0.6.1] - 2026-04-22

Fix in-flight turn loss across service restarts. When
`bearings.service` was stopped (SIGTERM, crash, deploy) mid-turn, the
`claude` SDK subprocess died before emitting the assistant reply. The
user's prompt was already persisted but had no follower and no
recovery path — the prompt was silently lost and the user had to
retype it on reconnect. Root-caused from the 2026-04-22 incident
where a draft-persistence / arrow-history research prompt was lost
after a 15:48:59 UTC user-unit restart.

### Added

- `messages.replay_attempted_at` column (migration 0019) + schema
  update. The column is the fail-closed guard that prevents a replay
  loop: mark before enqueue so a crash during replay can't trigger
  an infinite restart cycle.
- `store.find_replayable_prompt(conn, session_id)` — returns the
  orphan user prompt iff the session is not closed, the newest row
  is role='user', and `replay_attempted_at IS NULL`. Closed sessions
  are excluded because the user explicitly retired them.
- `store.mark_replay_attempted(message_id)` — idempotent stamp. A
  second call on the same row returns False so a race resolves to
  single-fire semantics.
- `TurnReplayed` wire event (`type: "turn_replayed"`). Emitted once
  before the replayed prompt's turn so the UI can show "resuming
  prompt from previous session" instead of silently starting a turn
  the user did not just submit. Replays cleanly over the ring buffer
  so a mid-replay reconnect re-renders the banner.
- `SessionRunner._maybe_replay_orphaned_prompt()` runs once before
  the worker's first `queue.get()`. Scan is best-effort — any
  exception is logged and swallowed so a broken scan can never block
  a fresh runner from serving new prompts.
- Internal `_Replay` sentinel on the prompt queue so the worker
  distinguishes a replayed prompt (skip the user-row insert) from a
  fresh user submission. Prevents duplicate user rows that would
  confuse history and break reorg/dedup.
- `tests/test_runner_replay.py` — 12 tests pinning the contract at
  both the store-helper level (orphan detection, idempotent mark,
  closed-session guard) and the runner-integration level (first-boot
  replay, no-replay on fresh session, no double-replay across
  restarts, no duplicate user row, single `turn_replayed` event).

### Fixed

- Prompts submitted during a service restart are no longer lost.
  Every in-flight turn is now recoverable exactly once per boot; a
  second crash during the replayed turn surfaces to the user as a
  normal stop instead of an invisible silent failure.

## [0.6.0] - 2026-04-22

Directory Context System — foundation. Per-directory ground truth on
disk so any session landing in a tracked directory can read
`.bearings/` and know what's happening here instead of relying on
ephemeral chat memory. Directly addresses the Twrminal-transcript
failure mode where a session opened blind and improvised. Minor bump
because this is a new primitive, not a fix.

v0.6.0 ships the filesystem layer only — agent-prompt integration,
auto-onboarding on WS-open, and the `checks/on_open.sh` runner follow
in v0.6.1 / v0.6.2 / v0.6.3+. No existing code paths change; the new
surface is additive.

### Added

- New package `bearings.bearings_dir` with five Pydantic v2 schemas
  (`Manifest`, `State`, `EnvironmentBlock`, `Pending`,
  `PendingOperation`, `HistoryEntry`). Field caps ride on every
  descriptive string (`description` ≤ 500, history `summary` ≤ 200,
  list fields ≤ 64 entries) so a hand-edited or malicious file can't
  blow the per-turn prompt budget. `extra="forbid"` catches typos
  instead of silently dropping them.
- Atomic TOML IO (`bearings_dir.io`): tempfile + `os.replace` with
  `fsync` before rename on a single filesystem, plus `fcntl.flock`
  (shared for reads, exclusive for writes) so two sessions can't
  interleave a write. A corrupt TOML or Pydantic-invalid file is
  renamed to `corrupted-YYYYMMDDHHMMSS-<name>` with a `.reason`
  sidecar and treated as missing — the next session re-onboards
  cleanly instead of crashing. Windows is single-session-only; lock
  functions no-op there so dev on Windows still works.
- `history.jsonl` append/read helpers. Append-only JSONL keeps two
  writers safe without a flock (line-atomic on POSIX when each line
  fits in `PIPE_BUF`, which the 200-char summary cap ensures). A
  single corrupt line is skipped rather than failing the whole read.
- Seven-step onboarding ritual (`bearings_dir.onboard.run_onboarding`):
  (1) identify via project-root markers + README head,
  (2) `git status` / stashes / in-progress merge-rebase-cherry-pick-
  bisect markers, (3) environment — venv + `uv sync --locked
  --dry-run` freshness check + language version pins, (4) sibling
  clones under `$HOME/{Projects,code,dev,src}` matching remote,
  (5) unfinished-work grep + narrative-file reads + the **naming-
  inconsistency scan** that surfaces the Twrminal/Bearings class of
  drift as a *note, not a defect*, (6) tag-match against caller-
  supplied rows (no DB coupling — the CLI/WS handler owns the
  lookup), (7) structured `Brief` dataclass the caller renders.
  Pure read; writing is the caller's job.
- `bearings here init` — runs the ritual in CWD (or `--dir`), prints
  the brief, writes `manifest.toml` + `state.toml` + empty
  `pending.toml`. Pending is created empty so the flock target
  exists and a concurrent add doesn't race on creation.
- `bearings here check` — re-runs the cheap subset of the ritual
  (steps 2/3/5), bumps `state.toml.environment.last_validated`.
  Errors with a useful message when run before `here init`.
- `bearings pending add|resolve|list` CRUD with a full Python API in
  `bearings_dir.pending`. `add` is idempotent on name and preserves
  `started` across re-notices so the 30-day stale-op detection
  planned for v0.6.1 stays meaningful when a second session re-
  notices the same broken lockfile.
- 45 new tests across five files (`test_bearings_dir_{schema,io,
  pending,onboard,cli}.py`). Notable coverage: schema caps, corrupt-
  file quarantine (both TOML-parse and Pydantic-validate paths), a
  concurrent-writer race (20 rewrites from two threads — final file
  still parses), the Twrminal naming-inconsistency false-positive
  fixture, simulated-crash test that verifies `os.replace` failure
  preserves prior content with no stray tempfiles.

### Changed

- TODO.md `v0.4.x — Directory Context System (open)` heading
  retargeted to `v0.6.x` and its decisions + v0.6.0 items checked
  off. The `v0.4.x` label was drafted before Checklist Sessions
  claimed v0.4.0/0.4.1 and Slice 4 + polish took v0.5.0/0.5.1;
  Directory Context System slid to the next new-primitive minor
  slot.

## [0.3.29] - 2026-04-21

### Changed

- ContextMeter flash threshold retuned. v0.3.28 flashed past 32K
  tokens, which overstated Claude's long-context behavior — needle-
  in-a-haystack recall on Sonnet 4.x stays strong well past 100K,
  and Anthropic's own auto-compact default fires at ~80% of the
  window (≈160K). A 32K flash triggered on routine sessions and
  eroded the signal.
- Flash now rides on the existing red percentage band instead of a
  raw token count: ≥90% when auto-compact is on (≈180K on a 200K
  window), ≥80% when auto-compact is off (≈160K). That boundary
  already represents "auto-compact is imminent or the hard cap is
  right there," so the flash is "don't ignore this, it's been red"
  rather than a made-up degradation claim.
- Tooltip text updated: the degraded-state copy no longer claims
  recall degrades past 32K. Red-band tooltips now read
  `"Auto-compact imminent — checkpoint or fork now."` (compact on) or
  `"Near hard cap with no auto-compact safety net — act now."` (off).

### Removed

- `CONTEXT_DEGRADATION_THRESHOLD_TOKENS` constant in
  `ContextMeter.svelte`.

## [0.3.28] - 2026-04-21

### Changed

- ContextMeter pill now renders the raw context-token count alongside
  the percentage (`ctx 34.2k (17%)` instead of `ctx 17%`), making the
  absolute size visible at a glance.

### Added

- Flash-red warning on the ContextMeter when the current context
  window crosses 32K tokens. Empirically, Claude's recall degrades
  sharply past that threshold even when the nominal 200K cap is far
  off — the pill now forces the red band and pulses (0.83 Hz,
  WCAG-safe) so sessions in the degradation zone are obvious without
  reading the number. Reduced-motion users get a solid red band
  instead of the pulse via `motion-safe:animate-flash-red`.
- `ContextMeter.test.ts` — component previously had no unit coverage;
  new suite exercises the null placeholder, the token/percentage
  rendering under threshold, the exact-32K flash edge, and the red
  override of mid-percentage bands.

## [0.3.27] - 2026-04-21

### Added

- Session close / reopen lifecycle. Charters that have shipped can
  now be marked closed from the conversation header (the `✓` button
  after the merge `⇲` cluster); the sidebar sinks closed sessions
  into a collapsed `Closed (N)` group at the bottom of the list so
  live work stays on top. Reopen is symmetric and one click away
  inside the group.
- Migration `0015_session_closed_at.sql` adds a nullable
  `sessions.closed_at TEXT` column. Null = open (default), ISO
  timestamp = closed. Additive only; rolls forward cleanly on
  existing databases.
- `POST /api/sessions/{id}/close` and `/reopen` — dedicated
  lifecycle routes rather than a `PATCH` extension because the
  transition has side effects (auto-reopen on reorg) and the
  dedicated-route shape matches the existing `attach_tag` /
  `detach_tag` pattern. Both are idempotent: a second close
  refreshes the timestamp, a second reopen is a no-op.
- `SessionOut.closed_at` round-trips through session export /
  import so archived JSON preserves the closed flag.

### Changed

- Reorg move / split / merge routes auto-clear `closed_at` on any
  session that had work moved into or out of it. Rationale: if the
  charter is back in play, the flag is stale. Only real ops reset
  the flag — a no-op move (0 rows moved) leaves a closed session
  closed. Merge reopens both sides when the source survives and
  only the target when `delete_source=true`.
- `SessionList` splits its render into the main open `<ul>` plus a
  collapsible bottom group. The group's expanded state is local to
  the component and resets to collapsed each page load — deliberate,
  since a sticky preference is a separate prefs-store change.

### Notes

- 16 new pytest across store / routes / reorg (covering idempotent
  close, 404 on unknown ids, live-runner not dropped on close, and
  per-op auto-reopen semantics).
- 13 new vitest: 8 for the sessions store (`openList` /
  `closedList` derived + `close` / `reopen` happy + error paths)
  plus 5 for SessionList (group rendering, toggle, "No open
  sessions" placeholder when everything is closed).
- Import/export round-trip test (`test_import_session_round_trips_closed_at`)
  confirms the flag survives a full JSON round trip.

## [0.3.26] - 2026-04-21

### Added

- Session-description clamp in the conversation header. Long
  multi-paragraph plugs (design briefs, pasted bug reports) were
  eating half the viewport before the conversation even started.
  Tailwind `line-clamp-3` folds to three lines with a compact
  `⌄ show more` / `⌃ show less` toggle — the toggle only renders
  when the text actually overflows. Clamp state resets on session
  switch and re-measures after a description edit (pairs with the
  live-prompt-respawn hook from 0.3.25).

### Notes

- Companion piece to the 0.3.24 message-body fold: long content has
  a predictable fold affordance everywhere in the page — header
  plug, user paste, assistant turn.

## [0.3.25] - 2026-04-21

### Changed

- Runner auto-drop when prompt-layer fields change. The claude
  subprocess is spawned with `--system-prompt` baked in at launch,
  so in-place edits to `description`, `session_instructions`, or
  tag-memory content never reached a live runner without respawn.
  The affected runner(s) now drop from the registry so the next
  WebSocket turn rebuilds against the freshly-assembled prompt.
- `PATCH /sessions/{id}` drops the runner when `description` or
  `session_instructions` is in the request body; title-only and
  budget-only patches leave the runner alive.
- Tag attach / detach and tag-memory put / delete drop the runner
  for every affected session, since every session inheriting that
  tag's memory sees its prompt change.

### Notes

- Unblocks the 0.3.26 header clamp's re-measure behavior: editing
  the description from the header now propagates to the live agent
  on the next turn instead of lingering until the next reconnect.

## [0.3.24] - 2026-04-21

### Added

- `CollapsibleBody.svelte` — height-based fold around rendered
  markdown for user and assistant turns. Bodies taller than 480px
  clamp to that height with a mask-image fade and a `show full
  message` / `collapse` toggle. Expanded state persists per-message
  in `localStorage` (`bearings:msg:expanded:<id>`) so reloads and
  scroll-back don't re-collapse underfoot.

### Changed

- Streaming assistant turns bypass the fold so new tokens stay
  visible as they land — the fold only applies once the message
  has a final body.
- Tool-call group, thinking details, copy button, reorg menu,
  bulk-select checkbox, and shiki highlighting all unchanged;
  `MessageTurn.test.ts` stays green.

### Notes

- 7 new vitest (`CollapsibleBody.test.ts`). Closes the "Long user
  messages dominate the conversation viewport" TODO that motivated
  the 0.3.27 close / reopen feature (session 82c151f4).

## [0.3.23] - 2026-04-21

### Added

- `session_description` prompt layer injected into the assembled
  system prompt, slotted between `base` and `tag_memory`. The
  description blurb rendered beneath the Conversation header's
  title and tags now reaches the agent directly — empty-context
  agents orienting on "why am I here" can read the human-authored
  answer instead of guessing from conversation memory.

### Notes

- This is the feature surfaced when Dave asks `/get your bearings`:
  the charter at the top of the system prompt is this layer at
  work. Motivated the 0.3.27 close / reopen lifecycle so finished
  charters stop cluttering the sidebar.
- 4 new pytest in `test_prompt_assembler.py` covering the layer's
  presence, ordering, and the null-description bypass.

## [0.3.22] - 2026-04-21

### Added

- Tool-call-group warnings on reorg ops — Slice 7 (Polish) of the
  Session Reorg plan (`~/.claude/plans/sparkling-triaging-otter.md`).
  A new pure function `store.detect_tool_call_group_warnings` scans
  a proposed move for assistant/user pairs (tool_use + tool_result)
  that would be split across the boundary. The move route populates
  `warnings: [{code: 'orphan_tool_call', message, details}]` in the
  response; the split route does the same for its tail-move. Advisory
  only — the op still runs. Merge never produces these warnings
  because it moves every source row together.
- `ReorgUndoToast` now renders any advisory warnings as an amber
  block above the main message (`data-testid="reorg-undo-warning"`
  per row, tagged with `data-warning-code`). Absent / empty warnings
  keep the toast compact — no visual change on the common path.
- `bearings_session_reorg_total{op=move|split|merge}` Prometheus
  counter — exposed at `/metrics`. Only real ops bump the counter:
  idempotent no-op moves (0 rows changed) don't inflate it, matching
  the audit-row write behavior.

### Changed

- Slice 3/4/5 undo closures (`doMove`, `doBulkMove`, `doSplit`,
  `doMerge` in `Conversation.svelte`) now carry the response's
  `warnings` list into the `UndoState`. Merge always passes `[]`
  since the server never emits group-split warnings for merge.
- `routes_reorg.py` computes warnings BEFORE calling
  `move_messages_tx` so the scan sees both halves of any affected
  pair on the source; computing after would miss pairs whose
  halves were already split by the move itself.

### Notes

- 17 new pytest (354 total, up from 337): 9 unit tests for the
  warning detector's edge cases + 4 route-level warning tests + 4
  metric-increment tests (including "no-op move doesn't inflate").
- 2 new vitest (147 total, up from 145) for the new warning render
  branch in `ReorgUndoToast`.
- This ships the last of the Slice 7 "Polish" bucket's unblocked
  work. Slice 6 (LLM-assisted analyze) stays deferred — it's gated
  on token-cost Wave 3 (the sub-agent researcher) and Dave declined
  the fallback-LLM variant.

## [0.3.21] - 2026-04-21

### Added

- Merge route + persistent audit divider — Slice 5 of the Session
  Reorg plan (`~/.claude/plans/sparkling-triaging-otter.md`).
  `POST /api/sessions/{id}/reorg/merge` drains every message from
  a source session into a target (optionally deleting the source
  on success). Symmetric with the move/split routes — same undo
  window, same warnings shape, same `audit_id` in the response.
- `reorg_audits` table (migration `0014_reorg_audits.sql`) with
  columns `id`, `source_session_id`, `target_session_id`,
  `target_title_snapshot`, `message_count`, `op`, `created_at`.
  `source_session_id` cascades on source delete; `target_session_id`
  sets NULL on target delete so the divider can still render a
  "(deleted session)" fallback.
- `store.record_reorg_audit` / `list_reorg_audits` /
  `delete_reorg_audit` helpers + read routes
  `GET /api/sessions/{id}/reorg/audits` and
  `DELETE /api/sessions/{id}/reorg/audits/{audit_id}`.
- Move / split / merge responses now carry `audit_id: int | None`
  so the frontend can thread the id into its undo closure and
  delete the audit row on successful undo without a second round
  trip to list audits.
- `ReorgAuditDivider.svelte` — chronological divider rendered
  inline in the source conversation. Reads "Moved/Split off/Merged
  N message(s) to '<target title>' · <timestamp>". Target label is
  a clickable jump-button when `target_session_id` is present;
  italic "(deleted session)" fallback when null. Tagged with
  `data-audit-id` / `data-audit-op` for test queries.
- `⇲` Merge button in the session header (next to ✎/⇣/⎘/☐) opens
  `SessionPickerModal` with `allowCreate={false}` — merge always
  targets an existing session, never spins up a new one. Picker
  title adapts to "Merge this session into…".
- Frontend `TimelineItem` discriminated union interleaves turns and
  audit dividers sorted by timestamp — audit dividers render in
  the exact chronological slot where the op happened, not stapled
  to the top or bottom of the view.
- 23 new backend tests (337 pytest, up from 314) covering the
  merge route, audit recording on all three ops, audit list / delete
  routes, cascade + set-null FK behavior, and `audit_id` threading
  in response bodies. 7 new frontend tests (145 vitest, up from 138)
  for `ReorgAuditDivider` — verb-per-op, pluralization, jump
  callback, deleted-target fallback, null-snapshot fallback, data
  attributes.

### Changed

- `Conversation.svelte` now loads and refreshes a per-session
  `audits` list (via `$effect` keyed on the selected session's
  `updated_at`), interleaves audits into the rendered timeline,
  and threads `audit_id` + a `deleteAuditSafe` helper through
  every undo closure (`doMove`, `doBulkMove`, `doSplit`,
  `doMerge`). Undos that delete the target session skip the
  audit delete — the FK cascade does it.
- `doMerge` snapshots the source message IDs **before** calling
  `reorgMerge` so the undo can move exactly those rows back. The
  underlying `move_messages_tx` preserves each message's
  `created_at`, so "take the newest N on target" isn't a safe
  undo strategy.

## [0.3.20] - 2026-04-21

### Added

- Bulk-select mode — Slice 4 of the Session Reorg plan
  (`~/.claude/plans/sparkling-triaging-otter.md`). A `☐` toggle next
  to the session header's ✎/⇣/⎘ trio puts the conversation into
  bulk-select mode: each message row grows a checkbox, the per-
  message `⋯` menu tucks away, and a floating action bar anchors to
  the bottom of the viewport.
- `BulkActionBar.svelte` — floating bottom-center toolbar with
  "Move N…", "Split into new session…", and "Cancel" buttons. Bound
  keyboard shortcuts (`m` move, `s` split, `Esc` cancel) are ignored
  while an input/textarea holds focus so typing a prompt stays
  unaffected. Cmd/Ctrl/Alt + key combinations fall through to the
  browser unchanged.
- Shift-click range selection — clicking one checkbox and shift-
  clicking another selects the inclusive span between them, computed
  against the live `conversation.messages` index. Falls back to
  single-select if the anchor has scrolled out of the window since.
- Bulk Move opens the existing `SessionPickerModal` with the picker
  title adapted to the selection count ("Move 4 selected messages
  to…") and routes through a new `doBulkMove` helper shared by
  single-row moves, split-into-existing, and bulk ops. Undo reverses
  the move and (for move-to-new-session) deletes the freshly-created
  target so cancelled ops leave no sidebar residue.
- Bulk Split reuses the same picker but opens with
  `defaultCreating={true}` so the create-new-session form shows
  first. New `defaultCreating` prop added to `SessionPickerModal`.

### Changed

- `MessageTurn.svelte` now accepts optional `bulkMode`, `selectedIds`
  (a `ReadonlySet<string>`), and `onToggleSelect(msg, shiftKey)`
  props. Selected rows pick up an emerald border + tinted background
  so the selection is obvious at a glance. When `bulkMode` is true
  the per-message `⋯` menu is hidden in favor of the checkbox.
- Split-into-existing now routes through `doBulkMove` — previously
  had a bespoke copy of the move+undo closure. One code path, one
  undo shape.

### Fixed

- `MessageTurn` articles now expose `data-testid="user-article"` /
  `"assistant-article"` plus `data-message-id`, making the bulk-mode
  highlight test-addressable without needing to query by class.

## [0.3.19] - 2026-04-21

### Added

- Session reorg UI — per-message `⋯` menu on every user / assistant
  article in the conversation view exposes "Move to session…" and
  "Split here…". Slice 3 of the Session Reorg plan
  (`~/.claude/plans/sparkling-triaging-otter.md`), built directly on
  the v0.3.18 backend routes. Reveals on row hover + keyboard focus
  so it stays out of the way during normal reading.
- `SessionPickerModal.svelte` — searchable (title / working_dir /
  model), tag-filterable candidate list with an inline
  "create a new session" affordance (title + tags; other fields
  inherit from the source). Up/down arrow + Enter to confirm, Esc to
  cancel. The picker exposes two discriminated callbacks
  (`onPickExisting` / `onPickNew`) so the parent chooses the right
  backend path without re-parsing the draft.
- `ReorgUndoToast.svelte` — 30-second grace window after a reorg.
  Bottom-right toast shows `Undo (Ns)` and runs an inverse move on
  click; dismisses on timeout, explicit ×, or a successful undo.
  Split's inverse pulls the moved messages back into the source and
  deletes the freshly-orphaned target session so a cancelled split
  leaves no sidebar residue.
- `reorgMove()` and `reorgSplit()` in `$lib/api/sessions.ts` with
  `ReorgMoveResult` / `ReorgSplitResult` / `NewSessionSpec` types.
  Mirrors the v0.3.18 Pydantic shapes; `warnings: []` is surfaced so
  Slice 7 can populate it without another type-plumbing round.

### Changed

- `MessageTurn.svelte` gained optional `onMoveMessage` and
  `onSplitAfter` callbacks. When either is provided, each rendered
  user / assistant article picks up a hover-revealed `⋯` trigger with
  an outside-click-dismissed popover. Existing callers that don't
  wire the props keep the exact previous render.
- `Conversation.svelte` orchestrates the reorg flow end-to-end: opens
  the picker on menu click, dispatches to move vs. split based on the
  menu choice, reconciles sidebar + active-session state after the
  round-trip, and presents the undo toast. Move-to-a-brand-new
  session creates the row via `api.createSession` directly (not
  `sessions.create`) so the selection doesn't flicker away from the
  session the user is currently triaging.

12 new Svelte component tests across `SessionPickerModal.test.ts`
and `ReorgUndoToast.test.ts`. 125 frontend tests pass (up from 113).
Backend is unchanged — 314 tests still green, ruff + mypy strict
clean.

## [0.3.18] - 2026-04-21

### Added

- Session reorg routes — `POST /api/sessions/{id}/reorg/move` and
  `POST /api/sessions/{id}/reorg/split`. Move cherry-picks specific
  message ids from the source into an existing target; split anchors
  on a message id and relocates everything chronologically after it
  into a newly-created session. Split's `new_session.model` and
  `new_session.working_dir` are optional — omitted values inherit
  from the source so "split this thread off" doesn't force the
  caller to re-specify defaults the source already carries. Tag ids
  are required on split (≥1, matching the v0.2.13 session-creation
  gate) and are validated before the session row is written.
- Runner-stop side effect. Both routes call `runner.request_stop()`
  on any live runner attached to an affected session so the SDK's
  in-memory context rebuilds against the new DB state on the next
  turn. Move stops both sides; split stops only the source (the new
  session is fresh and has no runner yet). v0.3.15 priming is the
  belt to this stop's suspenders.
- `ReorgWarning` / `ReorgMoveResult` / `ReorgSplitResult` Pydantic
  shapes in `api/models.py`. `warnings` is always returned as `[]` in
  v0.3.18; Slice 7 (Polish) will populate it with tool-call-group
  split detection without changing the API shape. `NewSessionSpec`
  lives alongside — similar to `SessionCreate` but with optional
  `model` / `working_dir` for the inherit-from-source path.

Slice 2 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`); composed entirely
on top of the Slice 1 `store.move_messages_tx` primitive from
v0.3.17. 15 new tests in `tests/test_routes_reorg.py` (7 for move, 8
for split, including the runner-stop assertions). 314 backend tests
pass (up from 299). Ruff + mypy strict green.

## [0.3.17] - 2026-04-21

### Added

- `move_messages_tx()` primitive in a new `src/bearings/db/_reorg.py`
  module. Atomically moves a set of message rows from one session to
  another in a single transaction. Tool calls anchored to a moved
  message (via `tool_calls.message_id`) follow their message; orphan
  calls (null `message_id`) stay with the source. Both sessions'
  `updated_at` bump only when at least one row actually moves, so a
  no-op idempotent re-run doesn't perturb sidebar ordering.
  `sessions.message_count` is a subquery-derived column, so the next
  `list_sessions` read reflects the move with no recompute step in
  the primitive itself. Raises `ValueError` on `source == target` or
  missing target session; tolerates unknown ids by skipping them.
  Slice 1 of the Session Reorg plan
  (`~/.claude/plans/sparkling-triaging-otter.md`) — Slice 2
  (move/split routes) builds on this. 299 backend tests pass (up from
  289; 10 new in `test_db_reorg.py`). Ruff + mypy strict green.

## [0.3.16] - 2026-04-21

### Added

- Context-pressure meter (Wave 1 of the token-cost-mitigation plan).
  `get_context_usage()` is captured inside the SDK client's
  `async with` and shipped as a `ContextUsage` WebSocket event
  emitted BEFORE `MessageComplete` — the runner breaks its loop on
  `MessageComplete`, so anything after that never reaches the UI.
  Last snapshot persists on the session row (migration 0013:
  `last_context_pct`, `last_context_tokens`, `last_context_max`)
  and seeds the frontend store on `load()` so the meter paints on
  first render instead of flickering between turns. Threshold bands
  shift one earlier when auto-compact is off since there's no
  safety net catching overflow.
- Pre-submit budget gate. `submit_prompt()` refuses a turn when
  `total_cost_usd >= max_budget_usd`, emitting an `ErrorEvent`
  rather than queueing. The SDK's `max_budget_usd` advisory fires
  post-hoc — after tokens are spent — so an already-over-cap
  session could still kick off one more turn without the pre-check.

### Notes

- 7 new backend tests (289 → 296). Frontend: 113 vitest cases,
  svelte-check clean.

## [0.3.15] - 2026-04-21

### Fixed

- Cold-context reconnect into a live research session. The SDK's
  `resume=<sdk_session_id>` path fails silently when the session
  file is gone, the cwd has drifted, or the system prompt has
  changed. Belt-and-suspenders fallback: once per `AgentSession`
  instance (first turn after a cold runner build only), prepend a
  compact `<previous-conversation>` preamble built from the last
  10 persisted messages, each truncated to 2000 chars. SDK resume
  hint still rides along — if it works, we've merely duplicated
  the tail; if it fails, the model still has immediate context.
- The preamble only fires when the DB has prior turns AND they're
  not just the current turn's own user row (runner persists the
  user message before calling `stream()`). Subsequent turns rely
  on the SDK's own context chain — priming every turn would waste
  tokens.

## [0.3.14] - 2026-04-21

### Added

- Idle-runner reaper. `RunnerRegistry` now evicts `SessionRunner`
  instances that have been "quiet" (no turn in flight AND no
  WebSocket subscribers) longer than `runner.idle_ttl_seconds`
  (default 900s / 15 min). Frees the worker task + 5000-slot ring
  buffer for sessions the user hopped into once and walked away
  from, so a long-lived server doesn't accumulate one runner per
  session ever opened. The runner is recreated on the next WS
  connect; `sdk_session_id` is persisted so the resumed turn still
  has full CLI history. Set `runner.idle_ttl_seconds = 0` in
  `~/.config/bearings/config.toml` to restore v0.3.13 behavior
  (runners live until delete or server restart).

### Fixed

- `bearings.__version__` was pinned at `0.3.9` while
  `pyproject.toml` advanced through `0.3.10`–`0.3.13`, so
  `/api/health` reported a stale version. Synced both to the new
  `0.3.14` release.

## [0.3.13] - 2026-04-21

### Added

- Desktop/tray notifications when an agent turn finishes. Opt-in
  under Settings → "Notify when Claude finishes replying". Enabling
  triggers the browser's permission prompt in-place; once granted,
  every subsequent `message_complete` event raises a native
  notification while the Bearings tab is hidden or unfocused.
  Clicking the notification focuses the window. Notifications carry
  the session title in the body and a per-session dedup tag so a
  fast sequence of turns replaces rather than stacks in the tray.
  Works everywhere browser notifications work on Linux (KDE Plasma,
  mako under Hyprland, GNOME Shell) — the DE handles the render.

## [0.3.7] - 2026-04-20

### Reverted

- Reverts the v0.3.6 "quadratic inflation" fix. The premise was
  wrong — `claude-agent-sdk`'s `ResultMessage.total_cost_usd` is
  **per-turn**, not cumulative (verified empirically: a single
  resumed Opus turn on a real Bearings session reports ~$0.74 with
  `num_turns=1`). The original `store.add_session_cost` was already
  correct; 0.3.6's delta/reset-detection math over-counted.
- Leaves migration 0011 in place (schema forward-only) but stops
  using the `sdk_reported_cost_usd` column. Historical `total_cost_
  usd` values that 0011 zeroed are unrecoverable — per-turn deltas
  were never recorded. Forward accumulation is correct again.
- Known limitation acknowledged in code: large Opus sessions can
  show meaningful per-turn cost ($0.5–$2) because each turn spins
  up a fresh CLI with the full resumed history; that's real spend,
  not a bug.

## [0.3.6] - 2026-04-20

### Fixed

- Per-session `total_cost_usd` no longer inflates quadratically.
  `claude-agent-sdk`'s `ResultMessage.total_cost_usd` is cumulative
  for the resumed CLI session, but the old accumulator added it raw
  on every turn — so after N uniform-cost turns the row reported
  ≈ N(N+1)/2 × the actual spend. New column `sdk_reported_cost_usd`
  tracks the last cumulative; the runner subtracts it to get a
  per-turn delta before bumping `total_cost_usd` and re-emitting the
  `message_complete` wire event. Migration 0011 resets every
  `total_cost_usd` to 0 — historical per-turn deltas were never
  recorded, so the next turn on any resumable session re-seeds the
  total from the SDK's own (correct) cumulative.

  **Note (0.3.7):** premise was wrong — reverted.

## [0.2.13] - 2026-04-19

Closes out v0.2. Enforces the "every session has ≥1 tag" rule at
the API boundary and the new-session UI, adds attached-tag chips
to the Conversation header, and rewrites the README for the
tags-only design.

### Added

- `SessionCreate.tag_ids: list[int] = []` — POST /api/sessions
  requires at least one id. The route validates that every tag id
  exists (400 on empty or on any missing tag), inserts the session,
  then attaches the tags.
- SessionList new-session form: attached-tag chips with ✕, inline
  input that filters global tags (click to attach, Enter on a
  novel name to create-and-attach, same UX as SessionEdit).
  Submit disabled + tooltip until ≥1 tag is attached.
- Attaching a tag with defaults to the form pre-fills
  `working_dir` / `model` (precedence = canonical tag order, last
  wins). Opening the form seeds the chip list from the active
  sidebar tag filter.
- Conversation header tag chip row — pinned-first tag order, with
  ★ on pinned, rendered under the model/working_dir/cost line.
  Hover title shows the tag's defaults when present.
- README rewritten end-to-end for v0.2: tags as the one primitive,
  tag memories with sort-order-wins precedence, tag defaults, ≥1
  tag rule, and layer inspection via the Inspector Context tab.

### Changed

- `store.create_session` is unchanged (still tag-agnostic) — the
  enforcement is at the HTTP boundary so internal callers
  (`import_session`, direct store usage in tests that exercise the
  prompt assembler, etc.) can still create tag-less rows.
- All test helpers (`test_routes_sessions._create`, `_create_session`
  in `test_tags` / `test_ws_agent` / `test_tag_memories`, ad-hoc
  POSTs in `test_auth`, `test_metrics`, `test_routes_history`) auto-
  seed a `default` tag per test client and include its id.
- `tests/test_routes_sessions.py` gets 2 new cases pinning the
  enforcement: empty `tag_ids` → 400, unknown tag id → 400.

### Why

Tags were already the organizational primitive post-teardown.
Without the gate, a session could exist with no context hooks at
all — no memories, no defaults, nothing distinguishing it. The
rule makes the one-primitive design honest: there's always at
least one tag carrying context for the agent.

## [0.2.12] - 2026-04-19

Session instructions inline editor inside the Inspector Context
tab. The session layer is the last one in the assembled prompt —
always wins — so this is the knob users reach for when they want
a one-off override without touching tags.

### Added

- Inline textarea under the Context layer list. Pre-hydrates from
  `sessions.selected.session_instructions` on session change; user
  edits don't propagate to the server until Save is clicked.
- Reset button appears when the draft is dirty.
- Save calls `sessions.update(sid, { session_instructions: ... })`
  (PATCH-backed). Empty content saves as null (clears the
  instructions). After save, the Context pane re-fetches the
  system prompt so the `session` layer reflects the new value
  immediately.
- Hydration effect keyed on `instructionsLoadedFor === sel.id` so
  `sessions.refresh()` / `bumpCost` mid-edit don't wipe the
  draft. Switching sessions discards the prior draft.
- Inspector's updated_at-watch effect now also actively re-fetches
  the system prompt when the pane is open (not just invalidating
  on next open). Picks up tag-memory edits from the TagEdit modal
  without requiring the user to close and reopen Context.
- Removed the dead `project` case in `layerBadgeClasses` (tidy
  followup to v0.2.9 teardown).

### Why

Tags carry shared rules; session_instructions are the escape
hatch for a single session. Having it in the Context tab, next to
the assembled layer view, makes the precedence visible: everything
above is inherited from tags / the base, this box is you.

## [0.2.11] - 2026-04-19

Tag editor modal — the first surface for editing a tag's full
contents from the UI. Covers name, pinned, sort_order, memory
(markdown + live preview), default working dir, default model.

### Added

- `frontend/src/lib/components/TagEdit.svelte` — modal editor
  reachable from a hover-reveal ✎ button on each sidebar tag row.
  Loads the current tag's memory on open (GET /memory, 404 → no
  memory yet). Save path diffs memory state: empty after a non-
  empty load → DELETE; non-empty → PUT. Tag metadata (name,
  pinned, sort_order, defaults) go through tags.update (PATCH).
- Preview toggle flips the memory textarea to a `renderMarkdown`
  pane using the same Shiki-backed renderer as the conversation
  pane.
- "If multiple tags have conflicting rules, later tags (lower in
  the sidebar sort order) override earlier ones." hint sits
  beneath the memory editor, matching the spec.
- Delete button with two-click confirm, consistent with the
  sidebar session-delete pattern.
- `api.getTagMemory` / `putTagMemory` / `deleteTagMemory` TS
  helpers + `TagMemory` type.
- SessionList tag rows grew a hover-reveal ✎ affordance — hover
  the row, click to edit.
- `TagEdit.test.ts` — 5 cases: existing memory loads, 404 is
  silent, save-with-content PUTs memory, save-after-clear
  DELETEs memory, preview toggle renders markdown.

## [0.2.10] - 2026-04-19

Tag defaults — `default_working_dir` and `default_model` per tag.
Replaces what projects were going to do for new-session pre-fill.
First slice after the v0.2.9 teardown.

### Added

- Migration `0009_tag_defaults.sql`: adds `default_working_dir`
  and `default_model` TEXT columns to `tags` (both nullable).
- `store.create_tag` / `update_tag` accept the new fields. The
  update allowed-set grew by both columns; unset preserves, null
  clears.
- `TagCreate` / `TagUpdate` / `TagOut` expose the new fields.
- Frontend `Tag` / `TagCreate` / `TagUpdate` TS types match.
- New-session form pre-fills from the sidebar's active tag filter:
  when one or more tags are filter-selected, the form pulls
  `default_working_dir` and `default_model` from the highest-
  precedence tag (canonical list order, last wins — same rule as
  tag-memory precedence). Falls back to user prefs, then to the
  prior form value. No tag defaults, no behavior change.
- 5 new pytest cases in `tests/test_tags.py` (store create with
  defaults, null defaults, update set+clear, POST accepts, PATCH
  sets).

### Why

Projects were going to carry per-project defaults. With projects
torn down, tags now carry them. A pinned `bearings` tag with
`default_working_dir = ~/Projects/Bearings` and
`default_model = claude-opus-4-7` gives the same new-session pre-
fill behavior a project would have given — one click to filter
the sidebar to that tag, then `+ New` has the fields ready.

### Gaps

- No in-app UI to set tag defaults yet. Lands in v0.2.11 (tag
  editor modal), alongside the memory editor.
- Tag attach at session-create time is still v0.2.13. For now the
  pre-fill is driven only by the sidebar tag filter. A user who
  wants to create a session under a tag must filter to it first.

## [0.2.9] - 2026-04-19

Teardown of projects. Course correction — projects were the wrong
primitive. Tags with memories (already shipped in v0.2.7) carry
the role; tag-level `default_working_dir` and `default_model`
land in v0.2.10 to close the gap. Pinned tag = "project". See
`V0.2.0_SPEC.md` (rewritten this slice).

### Removed

- Migration `0008_drop_projects.sql`: wipes existing sessions
  (none in production at teardown time, per Dave's call), drops
  `idx_sessions_project`, drops `sessions.project_id` column
  (SQLite 3.35+ DROP COLUMN), drops the `projects` table.
- `src/bearings/api/routes_projects.py` — entire file.
- `src/bearings/db/store.py` — `create_project` / `list_projects`
  / `get_project` / `update_project` / `delete_project` and their
  helper constants. `NO_PROJECT` sentinel + `ProjectFilter` alias.
- `ProjectCreate` / `ProjectUpdate` / `ProjectOut` DTOs.
- `SessionCreate.project_id` / `SessionUpdate.project_id` /
  `SessionOut.project_id` (backend + frontend TS).
- `GET /api/sessions?project_id=` query filter.
- Project layer in `agent/prompt.py`. The assembler is now 3-layer:
  base → tag memories → session instructions.
- `tests/test_projects.py` and `tests/test_migration_0007.py`
  (the latter asserted the post-0007 shape which no longer matches
  end state; the 0007 migration file itself stays in
  `migrations/` so `schema_migrations` stays consistent).
- Frontend `Session.project_id` field.

### Changed

- `V0.2.0_SPEC.md` rewritten to describe the tags-only design.
  The old projects-included version led this slice's teardown —
  preserved only in git history.
- `db/schema.sql` reconciled — no `projects` table, no
  `project_id` column, no `idx_sessions_project`.
- Prompt-assembler tests trimmed to match the 3-layer shape.
- System-prompt API test trimmed to match.

### Why

Tags carry shared system-prompt content (as memories), shared
working-dir defaults, shared model defaults, and sidebar-pin
behavior. A pinned `bearings` tag IS the Bearings project.
Maintaining a second "projects" primitive alongside that was
duplicating surface for no additional capability. Cheaper-than-
expected memory stacking (short pointers, not mirrored document
libraries) closed the gap that projects were meant to fill.

## [0.2.8] - 2026-04-19

Inspector Context tab — read-only view of the assembled system
prompt. Ninth v0.2 slice, spec step 6.

### Added

- `GET /api/sessions/{id}/system_prompt` returning
  `{layers, total_tokens}`. Layers carry `{name, kind, content,
  token_count}` — calls the same `assemble_prompt` the agent uses
  so the Inspector always shows current prompt state. 404 if the
  session doesn't exist.
- `SystemPromptLayerOut` / `SystemPromptOut` DTOs.
- `agent.prompt.estimate_tokens` — coarse 4-chars-per-token
  approximation. Avoids pulling `tiktoken` (heavy dep) for what's
  a visual-only estimate; empty strings count as zero, anything
  else is clamped to at least 1 so non-empty layers aren't
  rendered as 0 tokens.
- Frontend `getSystemPrompt(sessionId)` + `SystemPrompt` /
  `SystemPromptLayer` types.
- Inspector panel: new **Context** disclosure above the existing
  Agent one. On open, fetches the assembled prompt; header shows
  `~N tok`. Each layer renders as a collapsible row with a
  color-coded kind badge (base/project/tag_memory/session). When
  the selected session's `updated_at` changes the next open
  refetches so project/tag/memory edits surface immediately.
- Frontend `Session` type grew `project_id` and
  `session_instructions`. `SessionCreate` accepts `project_id`;
  `SessionUpdate` accepts `project_id` + `session_instructions`.
  Catches the frontend contracts up to the v0.2.6/v0.2.7 backend
  additions — no UI for these edits yet (v0.2.9 / v0.2.11).
- 3 new prompt-assembler tests for `estimate_tokens`.
- 3 new API tests for `/system_prompt` (404, base-only layer
  shape, full four-layer stack).

## [0.2.7] - 2026-04-19

Tag memories backend + `session_instructions` PATCH + wires the
v0.2.5 prompt assembler into the live agent. Eighth v0.2 slice,
spec step 5. Backend is now feature-complete for v0.2; remaining
slices (0.2.8+) are UI.

### Added

- `store.get_tag_memory` / `put_tag_memory` (upsert via `ON
  CONFLICT`) / `delete_tag_memory`. `put` returns None if the tag
  doesn't exist so the route can render 404 without an FK
  violation.
- `/api/tags/{id}/memory` CRUD: `GET` 200 | 404, `PUT` 200 | 404
  (body: `{content}`), `DELETE` 204 | 404. `TagMemoryOut` and
  `TagMemoryPut` DTOs.
- `PATCH /api/sessions/{id}` accepts `session_instructions` — new
  value, or explicit null to clear. `SessionOut.session_instructions`
  exposed on every session response.
- `SessionUpdate.session_instructions` field (Pydantic
  distinguishes unset from explicit null via `model_fields_set`,
  same as the existing nullable columns).
- `store.update_session` `allowed` set grew by
  `session_instructions`.
- `_SESSION_BASE_COLS` includes `session_instructions` so every
  session read (get, list, export) carries it.
- `AgentSession` accepts an optional `db` connection. When set,
  `stream()` calls `assemble_prompt(db, session_id)` per turn and
  passes `system_prompt=<layered text>` to `ClaudeAgentOptions`.
  Edits to project prompts, tag memories, or session instructions
  take effect on the next prompt without restarting the WS. Tests
  that don't exercise persistence leave `db=None` and behave as
  before (no `system_prompt`).
- `ws_agent.py` passes the lifespan-owned DB connection into
  `AgentSession` at construction.
- 13 new store + API tests in `tests/test_tag_memories.py` plus 1
  session-instructions PATCH round-trip.
- 2 new agent-session tests verifying system_prompt is assembled
  from project / tag memory / session instructions when db is
  wired, and stays None when it isn't.

### Changed

- `store.delete_project` is unchanged — cascade to SET NULL on
  `sessions.project_id` was already exercised by v0.2.4's
  migration test. `delete_tag` already cascaded to `tag_memories`
  via FK from migration 0007; new test pins the behavior.

## [0.2.6] - 2026-04-19

Projects backend — store CRUD + REST + session filter. Seventh v0.2
slice, spec step 4. Frontend for projects lands in v0.2.9.

### Added

- `store.create_project` / `list_projects` / `get_project` /
  `update_project` / `delete_project` with `session_count` rollup and
  canonical pinned-first / sort_order / id ordering (mirrors tags).
- `/api/projects` CRUD: `GET` (list), `POST` (201; 409 on duplicate
  name), `GET /{id}`, `PATCH /{id}` (409 on duplicate rename, 404 on
  missing), `DELETE /{id}` (204; sessions' `project_id` becomes NULL
  via `ON DELETE SET NULL`).
- `ProjectCreate` / `ProjectUpdate` / `ProjectOut` DTOs.
- `SessionOut.project_id` — exposed on every session response.
- `POST /api/sessions` accepts `project_id` at creation time.
- `PATCH /api/sessions/{id}` accepts `project_id` (explicit null
  clears the assignment).
- `GET /api/sessions?project_id=<id>` filter. `project_id=none`
  restricts to sessions with no project. Non-integer non-`none` → 400.
- `store.list_sessions(project_id=...)` composes with tag filters
  (both AND'd together; refactored from three branches to one
  dynamic WHERE builder).
- `store.NO_PROJECT` sentinel + `store.ProjectFilter` alias so
  routes don't reinvent the parsing rule.
- 23 new pytest cases covering store CRUD, session_count rollup,
  ordering tiebreakers, cascade-to-SET-NULL, project + tag filter
  composition, and the full REST surface.

## [0.2.5] - 2026-04-19

Layered system-prompt assembler — pure function, no consumers yet.
Sixth v0.2 slice, spec step 3. `AgentSession` wires through in
v0.2.7 once tag-memory + session-instructions CRUD land.

### Added

- `src/bearings/agent/prompt.py::assemble_prompt(conn, session_id)`
  — async, pure SQL reads, returns `AssembledPrompt(layers, text)`.
  Layer order: `base` → `project` (if the session's project has a
  non-null `system_prompt`) → `tag_memory` layers (one per attached
  tag with a `tag_memories` row, in the canonical `pinned DESC,
  sort_order ASC, id ASC` order; tag-without-memory is silently
  skipped) → `session` (`sessions.session_instructions`, when set).
  `text` joins the layers with `<!-- layer: kind[name] -->` headers
  so downstream renderers can split them back out.
- `src/bearings/agent/base_prompt.py::BASE_PROMPT` — short,
  deterministic base layer. Real content lives in project / tag /
  session layers.
- 8 new pytest cases in `tests/test_prompt_assembler.py`: base-only,
  missing session, project-with-prompt, project-without-prompt,
  tag-without-memory skip, pinned/sort_order/id tiebreakers,
  session_instructions-last, per-layer header verbatim.

## [0.2.4] - 2026-04-19

Schema migration **0007** — projects, tag memories, session
instructions. Fifth v0.2 slice. No routes yet; CRUD + prompt
assembly land in v0.2.5+.

### Added

- Migration `0007_projects_and_memories.sql`:
  - `projects` (id, name UNIQUE, description, system_prompt,
    working_dir, default_model, pinned, sort_order, created_at,
    updated_at).
  - `sessions.project_id INTEGER REFERENCES projects(id) ON
    DELETE SET NULL` + `idx_sessions_project`.
  - `tag_memories` (tag_id PK/FK, content, updated_at), FK
    `ON DELETE CASCADE` tied to `tags`.
  - `sessions.session_instructions TEXT` nullable — session-level
    override for the assembled system prompt (prompt assembler
    lands in v0.2.5).
- Canonical `db/schema.sql` caught up to the full applied shape
  (tags, session_tags, projects, tag_memories).
- 4 new pytest cases: migration applies (tables + index), columns
  present on `sessions`, project delete NULLs `sessions.project_id`,
  tag delete cascades `tag_memories` rows.

## [0.2.3] - 2026-04-19

Sidebar **click-filter** — fourth v0.2 slice. Closes out the
tag-primitives UI surface that started in v0.2.0. Full spec build
order step 1 (both back- and front-end) is now shipped.

### Added

- `GET /api/sessions?tags=1,2&mode=any|all` — optional filter on
  the session list. `mode="any"` matches sessions carrying any of
  the listed tags; `mode="all"` requires every listed tag. Empty /
  omitted `tags` returns the unfiltered list unchanged. Bad `tags`
  (non-integer) → 400.
- `store.list_sessions(tag_ids=, mode=)` extended to run the join
  + GROUP BY / DISTINCT path when filtering.
- `api.ts` `listSessions` now takes an optional `SessionFilter`;
  the sessions store caches the last-applied filter.
- `tags` store gets `selected: number[]`, `mode: 'any' | 'all'`,
  `toggleSelected()`, `clearSelection()`, plus derived `hasFilter`
  + `filter`.
- Sidebar tag rows become toggle buttons (emerald tint when
  selected), an Any/All toggle sits next to the "Tags" header, and
  a "Filter: N tag(s) ✕" pill appears when the filter is active —
  click to clear.
- SessionList watches the filter and re-fetches sessions on change.
- 5 new pytest cases (store any/all, store empty-filter, API happy
  path, API 400 on bad tags). 3 new vitest cases (toggle, derived
  filter, clearSelection).

## [0.2.2] - 2026-04-19

Attach/detach tags on a session. Third v0.2 slice — first path for
actually putting tags onto something from the UI. Sidebar
click-filter lands in v0.2.3.

### Added

- `TagCreate` / `TagUpdate` types + `createTag` / `updateTag` /
  `deleteTag` / `attachSessionTag` / `detachSessionTag` in
  `frontend/src/lib/api.ts`. The `deleteTag` helper handles the 204
  No Content response explicitly (the shared `jsonFetch` path
  assumes a JSON body).
- Mutation methods on the `tags` store: `create()`, `update()`,
  `remove()`, plus `bumpCount()` for post-attach/detach sidebar chip
  updates without a full refresh.
- **Tags section** in the SessionEdit modal: attached tags render
  as chips (with ★ on pinned) with an ✕ to detach. An input below
  filters global tags by name; click a suggestion to attach, or
  press Enter on a novel name to create-and-attach in one step.
- `SessionEdit.test.ts` covers detach via ✕, suggestion-click
  attach, and the Enter-to-create path.
- Extended `tags.svelte.test.ts` covers `create`, `remove`, and
  `bumpCount` including the clamp-at-zero rule.

## [0.2.1] - 2026-04-19

Sidebar **Tags panel** — read-only. Second v0.2 slice.

### Added

- `Tag` type + `listTags` / `listSessionTags` helpers in
  `frontend/src/lib/api.ts`.
- New `frontend/src/lib/stores/tags.svelte.ts` with a `TagStore`
  singleton (mirrors the shape of `sessions.svelte.ts`).
- Tags section in `SessionList.svelte`: "Tags" header above the
  session list, pinned tags first (with a ★ glyph), then a divider,
  then unpinned. Each row shows a right-aligned session-count chip.
  Section is hidden while sidebar search is active and when no tags
  exist. No click/filter behavior yet — that lands in v0.2.2.
- `+page.svelte` boot now refreshes sessions and tags in parallel
  (`Promise.all`).
- Store test `tags.svelte.test.ts` (success + error path).

## [0.2.0] - 2026-04-19

First v0.2 slice — **tag primitives**. Backend-only: establishes the
global `tags` registry + `session_tags` join table that the sidebar
Tags panel (v0.2.1) and eventual tag memories (v0.2.6+) build on.

### Added

- **Tag primitives.** New migration `0006_tag_primitives.sql` creating
  `tags` (id, name UNIQUE, color, pinned, sort_order, created_at) and
  `session_tags` (session_id, tag_id, created_at). Both FKs cascade
  on delete. `idx_session_tags_tag` keeps per-tag lookups fast.
- **Tag store helpers** in `db/store.py`: `create_tag`, `list_tags`,
  `get_tag`, `update_tag` (partial), `delete_tag`, `attach_tag`
  (idempotent `INSERT OR IGNORE`), `detach_tag`, `list_session_tags`.
  `list_tags` returns a `session_count` rollup per tag; all tag reads
  order pinned-first, then ascending `sort_order`, then `id`.
- **Tag REST surface** (`/api/tags/*`): `GET`, `POST` (201, 409 on
  duplicate name), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` (204).
- **Session-tag endpoints** on the sessions router: `GET
  /api/sessions/{id}/tags`, `POST /api/sessions/{id}/tags/{tag_id}`,
  `DELETE /api/sessions/{id}/tags/{tag_id}`. Attach/detach bumps
  `sessions.updated_at` so a tagged session floats to the top.
- New DTOs `TagCreate`, `TagUpdate`, `TagOut` in `api/models.py`.
- 25 new tests in `tests/test_tags.py` covering migration shape,
  CRUD round-trips, idempotent attach, cascade on tag delete and
  session delete, unique-name 409, ordering, and every new endpoint
  including missing-session and missing-tag paths.

### Fixed

- `db/schema.sql` now includes the `sessions.description` column
  from v0.1.40 (previously missed during that slice's canonical-file
  update). Schema file is back in sync with applied migrations.

## [0.1.40] - 2026-04-19

### Added

- **Editable session descriptions.** New `description TEXT` column on
  `sessions` (migration `0005_session_description.sql`) surfaces a
  free-form context note for each session — longer than the title,
  shorter than the conversation. Wired through `SessionCreate` /
  `SessionUpdate` / `SessionOut`, a new textarea in the SessionEdit
  modal, and a subtle render under the Conversation header subtitle
  when set. Preserved through the v0.1.30 export/import shape.
- Three new route tests: description round-trip, patch-update,
  patch-null clears.

## [0.1.39] - 2026-04-19

Docs/housekeeping only — no code change. Brings the two pieces of
project documentation that drifted during the v0.1 sprint back in
line with reality.

### Changed

- `README.md` rewritten: removed the "v0.1.0 scaffold… stubbed" prose
  that had survived 38 shipped versions, added a Features summary
  (streaming, CRUD, import/export, auth, budgets, metrics, search,
  shortcuts, CLI `send`), and widened the config table to cover
  `auth.token`.
- `TODO.md` reconciled: the three "v0.1.7+" stragglers (auth gate,
  graceful shutdown, budget cap) had all shipped — ticked and moved
  under a "Stale items resolved in earlier slices" subsection with
  pointers to the slice that landed each one.

## [0.1.38] - 2026-04-19

Closes out v0.1. Two tweaks and the first testing-notes pass.

### Changed

- Prompt send rebound: **Enter sends, Shift+Enter newlines** (was
  `⌘/Ctrl+Enter` / Enter newline). IME composition respected.
  CheatSheet and placeholder updated to match.

### Added

- Inspector "Agent" disclosure: tool-call list now nested under a
  collapsible `<details>` summary showing the session model + a
  running count badge. Auto-follows scroll to the latest tool call
  while the agent is streaming (effect watches
  `conversation.toolCalls.length` + `streamingActive`).
- `TESTING_NOTES.md` at the project root — session-by-session log of
  what Dave found and what got fixed.

## [0.1.37] - 2026-04-19

### Added

- Multi-file session import: drop a directory's worth of
  `session-*.json` onto the sidebar (or pick several in the ⇡ file
  dialog) and they import serially. `<input type="file" multiple>`
  is set on the hidden picker; `onDrop` reads every file from
  `dataTransfer.files`.
- `Importing N of M…` emerald status line while the loop runs.
  Per-file failures collect and render as `name: error; name: error`
  in the existing rose-colored error banner; successes land in the
  sidebar with the last-imported selected.

## [0.1.36] - 2026-04-19

### Added

- Drag-drop a `session-*.json` onto the Sessions sidebar to import
  — matches the ⇡ button but skips the file picker. Emerald
  ring + "Drop session JSON to import" overlay while a drag is
  over the aside. `dragleave` is scoped to the aside so crossing
  into child elements doesn't flicker the overlay.
- Import file-reading logic extracted into `importFromFile(file)`
  shared by the ⇡ click-handler and the drop handler.

## [0.1.35] - 2026-04-19

### Added

- `POST /api/sessions/import` — consumes the v0.1.30 export shape
  (`{session, messages, tool_calls}`) and restores it as a new
  session. Generates fresh ids for the session, every message, and
  every tool call; preserves content / role / thinking / timestamps;
  remaps `tool_calls.message_id` through an id-translation table.
  Resets `total_cost_usd` to zero (restores don't count as spend).
  Returns 400 on missing / malformed `session` key.
- `store.import_session(conn, payload)` helper — single-transaction
  writeback.
- ⇡ button in sidebar header opens a file picker; FileReader parses
  the JSON, POSTs, prepends the imported session to the list,
  selects and connects. Inline error below the button on bad JSON
  or server rejection.
- `api.importSession(payload)` TS helper.

## [0.1.34] - 2026-04-19

### Added

- `AuthGate.test.ts` — 5 cases: hidden when `auth.status == 'open'`;
  visible on `required`; shows "rejected" copy on `invalid`; saving a
  token flips status to `ok` + writes localStorage; empty-string
  submission is a no-op.

### Fixed

- `vitest.setup.ts` installs a Map-backed `localStorage` shim on
  both `globalThis` and `window`. Node 22+ ships a native
  `localStorage` global that is non-functional unless
  `--localstorage-file` is given a valid path, and that global
  shadows jsdom's Storage under vitest — `setItem` / `getItem` threw
  `TypeError`. The shim sidesteps the whole mess and clears between
  tests via `afterEach`.

## [0.1.33] - 2026-04-19

### Added

- `Settings.test.ts` — exercises the real `prefs` store: fields
  pre-fill on open, Save writes all three fields back to the store,
  Cancel leaves the store untouched. Proves the component-test
  scaffold can drive store-integrated components, not just static
  markup.

### Changed

- `vitest.config` resolves `$lib` to `src/lib` explicitly — needed
  because SvelteKit's build-time alias isn't available in the
  isolated vitest plugin chain. Added `@types/node` dev dep so the
  config's `path.resolve(__dirname, …)` typechecks.

## [0.1.32] - 2026-04-19

### Added

- Component tests under `@testing-library/svelte` + `jsdom`:
  vitest.config adds `environment: 'jsdom'`, `resolve.conditions: ['browser']`
  (so Svelte 5 picks the client entry, not index-server.js), and a
  setup file loading `@testing-library/jest-dom/vitest` matchers.
- First component test: `CheatSheet.test.ts` — renders nothing when
  closed, renders the shortcuts list when open, close button is
  clickable. Auto-cleanup via `afterEach(cleanup)`.
- `src/vitest-env.d.ts` pulls jest-dom matcher types into the
  svelte-check tsconfig.

## [0.1.31] - 2026-04-19

### Added

- `Session.message_count` — computed via subquery in `get_session`,
  `list_sessions`, `list_all_sessions`. SessionOut API response
  exposes it.
- Conversation header shows `· N msg` (pluralized) next to the cost
  segment when a session is selected. Useful now that pagination
  only loads 50 messages at a time — you can tell at a glance
  whether older ones are hidden.
- `sessions.bumpMessageCount(id, delta)` — conversation store calls
  it on user prompt (+1) and on MessageComplete (+1), so the header
  count ticks up live during streaming.

## [0.1.30] - 2026-04-19

### Added

- `GET /api/sessions/{id}/export` — single-session JSON dump
  containing `{session, messages, tool_calls}`. Scoped version of the
  v0.1.5 `/api/history/export` for archiving one conversation.
- ⇣ button in the Conversation header (next to ✎) downloads the
  session as `session-{id8}-{YYYYMMDD}.json` via a Blob + temporary
  anchor. Disabled while a download is in flight.

## [0.1.29] - 2026-04-19

### Added

- `GET /api/sessions/{id}/messages?before=<iso>&limit=<N>` — newest-
  first pagination cursor. `store.list_messages` grows an optional
  `before` + `limit`; without `limit` it keeps the original
  all-oldest-first behavior so existing callers are unaffected.
- Frontend `api.listMessagesPage(sid, {before?, limit?})` returns
  `{messages, hasMore}` with the page already reversed to
  oldest-first for rendering.
- `conversation.load()` now fetches 50 most-recent messages (+
  `hasMore`), not the whole history.
- `conversation.loadOlder()` + scroll-to-top handler in
  Conversation.svelte: scrolling within 40px of the top prepends the
  next page, preserving viewport (`scrollTop = newHeight -
  prevHeight`).
- "Scroll up to load older messages" / "Loading older…" hint at the
  top of the message list when `hasMore`.

## [0.1.28] - 2026-04-19

### Changed

- `store.list_sessions` orders by `updated_at DESC` instead of
  `created_at DESC`. `insert_message` now also bumps the owning
  session's `updated_at`, so a session that just streamed a turn
  rises above an idle newer session.
- Frontend `sessions.bumpCost` mirrors the same move-to-top: the row
  gets a fresh `updated_at` and is spliced to the head of the list,
  matching what the next `refresh()` would produce.

## [0.1.27] - 2026-04-19

### Added

- Cost badge on each sidebar session row (`$0.1234` in a mono font,
  hidden when total cost is zero). Uses the same amber/rose pressure
  coloring as the Conversation header when a `max_budget_usd` is set.
- `sessions.bumpCost(id, deltaUsd)` — called by the conversation
  store on every MessageComplete that carries a cost, so the sidebar
  badge updates live during streaming instead of waiting for a full
  refresh.
- Sidebar timestamp uses `updated_at` instead of `created_at` so a
  rename or a just-streamed turn shows a meaningful "last touched".

## [0.1.26] - 2026-04-19

### Added

- `?` key toggles a CheatSheet modal listing every keyboard /
  discoverability shortcut we've accumulated (⌘K, Esc, ⌘/Ctrl+Enter,
  double-click rename, ✎ / ⚙ / ✕ icons). Gated off when focus is in
  a textarea / input so typing a literal "?" in the prompt still
  works. Esc closes the modal.

## [0.1.25] - 2026-04-19

### Added

- Keyboard shortcut `⌘/Ctrl+K` focuses (and selects) the sidebar
  search input. Placeholder updated to advertise it.
- `Esc` inside the search input clears the query and blurs.

## [0.1.24] - 2026-04-19

### Added

- Match pill above the Conversation body when `highlightQuery` is
  set: `Matching «query» · Esc to clear`, with a ✕ button to clear.
- Document-level `Esc` keydown clears the highlight; ignored while
  the prompt textarea or any input has focus so it doesn't compete
  with normal text editing.

## [0.1.23] - 2026-04-19

### Added

- `AgentSession.interrupt()` — forwards to the active SDK client's
  `client.interrupt()`. Safe no-op when no stream is active. The WS
  handler now calls it on a `{"type":"stop"}` frame *before* breaking
  out of the stream loop, so tools running in the CLI subprocess get
  an actual cancel signal rather than just getting their output
  stream orphaned.
- `AgentSession._client` field tracks the live SDK client while a
  stream is in flight. Cleared in a `finally` under the `async with`
  so reference drops even if the generator is closed mid-iteration.

### Why

v0.1.18's stop already broke out of the server's stream loop and
persisted the partial turn. But a Bash tool running a 30s command
kept running in the CLI subprocess — the user's Stop clicks
stopped what they saw on screen without freeing the compute. Now
`agent.interrupt()` pokes the SDK, which tells the CLI to abort the
in-flight tool.

## [0.1.22] - 2026-04-19

### Added

- `$lib/actions/highlight.ts` — Svelte action that DOM-walks text
  nodes, wraps case-insensitive matches of `query` in
  `<mark class="search-mark">`, and scrolls the first match into view.
  Unwraps previous marks on `update` so repeated queries stay stable.
- `conversation.highlightQuery` — set when a sidebar search result is
  clicked; Conversation's per-message prose div applies the action to
  that query so matches jump out in the message body, not only the
  sidebar snippet.
- Scoped `mark.search-mark` styling matches the amber tint used in
  the sidebar (`yellow-500 @ 35%` background / `yellow-300` text).

### Changed

- `conversation.pushUserMessage` clears `highlightQuery` — sending a
  new prompt shouldn't leave a stale search highlight behind.

## [0.1.21] - 2026-04-19

### Added

- `$lib/utils/highlight.ts::highlightText(text, query)` — returns HTML
  with case-insensitive matches wrapped in `<mark>`. HTML-escapes the
  source first (so injected markup renders as text), treats regex
  metacharacters in the query as literals. 6 unit tests cover the
  escaping, no-match, multi-match, and meta-char cases.
- Sidebar search results render highlights via `{@html}` on the
  snippet, with a scoped `<style>` giving `<mark>` an amber tint that
  reads cleanly on the dark theme.

## [0.1.20] - 2026-04-19

### Added

- Vitest for the frontend — pure-logic tests run via `npm run test`.
  First coverage: `$lib/utils/budget.ts::parseBudget` (extracted from
  `SessionList.svelte` so it's testable).
- `vitest.config.ts` kept separate from `vite.config.ts` so
  svelte-check's type-checking of the Vite config stays clean.
- CI `frontend` job now runs `npm run test` between `npm run check`
  and `npm run build`.

### Changed

- `SessionList` imports `parseBudget` from `$lib/utils/budget` instead
  of defining it inline.

## [0.1.19] - 2026-04-19

### Added

- `GET /api/history/search?q=...&limit=N` — case-insensitive LIKE
  match across `messages.content` + `thinking`, joined with
  `sessions` for title + model. Returns `SearchHit[]` with a trimmed
  snippet window (±40/±120 chars around the first match).
- `store.search_messages(conn, query, limit)` + `SearchHit` Pydantic
  model.
- Frontend `api.searchHistory(q, limit)` helper.
- Sidebar search input above the sessions list. Typing (debounced
  200ms) swaps the list for match previews — session title, role
  badge, snippet with ellipses. Clicking a hit selects the session
  and connects.

## [0.1.18] - 2026-04-19

### Added

- `{"type":"stop"}` frame on the agent WebSocket interrupts an
  in-flight stream. The server breaks out of `agent.stream`,
  synthesises a `MessageComplete`, and persists whatever text/tool
  calls streamed so far — the partial assistant message is not lost.
- Frontend `agent.stop()` sends the stop frame; Conversation header
  shows a red **Stop** button next to the connection badge while
  `conversation.streamingActive` is true.

### Changed

- WS handler refactor: a dedicated reader task drains inbound frames
  into an `asyncio.Queue`; the outer prompt loop pulls from it, and
  the streaming loop peeks non-blockingly between events. Keeps a
  single WS reader (no racing `receive_json` calls), lets any future
  mid-stream control frame follow the same pattern.
- Assistant-turn persistence extracted into a `_persist_assistant_turn`
  helper so natural-end and stop paths both write through the same
  code.

## [0.1.17] - 2026-04-19

### Added

- `SessionEdit.svelte` modal wired behind a ✎ button in the Conversation
  header. Edits `title` + `max_budget_usd` on an existing session via
  the v0.1.16 PATCH route. Cap is no longer create-time-only.
- `bearings send --format=pretty` — human-readable output:
  - tokens stream inline with a flush,
  - `thinking` / `message_start` frames suppressed,
  - tool calls render as `↳ tool Name (input)` / `← ok: output` or
    `← error: message`,
  - each turn ends with a separator line + cost badge.
  Default `--format=json` stays one-event-per-line for scripting.

## [0.1.16] - 2026-04-19

### Added

- `PATCH /api/sessions/{id}` with `SessionUpdate` body — partial
  updates for `title` and `max_budget_usd`; unset fields leave the
  column untouched, explicit null clears. `updated_at` bumps on any
  real change. Returns 404 if the session is gone.
- `store.update_session(conn, session_id, fields)` — whitelists
  `title` / `max_budget_usd`, builds the SET clause dynamically.
- Frontend `api.updateSession(id, patch)` + `sessions.update(id, patch)`
  store method.
- Inline rename in the sidebar: double-click a session title →
  input; Enter / blur saves via PATCH, Esc cancels. Conversation
  header reflects the new title through normal reactivity.

## [0.1.15] - 2026-04-19

### Added

- `stores/prefs.svelte.ts` — reactive preferences persisted in
  `localStorage` (`defaultModel`, `defaultWorkingDir`, `authToken`).
- `components/Settings.svelte` — modal accessed via a ⚙ button in the
  Sessions panel header. Edits all three prefs + also lifts the auth
  gate when a token is entered here while the gate is up.
- SessionList new-session form pre-fills `working_dir` and `model`
  from saved prefs each time it opens; user edits within the open
  form still override. Create also falls back to the pref default if
  the user clears the field.

## [0.1.14] - 2026-04-19

### Added

- `messages.thinking` column (migration 0004). WS handler accumulates
  a `thinking_buf` alongside `buf` during the turn and passes the
  joined string (or `None` if empty) to `insert_message` at
  `MessageComplete`. Persisted thinking survives page reloads.
- `MessageOut.thinking` + frontend `Message.thinking` types.
- Conversation pane renders a `<details>` "thinking" block (closed by
  default) on any persisted message that has stored reasoning.

### Fixed

- `test_metrics.py::test_ws_counters_update` flake: the
  `messages_persisted` assistant counter is incremented in the
  MessageComplete branch after the last send, which can be truncated
  by TestClient context exit. Now polls the counter inside the WS
  context before asserting, matching the pattern used elsewhere.

## [0.1.13] - 2026-04-19

### Added

- `Thinking(type="thinking", session_id, text)` event. `AgentSession`
  now translates `ThinkingBlock.thinking` (emitted by the SDK when
  extended thinking is on) into a `Thinking` frame instead of silently
  dropping it.
- Frontend `AgentEvent` union picks up `ThinkingEvent`; conversation
  store accumulates `streamingThinking` alongside `streamingText`.
- Streaming pane shows a `thinking` `<details>` block (open by default)
  above the token output when the agent is reasoning aloud.

## [0.1.12] - 2026-04-19

### Added

- `AuthGate.svelte` modal. When `/api/health` reports
  `auth: "required"` and no token is stored (or the stored token is
  rejected on any API 401 / WS 4401), the modal blocks the UI with a
  password-masked input. Save → token persists in
  `localStorage["bearings:token"]` → boot proceeds.
- `stores/auth.svelte.ts` tracks `status`
  (`checking`/`open`/`ok`/`required`/`invalid`/`error`). `api.ts`
  exports `onAuthFailure(cb)` so the store flips itself to `invalid`
  on 401 without a circular import. `agent.svelte.ts` flips the same
  way on WS close 4401 and aborts reconnect (no infinite loop).
- Boot flow moved from `SessionList.onMount` to `+page.svelte`: auth
  check first, then `sessions.refresh` + auto-connect only after the
  gate clears.
- Budget pressure coloring in the Conversation header: amber at ≥80%
  of `max_budget_usd`, rose at ≥100%. Sessions with no cap render
  unchanged.

### Fixed

- `SessionList` budget parsing now handles `<input type="number">`
  binding variants (number / empty string / null) instead of assuming
  a string; previously the new-session form submitted
  `max_budget_usd: null` when the field had a value.

## [0.1.11] - 2026-04-19

### Added

- Opt-in bearer-token auth. Set `auth.enabled = true` +
  `auth.token = "..."` in `config.toml`:
  - `/api/sessions*` and `/api/history*` require
    `Authorization: Bearer <token>` (new `api/auth.py` dependency).
  - `/ws/sessions/{id}` requires `?token=<token>` (browsers can't set
    WS headers); closes with app code `4401 Unauthorized` on mismatch.
  - `/api/health` and `/metrics` stay open so monitoring can probe
    without creds.
  - Enabling auth with an empty token fails the first request with
    500 — fail closed rather than silently ship with no protection.
- `GET /api/health` now returns `{auth: "required"|"disabled", version}`
  so clients can tell whether they need to supply a token.
- `bearings send --token <t>` flag; CLI also auto-pulls from
  `cfg.auth.token` when `auth.enabled`.
- Frontend `api.ts` reads `localStorage["bearings:token"]` and injects
  `Authorization: Bearer` on fetches + `?token=...` on the WS URL. UI
  to enter the token lands in a later slice; for now set it via devtools
  (`localStorage.setItem('bearings:token', '...')`).

## [0.1.10] - 2026-04-19

### Added

- `MessageComplete.cost_usd` — SDK-reported turn cost
  (`ResultMessage.total_cost_usd`) surfaced on the wire. `AgentSession`
  captures it before the `break` on ResultMessage.
- `sessions.total_cost_usd` column (migration 0003, `REAL NOT NULL
  DEFAULT 0`). `store.add_session_cost` accumulates it per turn; WS
  handler calls it on MessageComplete when cost is non-null.
- `SessionOut.total_cost_usd` on the API.
- Frontend `Session.total_cost_usd` + `MessageCompleteEvent.cost_usd`.
- Conversation store tracks `totalCost`: seeded from the DB row on load,
  incremented locally per MessageComplete. Conversation header shows
  `spent $Y.YYYY` and, when a cap is set, `/ $X.XX`.

## [0.1.9] - 2026-04-19

### Added

- Graceful WebSocket shutdown: FastAPI lifespan tracks active agent
  sockets in `app.state.active_ws`; on shutdown, each is closed with
  code `1001 Going Away` before the DB connection is torn down.
  Clients see a clean disconnect (and hit the v0.1.4 reconnect path)
  instead of `ConnectionReset` on `systemctl restart`.
- Conversation header shows `budget $X.XX` next to model + working_dir
  when the session has a `max_budget_usd` cap set; otherwise omitted.

## [0.1.8] - 2026-04-19

### Added

- `sessions.max_budget_usd` column (migration 0002) — optional per-session
  cap in USD. `POST /api/sessions` accepts it via body; `AgentSession`
  passes it to `ClaudeAgentOptions.max_budget_usd` when non-null. Stops a
  runaway agent loop from burning unbounded tokens.
- Frontend: "Budget USD (optional)" field in the new-session form,
  persisted end-to-end. `Session` / `SessionCreate` TS types pick up the
  field.
- `/api/history/export?from=YYYY-MM-DD&to=YYYY-MM-DD` — either/both
  bounds supported; bad dates return 400. Store `list_all_*` helpers
  swap the old single `date_prefix` arg for `date_from` + `date_to`;
  `/history/daily/{date}` now passes the same date to both bounds.

## [0.1.7] - 2026-04-19

### Added

- New `MessageStart(session_id, message_id)` event emitted by
  `AgentSession.stream` as the first frame of each turn. The same
  `message_id` is reused for the turn's `MessageComplete`, giving the
  wire protocol a stable id for the assistant message before its
  content is known.
- `store.attach_tool_calls_to_message(message_id, tool_call_ids)` —
  backfills `tool_calls.message_id` after the assistant message row
  exists. The WS handler collects tool-call ids emitted during the
  turn and calls this helper at `MessageComplete`.
- `insert_message` accepts an optional `id` so the WS handler can
  persist the assistant row with the `MessageStart.message_id` — the
  same id the client already received over the wire.
- Frontend `AgentEvent` union gains `MessageStartEvent`; conversation
  store handles it as a no-op (rendering continues to hinge on
  `MessageComplete`).

### Why

Tool-call rows were landing with `message_id = NULL`. Attempting to
insert the link at `ToolCallStart` time tripped the FK (no message
row yet). The `MessageStart` → collect → backfill flow keeps the FK
enforced while still linking tool calls back to their assistant turn.

## [0.1.6] - 2026-04-18

### Added

- `GET /api/sessions/{session_id}/tool_calls` — list persisted tool-call
  rows, oldest-first. 404 on unknown session.
- `ToolCallOut` Pydantic model (matches DB columns 1:1, `input` stays as
  the stored JSON string).
- Frontend `api.ts` gains `ToolCall` type + `listToolCalls()` helper.
- `conversation.svelte.ts` now hydrates the `toolCalls` array from
  `/api/sessions/{id}/tool_calls` on session load (parallel with
  `listMessages`), converting ISO timestamps → ms and the stored JSON
  input string → `Record<string, unknown>`. Reloading a session now
  shows its tool-call history in the Inspector instead of an empty
  panel; live WS events continue to append/update on top.

## [0.1.5] - 2026-04-18

### Added

- Prometheus collectors in a dedicated `bearings/metrics.py` using a
  private `CollectorRegistry`. Metrics exposed on `/metrics`:
  - `bearings_sessions_created_total`
  - `bearings_messages_persisted_total{role}`
  - `bearings_tool_calls_started_total`
  - `bearings_tool_calls_finished_total{ok}`
  - `bearings_ws_active_connections` (gauge)
  - `bearings_ws_events_sent_total{type}`
  Instrumentation lives at the route / WS-handler boundary; store.py
  stays side-effect-free.
- `GET /api/history/export` — full `{sessions, messages, tool_calls}`
  dump.
- `GET /api/history/daily/{YYYY-MM-DD}` — same shape filtered to one
  calendar day; 400 on bad date.
- `store.list_all_sessions`, `list_all_messages`, `list_all_tool_calls`
  with optional `date_prefix` filter.
- CI job verifies `src/bearings/web/dist/index.html` + `_app/` exist
  after `npm run build` so a broken sync-dist step fails the build.
- CI frontend job now also runs `npm run check` (svelte-check) gating
  type errors in components.

## [0.1.4] - 2026-04-18

### Added

- Shiki syntax highlighting in conversation markdown code blocks
  (python, typescript, bash, json, yaml, rust, go, and more); wired via a
  custom marked renderer. Pre-initialized at module load via top-level
  await so `renderMarkdown` stays synchronous.
- Tool-call finish time: `LiveToolCall.finishedAt` set on
  `tool_call_end`; Inspector now shows final duration ("123ms" / "2.4s")
  after completion instead of ticking "running".
- Session selection persists in `localStorage`
  (`bearings:selectedSessionId`); auto-connects on boot if the stored id
  still exists in the session list.
- WebSocket auto-reconnect with exponential backoff (1s/2s/4s/8s/…,
  capped at 30s); Conversation header shows `retrying in Ns`. Triggers
  on abnormal closes, skipped for `4404 session not found` and normal
  `1000` close. Resets on successful open; cancelled on explicit
  `agent.close()`.
- Inline two-click delete confirmation: first click on ✕ swaps to
  "Confirm?" for 3 seconds; second click deletes. No more `window.confirm`
  dialog — UI is fully scriptable.

### Changed

- `vite.config.ts` build target bumped to `es2022` so top-level await in
  `render.ts` (shiki WASM init) compiles cleanly.
- `SessionList` confirm state switched to `$state` object property
  (`confirm.id`) rather than a bare `$state` variable; event-handler
  closures see fresh values reliably.

## [0.1.3] - 2026-04-18

### Added

- Frontend three-panel shell: `SessionList`, `Conversation`, `Inspector`
  Svelte components wired through `+page.svelte`.
- `frontend/src/lib/api.ts` — typed `AgentEvent` discriminated union, session
  CRUD helpers (`listSessions`, `createSession`, `deleteSession`,
  `getSession`, `listMessages`).
- Svelte 5 runes-based stores: `sessions.svelte.ts` (list, selected id,
  CRUD) and `conversation.svelte.ts` (historical messages, in-flight
  streaming buffer, live tool calls).
- `agent.svelte.ts` — WebSocket connection manager dispatching events
  into the conversation store, with typed `ConnectionState`.
- `render.ts` — `marked`-backed Markdown → HTML with GFM + line breaks.
- `@tailwindcss/typography` plugin for markdown styling (`prose
  prose-invert`).

### Changed

- `frontend/package.json` version bumped to `0.1.3` (tracks Python pkg).

## [0.1.2] - 2026-04-18

### Added

- `GET /api/sessions/{session_id}/messages` — history playback endpoint
  returning `MessageOut[]`.
- `bearings send --session <id> <prompt>` — CLI subcommand opens a WebSocket
  to a running server, streams events to stdout as JSON lines, exits 0 on
  `message_complete`, 1 on `error`.
- `ToolCallEnd` event: `AgentSession.stream` now translates
  `ToolResultBlock` (carried on `UserMessage.content`) into a `ToolCallEnd`
  event with `ok`/`output`/`error` derived from `is_error` + `content`.
- Tool-call persistence: `store.insert_tool_call_start`, `finish_tool_call`,
  `list_tool_calls`. WS handler writes rows as events stream.

## [0.1.1] - 2026-04-18

### Added

- DB CRUD in `db/store.py`: `create_session`, `list_sessions`, `get_session`,
  `delete_session`, `insert_message`, `list_messages`.
- `api/models.py` with `SessionCreate`, `SessionOut`, `MessageOut` DTOs.
- Real session CRUD routes at `/api/sessions` (`GET`, `POST`, `GET/{id}`,
  `DELETE/{id}`), replacing the 501 stubs.
- `AgentSession.stream()` wired to `claude-agent-sdk`'s `ClaudeSDKClient`;
  translates `AssistantMessage` text/tool-use blocks into `Token` /
  `ToolCallStart` / `MessageComplete` / `ErrorEvent`.
- `/ws/sessions/{id}` WebSocket bridge: accepts a `{"type":"prompt","content":"..."}`
  frame, streams events back, and persists user + assistant messages.
- FastAPI `lifespan` wiring `init_db()` at startup → `app.state.db`.

### Changed

- `init_db()` now sets `conn.row_factory = aiosqlite.Row` so CRUD can return
  column-keyed dicts.

## [0.1.0] - 2026-04-18

### Added

- Initial scaffold: FastAPI backend, SvelteKit frontend shell, SQLite/aiosqlite
  persistence layer, CLI entry point, systemd user unit, CI workflow.
- Health endpoint and placeholder REST/WebSocket routes (bodies return 501 until
  backing logic lands).
