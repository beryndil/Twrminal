# Bearings — Open Tasks

**Live document.** Only deferred, blocked, and carried-over work
belongs here. Shipped work lives in `CHANGELOG.md` (and in
`git log --oneline --all` / `git tag`). The pre-2026-04-22 version of
this file — which contained per-version shipped ledgers — is preserved
verbatim at `TODO-archive-2026-04-22.md` next to this file.

Known gap: 15 shipped versions (v0.3.0–5, v0.3.8–12, v0.4.0–1,
v0.5.0–1) exist in the archive's "## vX.Y.Z — shipped" sections but
are missing from `CHANGELOG.md`. Backfill is logged at
`~/.claude/TODO.md` § "CHANGELOG.md gap in Bearings".

Scaffold reference (still useful for plans):
`~/.claude/plans/here-are-the-architectural-ticklish-puppy.md` and
`~/.claude/plans/hazy-hatching-honey.md` (v0.1.1 slice plan).

---

## Autonomous checklist execution — 2026-04-24

**Goal.** Point Claude at a `kind='checklist'` session and have him work
through unchecked items sequentially — one fresh paired chat session per
item — with zero human input between items. Context protection, followup
nesting, and handoff legs are first-class primitives, not afterthoughts.

**Why this is tractable.** The primitives already exist:
- Per-item paired chat sessions (`routes_checklists.py`, spawn endpoint)
  already provide across-item context isolation.
- `checklist_items.parent_item_id` (schema.sql:187) already supports
  nested followups.
- `sessions.checklist_item_id` (schema.sql:38) already lets us find every
  session spawned for an item.
- The agent runner's worker queue (`runner.py`) doesn't care whether
  prompts come from WS or server-side code — enqueuing programmatically
  is trivial.
- `ContextUsage` events (`session.py:258-266`) already expose `percentage`
  of context window consumed — watchdog input is free.

**Three axes of context protection.**

| Axis | Mechanism |
|------|-----------|
| Across items | Fresh paired chat session per item (exists) |
| Nesting (followups) | `parent_item_id` tree + depth cap (schema exists) |
| Within an item | **Handoff-to-successor leg when window fills** ← new |

**Design.**

1. **Autonomous driver.** Long-lived async task per checklist session.
   Pseudocode:

   ```
   async def drive(checklist_session_id):
       while item := next_unchecked(checklist_session_id):
           if has_incomplete_children(item):
               await drive_children_first(item)
           leg = 1
           while not item.checked:
               session = spawn_paired_chat(item, leg=leg,
                                          plug=previous_plug or None)
               await run_with_watchdog(session)  # may emit handoff
               if session.emitted_handoff:
                   previous_plug = session.handoff_plug
                   leg += 1
                   continue
               if session.spawned_children:
                   await drive_children_first(item)
                   # re-enter loop; parent re-executes with children done
                   continue
               if session.failed:
                   record_failure(item); break
           # item checked; advance
   ```

2. **Completion signal.** New MCP tool exposed to the agent:
   `mark_checklist_item_done(item_id, notes?)`. Agent self-marks when
   truly done. Driver polls `checked_at` to advance. (Alternatives —
   end-of-turn heuristic, `<DONE/>` token — are fragile; self-mark is
   the only one where the agent owns the completion decision.)

3. **Followup / nesting tool.** New MCP tool:
   `add_checklist_followup(parent_item_id, label, block_parent: bool)`.
   When `block_parent=True`, driver recurses into children before the
   parent can complete. Depth cap (initially 3) guards against runaway
   spawning — on violation, mark item failed with "nested too deep."

4. **Context watchdog & handoff.** Driver subscribes to `ContextUsage`
   events for the active session. At threshold (~60% of max_tokens —
   conservative, matches Dave's manual handoff discipline):
   - Driver injects prompt: "You're approaching context limit. Emit a
     handoff plug via the `handoff` tool describing state, work done,
     work remaining, files touched, red lines. Do not continue the
     task this turn."
   - New MCP tool: `handoff(plug_text)`. Persists plug on the item.
   - Driver kills current runner, spawns successor paired chat for the
     same item with `description = plug_text` and
     `session_instructions` containing the plug for per-turn
     persistence. Title suffix: "(leg N)".
   - Successor resumes the work with only the plug as context.

5. **Schema delta.** `checklist_items.chat_session_id` is currently a
   single FK (schema.sql:205). For legs, switch to the reverse pointer:
   query `SELECT * FROM sessions WHERE checklist_item_id = ? ORDER BY
   created_at` to get the leg chain. Drop `chat_session_id` column via
   numbered migration. Zero new tables. The UI shows each leg as an
   expandable row under the item.

6. **Safety rails.**
   - Per-item token/time budget (reuse `max_budget_usd` already plumbed
     in `session.py:276`).
   - Total checklist budget cap (config or per-run parameter).
   - Hard stop button: kills driver + active runner.
   - Failure policy: halt-on-first-fail (default) vs.
     mark-failed-continue (opt-in). Log failures to item notes.
   - Max legs per item cap (e.g. 5) — if item keeps demanding handoffs
     past this, something is wrong with how it's scoped.
   - Max items per run cap (e.g. 50) — cheap safeguard against a
     runaway checklist.

7. **UI surface.**
   - "Run autonomously" button on `kind='checklist'` sessions.
   - Status pill: "running item 3 of 7 — leg 2 — 45% context" or similar.
   - Stop button (already-existing session Stop, extended to tear down
     the driver).
   - Leg chain display per item (expandable).
   - Failure indicator per item with link to the failed leg's session.

**Build order.**

1. **Migration + schema change.** Drop `checklist_items.chat_session_id`,
   rely on reverse pointer. (Smallest, unblocks everything else.)
2. **MCP tools.** `mark_checklist_item_done`,
   `add_checklist_followup`, `handoff`. Wire into the agent runner's
   tool surface. These are independent of the driver and testable.
3. **Context watchdog.** Subscriber on `ContextUsage`, threshold check,
   handoff-prompt injection. Testable in isolation with a mock agent.
4. **Autonomous driver (flat case).** Just linear iteration, no nesting,
   no handoff — prove the spawn-run-advance loop works.
5. **Followup nesting.** Layer `parent_item_id` recursion + depth cap
   onto the driver.
6. **Handoff legs.** Layer watchdog + successor spawn onto the driver.
7. **UI.** "Run autonomously" button, status pill, legs expander, stop.
8. **Safety rails + config.** Budgets, caps, failure policy.

**Red lines.**
- Do not invent a within-session context-clearing mechanism. Legs-via-
  new-session is the handoff primitive; that's how Dave works manually
  and it's what the schema/session model already supports.
- Do not touch `agent/_interrupt_probe.py` or its call sites — those are
  scheduled for removal once the session-switch interrupt bug closes.
- Do not wedge the driver into the WS handler. It's a standalone async
  task owned by a new module (e.g. `src/bearings/agent/auto_driver.py`),
  registered alongside the runner but independent.
- No cross-session context leakage. Each leg and each item starts with
  ONLY the plug + checklist overview — no inheritance of prior SDK
  session ids.

**Files most likely to touch.**
- `src/bearings/db/schema.sql` + new migration
- `src/bearings/agent/auto_driver.py` (new)
- `src/bearings/agent/tools_checklist.py` (new — MCP tool handlers)
- `src/bearings/agent/runner.py` (hook for programmatic prompt enqueue,
  probably already supports it)
- `src/bearings/api/routes_checklists.py` (add "run autonomously"
  endpoint)
- `src/bearings/api/models/checklists.py` (add DTOs for legs + run
  status)
- `frontend/src/lib/components/...` (new UI button + status pill +
  legs expander — specific paths TBD during the UI slice)

**Verification.**
- Unit tests per MCP tool (mark, followup, handoff).
- Unit tests for the driver in isolation against a stub agent.
- Integration test: 3-item checklist, stub agent that marks each done
  immediately → driver advances cleanly, all three checked.
- Integration test: 1 item, stub agent emits handoff at 60% → driver
  spawns leg 2, which marks done → item checked, 2 sessions present.
- Integration test: 1 item, stub agent creates blocking child → driver
  recurses, child completes, parent re-executes and completes.
- Browser QC via Playwright: click "Run autonomously" on a real
  checklist, watch it complete end-to-end.

---

## AskUserQuestion tool_result arrives empty — 2026-04-24

**Symptom.** During plan mode, the AI calls the first-party
`AskUserQuestion` tool, the picker dialog renders, Dave selects an
answer. The tool result delivered back to the model is literally
`User has answered your questions: .` — trailing period, empty body.
Reproduced twice in one session for two independent picker
invocations. Not a one-off dismissal; Dave confirmed he was
interacting with the pickers.

**Investigation (done 2026-04-24).** Audited the full event path
through Bearings and confirmed it is a **pure relay** — zero mutation
of tool_result content anywhere in Bearings:

- `src/bearings/agent/session.py:349-352` — `ToolResultBlock` is
  forwarded to `_tool_call_end`, which calls `_stringify` (lines
  54-57). `_stringify` returns string content verbatim and JSON-dumps
  list content. No trimming, no summarization.
- `src/bearings/agent/runner.py:990-1009` — `_emit_event` pydantic-
  dumps the event and orjson-encodes it. Pure serialization.
- `src/bearings/api/ws_agent.py:171-205` — `_forward_events` sends
  pre-encoded wire frames verbatim via `websocket.send_text`. No
  inspection of payload.
- `src/bearings/db/_messages.py` — `finish_tool_call` and
  `append_tool_output` persist `output` untouched.
- Grep for `AskUserQuestion` / `ask_user_question` across the repo
  returns zero matches. No custom handling exists.

**Conclusion: bug is upstream** — either in `claude-agent-sdk`
(pinned at 0.1.63 per `uv.lock`) or in the bundled Claude CLI that
renders the picker UI.

**Likely fix.** The claude-agent-sdk 0.1.65 changelog entry for #836
fixes a message-parser bug where content blocks were *silently
dropped*, causing messages to arrive with empty content. Adjacent
enough to the symptom here to be worth trying. 0.1.66 also bumped
the bundled Claude CLI (where the picker UI lives) to 2.1.119.

**Next actions (in order):**
1. Bump `claude-agent-sdk` in `pyproject.toml` to `>=0.1.66,<0.2`
   (or pin `==0.1.66`), `uv lock --upgrade-package claude-agent-sdk`,
   retest AskUserQuestion in a Bearings plan-mode session.
2. If still broken after the bump: bare-shell repro — run plain
   `claude` outside Bearings, trigger plan mode, call
   AskUserQuestion, confirm the empty-answer bug reproduces
   upstream. If yes, file upstream against
   `anthropics/claude-agent-sdk-python` (or `claude-code` if the
   issue is in the CLI picker rather than the SDK parser) with the
   exact wire payload.
3. Do NOT patch around this in Bearings. Red line per the session
   brief: upstream bugs get filed upstream, not hacked around here.

**Files NOT to touch.** Nothing under `frontend/src/lib/components/`
(picker is harness-rendered, not Bearings-rendered). Nothing in
`frontend/src/lib/stores/sessions.svelte.ts` (lifecycle fix in
979c1ba is orthogonal).

**Not urgent.** Planning sessions are degraded but not broken —
Dave can re-type answers as plain text for now.

---

## Flaky test: `test_get_tool_calls_filters_by_message_ids` — 2026-04-24

Observed once in a full `uv run pytest -q` run:
`tests/test_routes_sessions.py::test_get_tool_calls_filters_by_message_ids`
fails with `assert parent_msg_id is not None` at line 372. Does not
reproduce in isolation (`pytest tests/test_routes_sessions.py::…`) and
does not reproduce on a second full-suite run. Smells like test
ordering — a prior test leaves WS-adjacent state (runner registry,
broker, or stub agent) in a shape where the parent message_id on the
WS-posted tool_call isn't backfilled. Not caused by anything in the
softRefresh / applyUpsert lifecycle-merge fix I landed today — that
change is frontend-only. Deferred: stabilize the test (likely by
adding a teardown or scoping a fixture) or mark it with
`pytest.mark.flaky` pending investigation.

---

## TEMP probe — session-switch interrupt diagnostic — 2026-04-23

**Active, remove after diagnosis.** Dave reported an intermittent bug:
switching sessions in the UI sometimes interrupts the running Claude
instance. Code audit shows no session-switch path that should call
`agent.interrupt()` — WS disconnect explicitly keeps the runner alive,
and the reaper won't touch a `running` runner. To pin down which of
the three real interrupt sites (`runner.shutdown` / `runner.request_stop`
/ `_execute_turn` stop-check) is actually firing, I added a dedicated
probe at:

- `src/bearings/agent/_interrupt_probe.py` — new module, writes to
  `~/.local/share/bearings/interrupt-probe.log`.
- `src/bearings/agent/session.py:AgentSession.interrupt` — catches
  every actual SDK interrupt with the full caller chain.
- `src/bearings/agent/runner.py:SessionRunner.shutdown` — logs who
  triggered the shutdown path.
- `src/bearings/agent/runner.py:SessionRunner.request_stop` — logs
  who triggered the user-stop path.
- `src/bearings/api/ws_agent.py` finally block — logs WS disconnect
  timing + runner state for correlation.

**Removal checklist when bug is pinned down:** delete
`_interrupt_probe.py`, remove the four call sites (each marked with
`# TEMP 2026-04-23`), and delete this TODO entry. Don't ship this to
a tagged release — the FileHandler is cheap but unconditional.

**Defensive layer added 2026-04-24 while root cause still open.**
`agent.stop()` no longer sends the WS frame synchronously — it queues
the frame behind a 3s countdown and surfaces an inline "Stopping Xs
· Undo" pill in place of the Stop button. Clicking the pill's Undo
button cancels the pending send. This serves two purposes:

1. Every Stop click is now **visible** — the pill appears whether
   Dave meant to click or not. Accidental stops become observable
   instead of mysterious.
2. Accidental stops are **recoverable** during the 3s window.

Shipped in two commits:
- `ba98d70` — first pass via the shared `undoStore` + bottom-right
  toast. Dave flagged the position as wrong ("it should popup by
  the stop button") because hunting for a bottom-right toast eats
  the 3-second window.
- `08ab470` — replaced the bottom-right toast with an inline pill
  that morphs the Stop button in place. New component
  `frontend/src/lib/components/StopUndoInline.svelte` reads the
  reactive `agent.stopPendingStartedAt` (`number | null`) and
  `stopPendingWindowMs` to render the countdown. `undoStore`
  import dropped from `agent.svelte.ts`; wiring is pure reactive
  state. `Conversation.svelte` + `ChecklistChat.svelte` both swap
  Stop→pill based on the flag.

Relevant code (current state):
- `frontend/src/lib/agent.svelte.ts` — `STOP_DELAY_MS` const,
  `stopPendingStartedAt` / `stopPendingWindowMs` `$state` fields,
  `pendingStopTimer` private timer, `cancelPendingStop()` (also
  called from `close()` so a session switch drops the queued
  frame).
- `frontend/src/lib/components/StopUndoInline.svelte` — the
  inline pill.
- `frontend/src/lib/agent.svelte.test.ts` — 4 tests cover
  deferral, undo-cancel, no-stack guard, and session-switch
  cancel. 608/608 frontend suite green.

Browser→server diagnostics (also TEMP 2026-04-24, remove with the
probe):
- `src/bearings/api/routes_diag.py:log_undo_diag` — `/api/diag/undo`
  endpoint that writes to the same `interrupt-probe.log`.
- Stop frame carries `_clickedAt`, `_undoPushed`, plus the earlier
  `_trace` / `_isTrusted` / `_eventType`. Server-side probe in
  `ws_agent.py` stop branch echoes `fe_clickToRecv_ms` so I can
  confirm the 3s defer actually runs in Dave's browser.
- Rule `~/.claude/rules/no-devtools-dave.md` — Dave doesn't open
  browser devtools; all diagnostics MUST come back via the server
  (probe log, Playwright, instrumented frames).

**Disposition when bug closes:** the inline pill is worth keeping
as a feature — three-second undo on Stop is a generally nice
affordance. But re-evaluate the window length (3s was chosen for
diagnostic visibility; 1.5s might feel snappier once the bug is
gone) and strip the probe instrumentation from the frame (`_trace`
/ `_isTrusted` / `_eventType` / `_clickedAt` / `_undoPushed`
fields) + delete `/api/diag/undo` at the same time.

---

## `bearings window` default browser: Firefox — 2026-04-24

**Shipped.** `bearings window` now autodetects Firefox-family binaries
first and Chromium-family binaries second. Firefox launches with a
bearings-owned SSB profile (`--profile <dir> --new-window URL`);
Chromium keeps the legacy `--app=URL` SSB-style flag. Motivation is
the Chromium-on-Hyprland drop-dispatch bug logged below: the launcher
used to hand every new user a Chrome window where drag-and-drop
silently fails. Firefox has working DnD on the same compositor and
— with userChrome.css collapsing tabs/nav/bookmarks — looks like the
old Chrome `--app` SSB window.

Code changes (commit pending):
- `src/bearings/cli.py`: new `FIREFOX_BROWSERS` tuple, combined
  `SUPPORTED_BROWSERS = FIREFOX_BROWSERS + CHROMIUM_FLAVORED_BROWSERS`,
  `find_chromium_browser` renamed to `find_browser`, new
  `_is_firefox_like` helper. `FIREFOX_SSB_PROFILE_DIR` = `$XDG_DATA_HOME/
  bearings/firefox-ssb`, bootstrapped by `_ensure_firefox_ssb_profile`
  on first launch (writes `user.js` with
  `toolkit.legacyUserProfileCustomizations.stylesheets = true` + a few
  onboarding-noise prefs, plus `chrome/userChrome.css` collapsing
  `#TabsToolbar`, `#nav-bar`, `#PersonalToolbar`). Idempotent — user
  edits to either file survive subsequent launches because bootstrap
  only writes when the file is absent.
- `tests/test_cli_window.py`: prefer-Firefox + fallback-to-Chromium +
  Firefox-wrapper + both-flag-paths coverage, plus profile-bootstrap
  create-files and preserve-user-edits tests (12 tests, all green).

**Red lines still honored** — nothing was removed from the upload
pipeline: DnD receiver, `dropDiagnostic` amber banner, DND_PROBE
instrumentation, `Ctrl+V` paste handler, 📁 Browse button, and 📎
zenity attach-file fallback all remain. Every input path survives;
only the default launcher + its profile changed.

**Open follow-ups (not blocking):**

- [ ] Escape hatch flag for the SSB profile — `bearings window --plain`
  (or `--profile /custom/path`) if someone wants the normal Firefox
  window back without editing config. Not needed today; add if Dave
  hits a case where the SSB window is in the way.
- [ ] First-launch window sizing. Firefox remembers window geometry
  in the profile, but the very first SSB window opens at Firefox's
  default size — on a multi-monitor setup that can land awkwardly.
  Could set `toolkit.startup.max_resumed_crashes` + a default width/
  height via `browser.link.open_newwindow.override.external` or just
  let the user move it once and trust sessionStore.

---

## Drag-and-drop browser compatibility — 2026-04-23

**Findings after shipping the bytes-upload fallback (commits `fac7382`
→ filename-preservation follow-up):**

- **Firefox on Hyprland+Wayland: works.** Full path: file drop →
  DataTransfer.files readable → POST `/api/uploads` → server writes
  `<upload_dir>/<uuid>/<original-name.ext>` → absolute path injected
  at cursor. Confirmed by Dave with a real `.log` drop.
- **Chrome on Hyprland+Wayland: drop events never dispatch.**
  `dragenter`/`dragover`/`dragleave` all fire correctly (journal
  confirmed this before the probe was stripped), but Chrome never
  dispatches `drop` to ANY target — not the section, not the
  document-level swallow handler. Also verified under
  `--ozone-platform=x11` (XWayland): still silent, so it's not
  strictly a `wl_data_device` issue — Hyprland's XDND bridge and
  Chromium's Wayland path both fail to deliver. Not fixable
  client-side.
- **Chrome workaround shipped (commit `d7a0913`):** paste and a
  browser-native file picker as DnD-equivalent input paths, both
  feeding the existing `/api/uploads` pipeline.
  - `Ctrl+V` in the textarea picks up `ClipboardEvent.clipboardData.files`
    — clipboard is a different Wayland protocol than DnD and fires
    reliably. Dave confirmed this works end-to-end in his Chrome
    instance.
  - 📁 Browse button triggers a hidden `<input type="file" multiple>`;
    no compositor deps at all.
  - 📎 zenity Attach-file button still present — it's the only path
    that honors the session's `working_dir`.
- **Red-line fallback still honored**: if paste also fails on some
  future compositor, zenity is always there. No browser-sniffing.

**Open follow-ups (not blocking):**

- [ ] GC sweep of `~/.local/share/bearings/uploads/` — time-based
  (e.g. delete UUID subdirs > 30d old) or tied to session deletion.
  Deferred until disk-usage becomes a real concern.
- [ ] XHR progress events so the "Uploading N file(s)…" pill shows
  actual bytes/sec instead of just a spinner. Irrelevant for small
  text drops; matters once a user drops a multi-MB image or PDF.
- [ ] Batch-POST endpoint for multi-file drops — current code serial-
  awaits per file to keep injection order deterministic. A single
  multipart POST with ordered parts would cut localhost latency.
- [ ] Retest Chrome with `--enable-features=FileSystemAccessDragAndDrop`
  at some point — if/when Chromium fixes the Wayland drop dispatch,
  we'd prefer not to tell users they need Firefox.

**Do NOT remove:** the drop receiver, `parseUriList`, `extractPaths`,
or the `dropDiagnostic` amber banner. Those are the instrumentation
that'll surface future compositor/browser regressions — even after
the upload fallback works, we still need to see what breaks next.

---

## Terminal-style `[File N]` attachments — 2026-04-23

**Shipped.** Mirrors the Claude Code terminal UX Dave called out
("It displays to me as [File 1], [File 2] but you get the actual
address"): the composer inserts token literals at the cursor, the
real path + display metadata travel in a sidecar, and the agent SDK
receives the fully substituted prompt.

Pieces that landed:
- Migration `0027_message_attachments.sql` adds `messages.attachments
  TEXT` (JSON blob) — additive, nullable.
- `src/bearings/agent/_attachments.py` — regex `\[File (\d+)\]`,
  whitespace-aware path quoting, orphan-prune + JSON-serialize.
- Runner orphan-replay path re-parses the stored sidecar so a socket
  drop mid-turn still reaches the SDK with the substituted prompt.
- Frontend: `lib/attachments.ts` + `MessageAttachment` wired through
  `agent.send` → WS frame → optimistic user bubble.
- Composer chip strip above the Attach-file row — shows `[File N]`,
  filename, size; `×` removes both sidecar row AND text token.

**Follow-ups (not blocking):**
- [ ] Transcript chip rendering in `MessageTurn.svelte` — today the
  user bubble renders stored `[File N]` text literally. `parseMessageBody`
  from `lib/attachments.ts` is ready to walk the message; the user
  bubble renderer just needs to iterate segments and emit styled chip
  spans for `kind: 'token'`.
- [ ] Renumber-on-delete policy: intentionally skipped (matches
  terminal). Revisit only if Dave asks for it.

---

## Per-message glass refraction — 2026-04-23

**Deferred.** First pass of Midnight Glass applied
`backdrop-filter: blur(8px)` to `<article>` so message cards got the
same refractive glass as the sidebars. Chromium promotes each such
element to its own compositing layer; in a `flex-1 overflow-y-auto`
messages column with dozens of turns, that produced enough layers
that the composer form's position didn't settle synchronously, and
the textarea rendered partly below the viewport until `autosizeTextarea`
(Conversation.svelte) forced a reflow on first keystroke.

Fix shipped: dropped backdrop-filter from `article` entirely — cards
still read as discrete surfaces via inner highlight + violet hairline
+ drop shadow. Sidebars and inspector `<aside>`s keep the real glass.

**Reopening requires** either (a) restructuring the composer so its
position doesn't depend on flex-sibling height settling in one pass,
or (b) virtualizing the message list so only the currently-visible
articles are live compositing layers. See `midnight-glass.css` comment
at the `article` rule for the full diagnosis.

---

## Theme switcher UI — 2026-04-23

**Context:** Midnight Glass theme landed as the active default; the
pre-Midnight-Glass palette is preserved under `[data-theme='default']`
in `frontend/src/lib/themes/tokens.css`. Switching is a one-attribute
flip on `<html>` (`data-theme`) — the Tailwind color scale resolves
through CSS variables, so no component rewrite is needed.

**Deferred:** Dave plans to build the selector UI later. Likely shape:
a Settings toggle (or header control) that writes the choice to
`localStorage` and updates `document.documentElement.dataset.theme`,
with a matching server-side preference so reload/other-tab stays in
sync. A no-flash path (inline script in `app.html` before paint that
reads storage and sets the attribute) is worth doing at the same
time — otherwise the first paint always shows the default.

**Files involved:**
- `frontend/src/lib/themes/tokens.css` — add new themes here
- `frontend/src/lib/themes/midnight-glass.css` — treatment layer;
  future themes get their own `<name>.css` with scoped selectors
- `frontend/src/app.html` — current hardcoded `data-theme="midnight-glass"`
- `frontend/src/app.css` — `@import`s both theme files today

---

## Drift detector lacks forward-only-revert tombstones — 2026-04-23

**Symptom:** `bearings.service` crashlooped with
`MigrationDriftError: schema_migrations has applied row
'0011_sdk_reported_cost.sql' but no such file`. Fixed in-place on Dave's
DB by stopping the unit, backing up to
`db.sqlite.bak-pre-0011-orphan-fix-20260423-175258`, and running
`DELETE FROM schema_migrations WHERE name='0011_sdk_reported_cost.sql'`.
Unit healthy at 17:53:06 CDT, `127.0.0.1:8787`.

**Root cause:** revert commit `7a957e3` (Apr 20, "undo 0.3.6 cost-inflation
fix — premise was wrong") deleted `src/bearings/db/migrations/0011_sdk_reported_cost.sql`
and declared "schema is forward-only" — but `_common.py:_apply_migrations`
(drift-detection pass added 2026-04-23, see comment at `_common.py:72`)
treats any applied row without a matching file as drift and refuses to
start. Anyone who ran v0.3.6 before the revert and then updated past the
drift-detector commit will hit this. Dead column `sdk_reported_cost_usd`
(NOT NULL DEFAULT 0) survives in `sessions` and is unreferenced in current
source — harmless but untidy.

**Fix options to consider:**
1. **Tombstone list** — add a module-level set of intentionally-retired
   migration names; drift detector skips those. Cheapest, leaves dead
   column in user DBs.
2. **Recovery migration** — ship `0026_retire_sdk_reported_cost.sql` that
   deletes the orphan row (and optionally drops the column). Fixes every
   affected user DB on next startup; follows the forward-only discipline.
3. **`--repair-drift` CLI flag** — one-shot op that deletes orphan rows
   with explicit user confirmation. Good escape hatch but doesn't
   auto-heal unattended installs.

Recommendation: option 2. Self-healing, no code complexity, keeps schema
history honest. Option 1 only if we expect more forward-only reverts.

---

## Session handoff — 2026-04-23 (context-full split)

Previous Claude session ran long (context-menu plan phases 7–13 +
post-ship packaging/hardening fixes, then diagnosed and fixed a live
right-click outage). Split here so the next session starts with fresh
context.

### Where we ended

- **v0.9.7 is the tip of main**, tagged and pushed. `bearings.service`
  was restarted at 13:31:23 CDT and now reports the real version —
  `/api/health` → `"version":"0.9.7"` (was lying as `0.6.0` for the
  whole v0.7.x–v0.9.6 line).
- **Right-click surface is live.** Context-menu plan phases 7 through
  13 shipped across v0.9.0–v0.9.5. Plan marks end-of-13 as
  "feature-complete per the shippable portion of the spec."
- **Packaging fixed (v0.9.6).** Wheel previously shipped with no
  frontend. `pyproject.toml` now has
  `[tool.hatch.build.targets.wheel.force-include]` pinning
  `src/bearings/web/dist/` into both wheel + sdist. Verified in a
  fresh venv.
- **Hardening landed (v0.9.7).** `menuConfig.hydrate` tolerates
  `undefined` / `null` / malformed `context_menus` payloads (runtime
  shape check, flags `.error = "stale backend"`, keeps registry
  serving built-in ordering). `src/bearings/__init__.py` now derives
  `__version__` from `importlib.metadata` so future bumps can't drift
  the reported version out of sync.

### Open tracks (pick one, or add your own)

1. **Context-menu plan deferred phases 14–16 (v0.10.x+).** All three
   have unresolved product questions the plan explicitly flagged
   (`docs/context-menu-plan.md` §8) — won't yield good code until the
   questions are answered by Dave:
   - Phase 14 Attachments — entirely unspecified (file types,
     storage model, whether they go into the model prompt, UX entry
     surfaces).
   - Phase 15 Retry tool call / regenerate — touches the
     `claude-agent-sdk` session-resume model (`sdk_session_id` holds
     hidden state); open question is whether retry forks the session
     or rewrites history in place.
   - Phase 16 Pending-ops panel — backend (`/api/pending`) already
     lives from Phase-A. Plan flags the anchor decision as unresolved:
     sidebar tab, Inspector tab, or floating card. Cheapest of the
     three once anchor is picked.

2. **Public-distribution / v1.0.0 readiness.** Prior session pivoted
   here briefly under the "make the best decisions for public
   distribution" prompt, then Dave course-corrected back to right-
   click. The pivot identified several blockers that are still open:
   - README Status/Features are 7 minor versions stale (still claims
     "Alpha — 0.2.x development", zero mention of the context-menu
     surface, palette, checkpoints, multi-select, etc.). First thing
     a public user reads.
   - No threat-model section in README (auth off by default +
     localhost binding is fine as the default, but it should be named
     explicitly so users who reverse-proxy don't get owned).
   - Never run `uv publish` / `twine upload dist/*`. Nothing is on
     PyPI yet — the wheel is *correct* now, but no one can
     `pip install bearings` from the public index.
   - Never tagged v1.0.0. Doing so promises a stable API surface.

3. **Pre-existing sluggishness audit.** Dave ran an audit on
   2026-04-23 that landed uncommitted edits in `TODO.md` — they are
   currently held in `git stash` (kept out of this handoff commit so
   the two tracks don't mix). Run `git stash list` to see them and
   `git stash pop` to restore. Headline finding:
   `frontend/src/lib/stores/conversation/reducer.ts` lines 229/256/
   276 allocate a fresh `toolCalls` array per streaming delta
   (`state.toolCalls = state.toolCalls.map(...)` /
   `[...state.toolCalls, newOne]`), despite the file's "mutate in
   place" header. This is the upstream cause of the 1:1 `buildTurns`
   rebuilds — **prerequisite for any re-derivation refactor to
   actually pay off**. Svelte 5 `$state` proxies propagate in-place
   mutation; fix is to mutate `tc.output` directly and
   `state.toolCalls.push()` for start.

### Operational notes for the next session

- **Don't trust `__version__` from a running service as the "what
  code is actually loaded" signal** — Python caches imports per
  process. Check `systemctl --user show bearings -p
  ActiveEnterTimestamp,MainPID` and compare to the latest commit
  time on main. If ActiveEnter predates the commit you care about,
  the process is stale and needs `systemctl --user restart bearings`
  to pick up new code.
- **The running `bearings.service` hosts the Claude session that
  operates on this repo.** Restarting it terminates the current
  Claude session. Ask Dave before restarting, or do it at a handoff
  boundary like this one.
- **The stashed TODO.md changes are Dave's audit work, not prior-
  session work.** Do not commit without checking with Dave.

---

## File-size audit (CLAUDE.md: max 400 lines)

Several files were split during v0.2/v0.3 work — see the archive's
`## Open follow-ups` § "File-size audit" for the full record.

**Closed 2026-04-23**: `src/bearings/api/models.py` (762 lines) split
into `src/bearings/api/models/` package across 14 domain submodules
(sessions, messages, tools, search, tags, prompts, fs, commands,
reorg, checklists, checkpoints, templates, vault, paired). All
submodules ≤171 lines. Public surface preserved via re-export shim
in `models/__init__.py`; no call-site changes. ruff + mypy strict +
761 pytests green.

Two violations remain:

- [ ] `src/bearings/agent/runner.py` — **510 lines** (was 1104, now
  27% over cap; 54% reduction this round, 2026-04-25). Round 1
  landed: `runner_types.py` (wire types + constants),
  `persist.py` (`persist_assistant_turn`),
  `progress_ticker.py` (`ProgressTickerManager`),
  `turn_executor.py` (worker loop + `execute_turn`, 434 lines),
  `event_fanout.py` (`emit_event` / `emit_ephemeral`). All 1063
  pytests + ruff + mypy strict green. Backwards-compat re-exports
  for `_Envelope`, `_Replay`, `_Submit`, `_Shutdown`, `RING_MAX`,
  `SUBSCRIBER_QUEUE_MAX`, `TOOL_PROGRESS_INTERVAL_S`,
  `_persist_assistant_turn` so `ws_agent` and existing tests keep
  importing from `bearings.agent.runner`.
  - Round 2 (deferred): runner.py at 510 is mostly extensive
    inline comments on `__init__` (bypass-permissions hang context,
    ApprovalBroker mode_getter rationale, sessions broker None
    handling). turn_executor.py at 434 is the per-event dispatch
    cascade in `execute_turn`. Both are over cap but further
    extraction starts to fragment cohesive behavior — the right
    next move if the cap is enforced is to (a) split per-event
    arms of `execute_turn` into `_on_tool_call_start` /
    `_on_tool_call_end` / `_on_message_complete` etc. helpers,
    (b) trim some `__init__` comments to module-level docs.
    Skipped in round 1 to keep diff small + tests green.

- [ ] `frontend/src/lib/components/Conversation.svelte` — **1,631
  lines** (4× cap). Highest-risk of the three: Svelte script +
  markup + style are interdependent, and CLAUDE.md requires browser
  verification for UI changes. Natural extraction candidates from
  the script block:
  - Reorg picker state + handlers (lines ~222–640: `openMoveFor` /
    `openSplitFor` / `onBulkMove` / `onBulkSplit` / `openMerge` /
    `closePicker` / `pickerTitle` / `pickerConfirmLabel` plus the
    `PickerOp` type) → `ReorgPicker.svelte` subcomponent + a
    `reorg-picker.ts` state helper.
  - Drag/drop cluster (lines ~958–1152: `hasFiles` / `parseUriList`
    / `onDragEnter` / `onDragOver` / `onDragLeave` / `extractPaths`
    / `onDrop` / swallow-handler setup) → `composer-dragdrop.ts`
    utility module.
  - Bulk-mode controls (lines ~193–220: `toggleBulkMode` /
    `onBulkToggleSelect`) → either a thin `BulkModeBar.svelte` or
    inline props on an existing subcomponent.
  - Textarea autosize + send + keydown (lines ~841–911) — small
    enough to stay, but watch it doesn't push a post-extraction
    Conversation.svelte back over cap.
  - After each extraction: `npm run check` (svelte-check) + run
    `uv run bearings serve` and exercise:
    conversation scroll, send, keyboard shortcut, reorg (move /
    split / merge with undo), bulk mode select + apply, drag-drop
    file upload, drag-drop text URI.

## Browser verification — deferred to pre-1.0.0

Consolidated pre-1.0.0 regression pass lives in `TESTING_NOTES.md`
§"Pre-1.0.0 browser regression pass — TODO". The old per-slice
v0.2.13 / v0.3.1 / v0.3.3 checklists are stale (app has moved on) —
rewrite the list against the 1.0.0-candidate UI at the time and run
it then. Do not exercise the historical checklists as-is.

## Open feature work

- [ ] **Context menu system — v0.9.0-alpha → v0.9.3 (2026-04-22).**
  Registry-driven right-click / long-press menus across 17 target types.
  Canonical plan: `docs/context-menu-plan.md`. Baseline v0.8.0. Plan
  makes five governing decisions:
  (1) "Change model for continuation" mutates session in place, does
  not fork.
  (2) `session.archive` action ID aliases to existing close route —
  no new archived state, no migration for archived_at.
  (3) Unbuilt actions use hybrid signalling: 501-route actions fire a
  stub toast on click; actions whose DB primitive does not exist yet
  (checkpoint / template / attachment) render disabled with "Coming
  in vX.Y.Z" tooltip.
  (4) Ctrl+Shift+P command palette ships in Phase 4 alongside first
  real menus, not in polish phase 12.
  (5) Shift-right-click = advanced mode (spec wins);
  Ctrl+Shift+right-click = native-Chrome-menu passthrough.
  Six open questions remain (see §8 of the plan): Chrome
  `always-show-context-menu` flag behavior, touch long-press
  precedence on links-in-code-blocks, pending-ops panel home,
  regenerate-from-message SDK-resume interaction, slash-command
  shortcut collision precedence, TOML hot-reload. None block Phase 1.
  Migrations reserved: 0022 session.pinned, 0023 message flags, 0024
  checkpoints, 0025 session_templates. `Conversation.svelte` (1424
  lines) is directive-only in this work — no new handler bodies may
  land there.
  - **Plan doc:** `docs/context-menu-plan.md`
  - **Phase 1 entry criterion:** decisions 1-5 reviewed and accepted
    (or amended) by Dave.
  - **Phase-gated decisions still needed:** see plan §8 items
    2 (before Phase 11), 3 (before Phase 16), 4 (before Phase 15),
    5 (before Phase 10). Items 1 and 6 are document-only / deferred.

- [x] **Silence gap during long Task sub-agent runs (2026-04-21, diagnosed 2026-04-23, P0–P3 shipped 2026-04-23).**
  Dave reported the UI sat silent for far too long between his "are you
  hung up?" prompt and the plan-agent response during the token-cost
  mitigation planning session (transcript
  `~/.claude/projects/-home-beryndil-Projects-Bearings/f57209ca-38b8-41b8-a6e7-cf1439c0b50d.jsonl`).

  **Timeline reconstructed from the transcript** (session `f57209ca`):
  T+0 (17:29:07Z) user prompt → T+12.8s `thinking` block → T+14.8s
  `text` block → T+31.8s `tool_use` name=`Agent` sub-agent kickoff
  (`toolu_01Bjpv…`) → **82s of dead silence, zero SDK entries** →
  T+113.5s `tool_result` lands and the outer turn resumes. No
  `isSidechain` entries anywhere in the file. The SDK surfaced nothing
  from the sub-agent until the tool_result returned.

  **Diagnosis:** mostly (a) compounded by (c). Bearings *does* forward
  the outer-turn `Agent` tool_use block the moment it arrives —
  `src/bearings/agent/session.py:336-340` (ToolUseBlock → ToolCallStart)
  and `src/bearings/agent/runner.py:557-566` (`_emit_event` before the
  coalescer). What's missing:
  - No keepalive in `src/bearings/api/ws_agent.py` — `_forward_events`
    is a bare `await queue.get()` loop. When the runner's `async for`
    parks waiting on the SDK, the socket goes idle.
  - No elapsed / pulse affordance in
    `frontend/src/lib/components/MessageTurn.svelte` on a running tool
    call. The `runningCount` badge exists at line 56 but carries no
    liveness signal — no timer, no subtitle, no pulse. User reads the
    static tile as a dead spinner.

  **Fix plan (priority order, all four mind the 4e5d532 `buildTurns`
  split — nudges must land on the `LiveToolCall` `$state` proxy, not a
  sibling field, to avoid breaking WeakMap caching):**
  - P0 ✅ shipped 8a5a9d4 — pulse + elapsed seconds + sub-agent subtitle
    on running `LiveToolCall`s in `MessageTurn.svelte`. Open-by-default
    `<details>` while any call runs.
    - ⚠️ **Partially reverted 2026-04-24 (94bc22b).** The open-by-default
      piece produced visible expand/collapse churn on every tool call
      (block flashed open when the first tool ran, slammed shut when the
      last finished). `open={runningCount > 0}` removed — `<details>`
      state is now purely user-controlled. To keep liveness visible when
      the user leaves the block collapsed during a long sub-agent wait,
      the sub-agent description is mirrored into the summary row
      (`data-testid="tool-work-subagent-subtitle"`) next to the pulsing
      running-count badge. Pulse, elapsed-seconds, and in-pre subtitle
      from the original P0 ship remain intact; only the auto-open
      behavior was rolled back.
  - P1 ✅ shipped 95bb9c2 — `ToolProgress` event in `events.py` and a
    3s asyncio ticker in `runner.py` per in-flight `tool_call_id`.
    Fan-out only (ephemeral via `_emit_ephemeral`), not in the ring
    buffer and not persisted. Tickers cancel on `ToolCallEnd` and in
    the turn-finally teardown.
  - P2 ✅ shipped 2788b60 — reducer records `lastProgressMs` on the
    matched `LiveToolCall`; `MessageTurn.formatElapsed` uses
    `max(local delta, server floor)` so a throttled backgrounded tab
    still paints honest elapsed numbers.
  - P3 ✅ shipped 68d9e9b — 15s idle ping in `_forward_events` using
    `asyncio.wait_for(queue.get(), timeout=…)`. Frame shape
    `{type:"ping",ts}` with no `_seq` so replay cursors stay on
    real events. Failed ping sends break the forwarder out so the
    handler's finally block cleans up corpse sockets whose FIN was
    lost. Three unit tests against `_forward_events` directly.

  **Verify:** DevTools → Network → WS should show `tool_progress` frames
  every ~3s spanning the full sub-agent window, each `tool_call_id`
  matching the outer `Agent` `ToolCallStart`. The Claude transcript
  JSONL stays unchanged (we don't write upstream). `/api/diag`
  subscriber count can back up the ticker-lifetime check.

  **Risk callouts:** (1) `sessions_broker.py` now runs alongside the
  runner — the keepalive task must live under the runner task tree,
  not the broker, so shutdown / stop cancels it cleanly. (2) runner.py
  is 823 lines (over the 400-line cap flagged elsewhere in this file);
  P1 adds ~30 lines, which should land inside the planned runner
  extraction if close on the queue, or carry a tombstone otherwise.
  (3) Midnight Glass is now the default theme — P0 affordance must use
  theme tokens / existing tailwind utilities, not hardcoded colors.

- [x] **Feature: "More info" button next to Copy on assistant
  responses (2026-04-21, shipped v0.12.1 / frontend 0.8.3).** Dave's
  ask: each assistant turn already has a Copy button in its action
  row; add a sibling button that, when clicked, sends a follow-up
  prompt to the agent asking it to go into more detail on the same
  issue/topic from that response. Implementation: new `ℹ MORE`
  button in the `MessageTurn` footer action row, gated to the
  most-recent finished assistant turn (computed in `Conversation`
  via `latestAssistantTurnKey`). Click pre-fills the composer with
  `Please go into more detail on your previous response.` and
  focuses the textarea — no auto-send, so Dave can append a
  qualifier or Esc-cancel. Five new unit tests in `MessageTurn.test`
  cover render-only-on-latest, hidden-during-stream, hidden-on-
  older-rows, hidden-when-handler-missing, and click-fires-callback.

  **Decisions (2026-04-22):**
  - (a) *Prompt text:* literally `Please go into more detail on
    your previous response.` Short, explicit, model-agnostic. The
    model already has the full turn in context — injecting a
    richer quoted template wastes tokens and risks confusing
    continuity ("which version of the reply am I elaborating
    on?"). Minimal beats clever.
  - (b) *Scope:* most-recent assistant turn only. Per-message
    "more info" on turn 3 when turns 4–10 exist creates an
    inconsistent UX ("am I elaborating on the latest, the picked
    one, or the one I clicked?"). Scrolled-past turns can still
    be elaborated via Quote & reply (a separate button coming in
    the same row). Latest-only keeps the semantics clean and
    spares the row from rendering the button on every historical
    turn.
  - (c) *Auto-send vs. composer pre-fill:* pre-fill + focus, do
    NOT auto-send. Dave often wants to add a qualifier ("more
    detail, especially about X"). One Enter key is cheap; an
    accidental send that burns a turn on the wrong topic is not.
    Also gives a natural cancel path (Esc clears the composer).
  - (d) *Placement + icon:* inline in the footer action row,
    using Dave's small-icon-plus-text ruling (see action-row
    research entry below). Glyph + UPPERCASE 4-char label to
    match the existing `⎘ COPY` convention. Proposed:
    `ℹ MORE`. Row order from left to right: `ℹ MORE` first,
    `⎘ COPY` last (Copy is the fallback / escape hatch, so it
    reads as the rightmost "done" action).

- [ ] **Research: assistant-reply action row — "Spawn sessions from
  this reply" button + brainstorm of other one-click actions
  (2026-04-22).** Dave's primary ask: alongside Copy (existing) and
  More Info (logged above), add a button that takes the *output of
  the current assistant turn only* (not the whole session) and
  asks an LLM to decide the best container shape for whatever the
  reply enumerates — three plausible shapes: (a) a single new
  `checklist` session with N items, (b) N new `chat` sessions (one
  per item), or (c) one new `chat` session covering the combined
  topic. Dave wants the shape decision automated, not chosen by
  him up-front. Then look around the codebase and propose other
  buttons that could live in the same action row. No action —
  research only.

  **Surface.** Single action row at the bottom of each assistant
  article in `frontend/src/lib/components/MessageTurn.svelte`
  (lines 344–356 today — one Copy button, right-aligned,
  `text-[10px] uppercase tracking-wider`). The *header* of the
  same article already has a separate `⋯` menu (lines 274–325)
  that hosts the session-reorg Move / Split actions. The footer
  row is the correct home for *reply-scoped* actions; the header
  ⋯ menu is for *session-shape* actions. Keeping those two lanes
  separate in the taxonomy avoids crowding either one.

  **Primitives that already exist and make "Spawn sessions" cheap
  to wire:**
  - Session-kind discriminator — `sessions.kind ∈ {'chat',
    'checklist'}` with CHECK constraint (`db/schema.sql:24-30`).
    Both shapes are first-class.
  - `POST /api/sessions` (chat creation) and checklist primitives:
    `POST /api/checklists/{sid}/items` + the paired-chat spawn
    `POST /api/checklists/{sid}/items/{iid}/chat`
    (`routes_checklists.py:78, 178`). Paired-chat spawn inherits
    `working_dir`, model, and tags from the parent — so a
    "checklist-with-N-items-that-each-spawn-a-chat" flow is one
    bulk call away once the items exist.
  - Tag/working-dir inheritance: every session needs ≥1 tag, and
    the checklist spawn path already defaults tags from the
    parent. The reply-spawn flow should do the same — inherit the
    current session's tags and `working_dir` unless Dave
    overrides in a preview modal.
  - `Message.content` on the server already carries the full
    assistant reply markdown, so the classifier has a clean input
    and doesn't need to walk the whole transcript.

  **LLM classification is the hard part, and it shares a
  dependency with Session-Reorg Slice 6.** The "pick the right
  shape, then extract the item list + titles + tags" step is a
  sub-agent call. Running it inline in the current session's
  context would pollute the parent. The same blocker gates
  Slice 6 (analyze-for-reorg). Both should wait on the Option 4
  "researcher" sub-agent + token-cost Wave 3 landing, then ship
  as one wave that shares the sub-agent plumbing — classifier
  prompt, structured-JSON output schema, preview modal,
  commit-on-approve. Before Wave 3: a heuristic fallback
  (numbered-list / bulleted-list extraction + length threshold
  to decide checklist vs. 1-chat vs. N-chats) is plausible as a
  v0 but should be clearly labeled "heuristic preview" in the
  UI so Dave doesn't confuse it with the real classifier.

  **UX shape (decided 2026-04-22).** Dave: small icons with
  text. So every action in the row is glyph + space + UPPERCASE
  4-char label, matching the existing `⎘ COPY` convention.
  Initial row (left→right): `ℹ MORE` · `＋ SPAWN` ·
  `❝ QUOTE` · `⎘ CODE` · `⎘ COPY`. Copy stays rightmost as the
  escape-hatch "done" action. Overflow (once the row has >5
  buttons): a footer-side `⋯ MORE↓` dropdown, visually distinct
  from the header `⋯` menu (header = session-reorg, footer =
  reply-scoped — different lanes). Icon-only and pure-dropdown
  layouts both rejected: icon-only sacrifices discoverability
  for the small real-estate saving; pure-dropdown hides every
  primary action behind an extra click.

  **Spawn preview modal** is non-negotiable: classifier output
  is editable (retitle, retag, drag items between proposals,
  drop items), then one approve-all commit that creates the
  checklist+items or the N chats in a transaction.

  **Brainstormed candidates for the action row** (scored for
  "built on existing primitives" vs. "needs new plumbing"):

  Built on existing primitives (ship any time):
  - **Quote & reply.** Pre-fills the composer with
    `> <selected excerpt>\n\n` so Dave can build on a specific
    line without re-typing. No backend work.
  - **Copy code only.** Strip prose, keep fenced code blocks
    concatenated. One function in the copy handler.
  - **Export single turn.** Uses the existing
    `GET /sessions/{id}/export` shape, filtered to one
    `message_id`. Single-turn share instead of whole session.
  - **Jump to tool calls for this turn.** Focus Inspector pane
    on the tool calls belonging to this `message_id`.
    `list_tool_calls` already returns the data; UI-only.
  - **Tokens / cost for this turn.** Tooltip on hover, not a
    nav. `get_session_tokens` is session-level today; would need
    a per-message rollup, but the raw token events exist.
  - **Append to TODO.md.** Pattern-detect "we should later X" /
    "deferred" language in the reply and offer to append the
    relevant paragraph to the nearest TODO.md. Uses existing
    `routes_fs.py` write path.

  Needs the sub-agent plumbing (ship with the Wave-3 bundle):
  - **Summarize / TL;DR.** Cousin of More Info, the other
    direction. Same prompt template family.
  - **ELI5 / Rephrase simpler.** Ditto.
  - **Critique / second opinion.** Spawn a critic sub-agent to
    poke holes. High value before plan execution.
  - **Regenerate.** Redo the previous turn with the same
    prompt; keep both, let Dave pick. Needs a message-branching
    concept the DB doesn't model yet (every message today has
    one parent).

  Needs new DB state:
  - **Pin / bookmark turn.** New `message_pins` column or
    table; show pins as anchors in SessionList.
  - **Save as memory / system-prompt snippet.** When the reply
    establishes a durable rule ("when X, do Y"), push it into a
    memory file or system-prompt addendum. Overlaps with
    `get_session_system_prompt` but that's read-only today.
  - **Rate this reply (👍/👎).** Per-message feedback column
    for quality tracking. Cheap DB, moderate UI.

  **Recommended first wave** (before Wave 3 lands, no sub-agent
  needed): Quote & reply + Copy code only + Export turn + Jump
  to tool calls. These four cost little, fill out the row with
  high-frequency actions, and let Dave live with the new
  pattern before the LLM-powered buttons arrive.

  **Recommended second wave** (with Wave 3): More info + Spawn
  sessions + Summarize + Critique, all sharing one classifier /
  sub-agent call pattern. Ship the preview-modal UX once and
  reuse across all four.

  **Decisions (2026-04-22):**
  - *Row style:* small icons + UPPERCASE 4-char text (Dave's
    ruling). Locked in above.
  - *Spawn preview modal placement:* **floating modal**
    (`SpawnPreviewModal.svelte`), not Inspector-pane hijack.
    Reasoning: the Inspector is the only surface for tool-call
    context, and Dave's workflow when reviewing an
    enumerate-this-reply often involves cross-referencing the
    tool calls that produced the plan. Hijacking the Inspector
    kills that cross-reference at the exact moment it's most
    useful. Floating modal costs one overlay; Inspector hijack
    costs the whole right-pane context. Size it bigger than
    `SessionPickerModal` — the editable-proposal table needs
    real-estate.
  - *Close parent session after Spawn:* **no, by default.**
    Render a checkbox "Close this session after spawning" in
    the preview modal, default unchecked. Reasoning: sometimes
    the enumeration is mid-conversation and Dave keeps asking
    questions; auto-closing would surprise him. The "punch list
    handoff" case where auto-close *is* what he wants is
    catchable with one checkbox. Reopen is one PATCH away
    (`POST /sessions/{id}/reopen` exists) so the cost of getting
    it wrong is low either direction — but defaulting to "leave
    open" preserves the conversation contract.
  - *Heuristic-v0 or wait for Wave 3:* **ship heuristic v0
    now**, swap the classifier in when Wave 3 lands. Reasoning:
    Wave 3's ETA is unbounded; the heuristic (numbered/bulleted-
    list extraction + length threshold → checklist vs. N-chats
    vs. 1-chat suggestion) is tractable and the preview modal
    corrects mis-classifications. Shipping v0 exercises the
    spawn transaction path, the preview UX, and the row
    integration, so Wave 3 becomes a backend swap with zero UI
    churn. Label the modal banner "heuristic preview — review
    before spawning" so Dave never mistakes it for the real
    classifier.
  - *Brainstorm vetoes* (from the list above):
    - **Regenerate — drop.** Needs a message-branching schema
      (every message today has one parent). Big plumbing cost
      for a rare use case. Punt indefinitely unless Dave asks.
    - **Rate reply (👍/👎) — drop.** Nobody's consuming the
      signal; it's UI noise. Revisit only if a concrete
      consumer appears (local fine-tune, feedback analytics).
    - **Save as memory / system-prompt snippet — punt to own
      entry.** Real use case, but the system-prompt API is
      read-only today and "where does the memory persist"
      (session, tag, global) is a non-trivial feature design.
      Doesn't belong as a one-click row button.
    - **Append to TODO.md — punt to own research entry.**
      "Nearest TODO.md" is ambiguous in Bearings' model
      (server cwd? Dave's project cwd? session `working_dir`?).
      Needs its own tiny design, not a row button.
    - **Pin / bookmark turn — keep on maybe list.** Session
      Reorg's split/move covers most curation needs, reducing
      pin's value. Not committed, not vetoed. Revisit after
      Session Reorg Slices 3–7 ship.
  - *First-wave row buttons* (pre-Wave-3, no sub-agent):
    **`❝ QUOTE`, `⎘ CODE`, `⬇ SAVE`, `⎯ TOOL`.**
    - `❝ QUOTE` — pre-fills composer with `> <reply excerpt>`.
    - `⎘ CODE` — copy fenced code blocks only, concatenated.
    - `⬇ SAVE` — export single turn as Markdown via filtered
      `/sessions/{id}/export`.
    - `⎯ TOOL` — focus Inspector on this turn's tool calls.
      (Chose `⎯ TOOL` over `🔧` to stay monochrome-ASCII-
      friendly with the rest of the row; Tailwind emoji
      rendering is inconsistent across fonts.)
  - *Second-wave row buttons* (with Wave 3, shares sub-agent
    plumbing): **`ℹ MORE`, `＋ SPAWN`, `✂ TLDR`, `⚔ CRIT`.**
    All four hit the same classifier/sub-agent call pattern and
    the same preview-modal UX (except `ℹ MORE` which just
    pre-fills the composer — no modal needed). Shipping them
    together means writing the sub-agent plumbing once.
  - *Spawn button label wording:* `＋ SPAWN`, not `＋ SESSIONS`
    or `＋ CHECKLIST`, because the shape is classifier-chosen
    and the label shouldn't lie about which shape is coming.
    "Spawn" is a verb already used in the codebase
    (`spawn_paired_chat`) so it's consistent with internal
    vocabulary.

- [ ] **Upstream: plan mode pins a stale plan file across topic pivots
  (2026-04-21).** Discovered in the Checklists session
  (`f66b7166…`) while trying to plan the checklist feature. Entering
  plan mode auto-selected `~/.claude/plans/enumerated-inventing-ullman.md`
  (the unrelated token-cost-mitigation plan from hours earlier in the
  same session) as "the only file you are allowed to edit." System-
  reminder verbatim: *"A plan file already exists at
  /home/beryndil/.claude/plans/enumerated-inventing-ullman.md. You can
  read it and make incremental edits using the Edit tool. … this is the
  only file you are allowed to edit — other than this you are only
  allowed to take READ-ONLY actions."* Forces a choice between
  clobbering a still-valuable unrelated plan or appending a mismatched
  section to a file on a different topic; no in-mode affordance to
  mint a fresh plan file. Selection isn't pure "most recently modified"
  either — `sparkling-triaging-otter.md` was newer on disk (Apr 21
  14:29) than `enumerated-inventing-ullman.md` (13:35), so the harness
  appears to remember a per-session assignment. Confirmed **not a
  Bearings bug**: `grep` across `src/` shows every `~/.claude/plans/`
  reference is an in-code comment pointing at plan docs for trace-
  ability — no file-selection logic, no system-reminder emission, no
  plan-path wiring through `AgentSession` / `prompt.py`. The reminder
  is emitted by Claude Code's plan-mode harness inside `claude-agent-
  sdk` / the CLI, upstream of Bearings. **Action:** file upstream to
  Anthropic / Claude Code asking for one of — (1) mint a fresh three-
  word-slug plan file per topic by default, (2) prompt "resume X or
  start a new plan file?" on plan-mode entry, or (3) allow the agent
  to `touch` a new file in `~/.claude/plans/` from within plan mode.
  Also a sibling bug Dave flagged in the same turn: plan-mode
  dropdown behavior needs its own investigation (tracked separately
  once reproduced). Workaround: drop out of plan mode, hand off to a
  fresh session, replan there. **Filed upstream 2026-04-24:**
  https://github.com/anthropics/claude-code/issues/53046 (refile of
  canonical stale-closed #21131 per its auto-close invitation; Adam
  Goyer's and SeanHollen's comments on #21131 cited as evidence of
  the deadlock). **Workaround codified 2026-04-24:**
  `~/.claude/rules/plan-mode-stale-pin-workaround.md` — experiment in
  this session showed plan-mode lockdown is soft (system-reminder
  only, emitted only at first entry), so `ExitPlanMode` →
  `EnterPlanMode` round-trip clears the constraint without needing
  to clobber, archive, or hand off to a fresh session. Retire rule
  when #53046 ships a proper fix.

- [ ] **Feature: Session Reorg — message triage across sessions.**
  Plan: `~/.claude/plans/sparkling-triaging-otter.md`. Session:
  `a0a4f828…` (tag: Bearings). Slices 1–5 + 7 shipped (see CHANGELOG
  for v0.3.17–v0.3.22). Slice 6 still open:

  - [ ] **Slice 6 — LLM-assisted analyze (~1–2 days, BLOCKED on
    token-cost Wave 3).** `POST /sessions/{id}/reorg/analyze`
    dispatches a sub-agent (needs Option 4 "researcher" to land first
    so the analysis doesn't pollute the parent context). Returns
    structured JSON proposal; UI renders as an editable table where
    Dave can retitle, retag, drag messages between proposals, and
    approve individually. Fallback until Wave 3: rule-based heuristic
    (long-silence split + keyword-shift split) as placeholder.

  Open design questions (see plan §"Open questions for Dave"):
  cost-attribution policy (leave on source vs. follow messages),
  undo-window length (30s default), Slice-6 priority (ship 1–5 first
  or put 6 on the critical path), tool-call-group warn-vs-refuse.

## v0.6.x — Directory Context System (open slices)

`v0.6.0` foundation shipped 2026-04-22 (see CHANGELOG). Remaining:

### v0.6.1 — session-layer integration

- [ ] **`history.jsonl` session lifecycle writer.** Session-start
  appends a marker (`started`, `session_id`, `branch`); session-end
  updates with `ended`, `commits`, `summary`. If the end hook never
  fires (crash), the start marker stays on disk so the next session
  can see the prior one ended unclean.
- [ ] **Prompt pipeline layer.** New `LayerKind = "directory_bearings"`
  inserted between `tag_memory` and `session` in
  `assemble_prompt()`. Sourced from manifest summary, state
  environment block, all pending ops, last 10 history lines. Size
  cap ~800 tokens. Per-turn filesystem reads (same cadence as tag
  memories today).
- [ ] **Stale-state detection.** At session start, read
  `state.toml.environment.last_validated`. If > 24h, re-run the
  cheap checks (step 3). If > 7 days, re-run steps 2+3+5. If a
  pending operation's `started` > 30 days old, flag in the brief
  as "stale, may already be resolved."

### v0.6.2 — automatic onboarding

- [ ] **Auto-trigger on WS-open.** When a Bearings session opens in
  a directory without `.bearings/`, generate and present the brief
  as the first assistant message. User confirms in chat prose.
  Agent writes the files on confirm.
- [ ] **Dogfood against `~/Projects/Bearings` itself.** First
  `.bearings/` ever written lives here. The test case that matters:
  the step-5 grep finds "Twrminal" in `CHANGELOG.md` and the brief
  reports it as *historical record, not a rename in progress* —
  not as a problem. This false-positive copy ships in the test
  fixture.

### v0.6.3+ — polish

- [ ] **`checks/on_open.sh` execution framework.** Spawn with
  timeout, capture stderr, attach exit code + stderr snippet to
  the brief. No plugin system; shell script is the API.
- [ ] **`bearings status` / `bearings log` / `bearings pending list`
  polish.** Color, terminal-aware formatting, `--last N`.
- [ ] **Read-only filesystem graceful degrade.** If `.bearings/`
  can't be written, onboarding succeeds and presents the brief but
  skips the write with a warning. Brief still reaches the session
  prompt; only persistence is lost.

### Explicit non-goals (deferred)

- Cross-directory state; each `.bearings/` is independent. Shared
  knowledge lives in Bearings' tag memories.
- Remote sync of `.bearings/`. Local only. User can `git add` it
  or `.gitignore` it.
- GUI editor for bearings files; TOML is editable enough.
- Plugin system for `checks/`; shell scripts are the API.
- Encryption; the files carry no secrets.
- Versioning of bearings files; git covers history when the
  directory is a repo.

## Intra-call tool output streaming (flagged, scoped)

Goal: in the terminal-style tool-work pane, have each call's stdout land
line-by-line as it's produced — not dumped whole at `tool_call_end`.
Matters for long-running `Bash` (e.g. `npm run build`, large searches)
where today the user stares at amber `●` for 30s, then a wall of output
appears. Frontend (MessageTurn.svelte, Inspector.svelte) already reacts
to `tc.output` reactively and auto-scrolls; no component change needed
downstream.

### Blocking investigation (resolved 2026-04-24)

- [x] **Verify SDK custom-tool registration in `claude-agent-sdk` 0.1.66.**
  ✅ Available. `create_sdk_mcp_server()` + `@tool` decorator are
  exported from `claude_agent_sdk` and Bearings already uses them in
  `agent/mcp_tools.py` (the `bearings__get_tool_output` tool from the
  token-cost wave). Path B is unblocked without a fork.
- [x] **Protocol trace of `subprocess_cli.py`.** Resolved by reading
  the SDK + Anthropic streaming spec — no live trace needed. The CLI
  follows Anthropic's streaming protocol: `content_block_delta` only
  carries `text_delta` / `thinking_delta` / `input_json_delta`; tool
  results come back as complete `ToolResultBlock` items inside a
  trailing `UserMessage`, never streamed. Confirmed against
  `_internal/transport/subprocess_cli.py:_read_messages_impl` (yields
  complete JSON objects only — speculative parse until full object) and
  `types.py:StreamEvent` (`event: dict[str, Any]` with no partial-tool-
  output schema in the spec). **Path A is dead** — even with a fork
  there are no partial frames on the wire to forward.

### Paths

- **Path C — Synthetic-delta spike.** ✅ Effectively shipped as
  bulletproof plumbing in commit `1359531` (2026-04-20):
  `ToolOutputDelta` event + frontend reducer (with ordering, cap, and
  truncation invariants) + runner consumer + idempotent DB append.
  Coalescer extracted in `d019285`. Pipe is structurally proven via
  `frontend/src/lib/stores/conversation.svelte.test.ts`. No live
  emitter wired — that was always Path B's job.
- **Path B — Bearings-owned Bash tool via SDK custom tool (6–10h).** ←
  **the remaining real work.** Register an in-process Bash
  implementation as an MCP tool (`bearings__bash`); run the subprocess
  locally with `LineBuffer`-backed chunking; push each line as a
  `ToolOutputDelta` into the runner's emit path; return the final
  combined output synchronously to satisfy the SDK contract. **Open
  design questions** to settle before coding:
  - **Side channel for deltas.** The `@tool`-decorated callable returns
    its final dict synchronously to the SDK — there's no return-stream.
    Deltas need a side path. Cleanest: pass a per-session `emit_delta`
    callback into the tool factory at `build_bearings_mcp_server` time
    (closure capture, same pattern as `db_getter` already uses); the
    callback pushes onto an `asyncio.Queue` consumed by `session.stream`
    and yielded as `ToolOutputDelta` events. Avoids reaching across
    the runner boundary.
  - **Replacing built-in `Bash`.** Add `Bash` to `disallowed_tools` and
    `mcp__bearings__bash` to `allowed_tools`. Risk: the model is
    trained on the name `Bash` and may keep trying it. A short system-
    prompt addendum ("for shell commands, use `mcp__bearings__bash`")
    plus the `disallowed_tools` denial should retrain it within a
    turn, but verify in a real session before declaring the feature
    done. Researcher subagent at `agents.researcher.tools` also lists
    `Bash` (`session.py:570`) — needs the same swap.
  - **Permission flow.** Built-in `Bash` rides the existing
    `can_use_tool` gating. The MCP tool needs the same — check the
    `permission_mode` and `tool_permissions` interaction with custom
    MCP tools; should "just work" but verify with a plan-mode session.
  - **Researcher subagent.** Sub-agents inherit options? Or do we have
    to set their tool list explicitly? Path: `AgentDefinition` at
    `session.py:560` — currently lists `Bash`. Update there.
  - **Builtins still used by the model.** `Read`, `Grep`, `Glob`,
    `Edit`, `Write`, `WebFetch` etc. don't stream — out of scope. The
    chatty long-runner is `Bash` (and downstream `Task` calls running
    `Bash`); that's where the user actually waits.
- **Path A — SDK fork + subprocess stream parsing.** ❌ Dead. See
  blocking-investigation note above — the CLI does not emit partial
  tool output on the wire, so a fork has nothing to extract.

### Files that change (shared across paths)

- `src/bearings/agent/events.py` — add `ToolOutputDelta` Pydantic model
  + extend event union.
- `src/bearings/agent/session.py` or `runner.py` — emit deltas (source
  differs by path).
- `frontend/src/lib/api/core.ts` — add `ToolOutputDeltaEvent` + union.
- `frontend/src/lib/stores/conversation.svelte.ts` — new case appending
  `event.delta` to the matching `tc.output`; ignore deltas when
  `tc.finishedAt !== null` (guard against out-of-order).
- No change to `MessageTurn.svelte` / `Inspector.svelte` / `schema.sql`.

### Gotchas (must be handled, not just listed)

- **Reconnect mid-tool**: WS drop loses unseen chunks. Persist the
  cumulative `output` to DB on each delta (idempotent update) so
  history endpoint stays authoritative.
- **Chunk boundaries**: split-mid-UTF-8 corrupts multibyte characters;
  split-mid-ANSI-escape breaks color. Backend buffers until a newline
  (or complete codepoint minimum) before flushing.
- **Memory cap**: pathological 1GB tool output shouldn't balloon the
  browser store. Cap `tc.output` to e.g. 5MB in the reducer, mark
  `truncated: true`.
- **Event ordering**: rely on the ring buffer's `_seq`. Reducer drops
  deltas whose target call is already finished.

### Decision (updated 2026-04-24)

Pipe is shipped (Path C plumbing landed 2026-04-20). Path A is dead.
**Path B is the next step** — implement `bearings__bash` as an
in-process MCP tool with side-channel delta emission, swap built-in
`Bash` out via `disallowed_tools`, and verify the model retrains to the
new tool name within a turn. Reserved as its own work item — see
checklist follow-up.

## Ops / service

### 2026-04-21 — bearings.service went offline, did not auto-recover

- **What happened:** Service received a clean SIGTERM at 15:45:19 CDT and
  shut down gracefully. Not OOM (system had 15Gi free, no dmesg OOM
  events, process peaked at 2.2G). Not `systemctl --user stop` (journal
  has no "Stopping bearings.service" line). Not shell-initiated (no
  `kill`/`pkill`/`stop` in `~/.config/zsh/.zsh_history`). Signal source
  unidentified — something outside the systemd cgroup signaled PID
  3025759 directly. No restart because `Restart=on-failure` treats clean
  TERM as success.
- **Fix shipped:** Unit at `~/.config/systemd/user/bearings.service`
  changed to `Restart=always`, `RestartSec=3`, with
  `StartLimitIntervalSec=60` / `StartLimitBurst=5` to prevent flap loops,
  and `SuccessExitStatus=143` so a clean TERM still counts toward the
  burst budget. Backup at `bearings.service.bak`. Reloaded, restarted,
  verified `/api/health` 200.
- **Follow-ups shipped 2026-04-24** (Bearings session
  `d44baee13ad844f9b150364f4bab5078`):
  - [x] **Sender attribution.** Both halves landed:
    - System-wide audit rule at `/etc/audit/rules.d/bearings.rules`:
      `-a always,exit -F arch=b64 -S kill -F a1=15 -k bearings_term`.
      `auditd.service` enabled + active. Verified end-to-end with a
      test SIGTERM — capture records sender `comm`/`exe`/`pid`/`auid`
      and target `opid`/`ocomm`. Post-mortem retrieval:
      `sudo ausearch -k bearings_term --start <timestamp>`.
    - `ExecStopPost=%h/.local/bin/bearings-sigterm-forensic` writes
      forensic context (exit code/status, recent journal, `loginctl`
      sessions, `last`, listeners on :8787, top user procs by CPU)
      to `~/.local/share/bearings/sigterm-forensic.log` on every
      stop. Self-trims when log exceeds 1500 lines. Verified
      populated on restart of 2026-04-24 18:02.
  - [x] **Memory backstop.** `MemoryMax=4G` set on the unit. Peak
        observed 2.0–2.2G; 4G gives ~2× headroom for Slice-5+ reorg
        work. `MemoryHigh` left unset (kernel-killed backstop only,
        no throttling).
  - **Backups:** original pre-Apr-21 unit at `bearings.service.bak`;
    pre-forensic-hook unit at `bearings.service.pre-forensic.bak`.
  - **Not done (deferred to Security-audit § Systemd hardening):**
    `ProtectHome` / `PrivateTmp` / `NoNewPrivileges`. `ProtectHome`
    cannot be `yes` or `read-only` — the SQLite DB lives in
    `~/.local/share/bearings/`. `PrivateTmp=yes` and
    `NoNewPrivileges=yes` are safe additions and should ride with
    the Security-audit pass.

### 2026-04-21 — slice 5 frontend shipping a request the backend doesn't serve — resolved

- `GET /api/sessions/{id}/reorg/audits` returned 404 in the logs right
  before the outage (unrelated to the shutdown — process was healthy
  after). The `ReorgAuditDivider.svelte` component expects that route.
- **Resolved 2026-04-24 (verification only — no code change).** The 404
  was logged on 2026-04-21; the missing pieces actually landed the same
  day in `7eb5558` (`feat(reorg): merge route + persistent audit
  divider (Slice 5, v0.3.21)`). All four layers are wired:
  - migration `0014_reorg_audits.sql` + `schema.sql:163` table.
  - store helpers `record_reorg_audit` / `list_reorg_audits` /
    `delete_reorg_audit` in `db/_reorg.py`.
  - `GET /sessions/{id}/reorg/audits` + `DELETE …/{audit_id}` in
    `api/routes_reorg.py:361-402`, mounted via
    `server.py:164` under `/api`.
  - frontend client `listReorgAudits()` at
    `frontend/src/lib/api/sessions.ts:536`.
  Live probe `curl http://127.0.0.1:8787/api/sessions/<id>/reorg/audits`
  returns 200 against the running service. Nothing to ship.

## Performance optimization

### 2026-04-21 — Audit: frontend timeline re-derivation

**Static analysis (Conversation.svelte + turns.ts + reducer.ts):**

- Per WS event the reducer mutates one of `streamingText`, `streamingThinking`,
  or replaces `state.toolCalls` with `.map()` (every `tool_output_delta` /
  `tool_call_end`). All three feed `$derived` getters on `ConversationStore`.
- `Conversation.svelte` has two stacked `$derived` blocks downstream:
  1. `turns = $derived(buildTurns({...}))` — O(messages + toolCalls) per fire:
     allocates a fresh `Map<messageId, LiveToolCall[]>`, walks every message,
     allocates a new `Turn[]`.
  2. `timeline = $derived.by(...)` — O(turns + audits) plus an O(n log n)
     **sort** by ISO timestamp. Allocates a new `TimelineItem[]`.
- Highest-frequency triggers: `token`, `thinking`, `tool_output_delta`,
  `tool_call_end`. On a typical streaming turn (~30 tok/s plus tool deltas),
  worst case is ≥30 buildTurns + timeline rebuilds per second.
- Open question: Svelte 5's `$derived` is lazy + memoized within a microtask,
  so rapid back-to-back state mutations may collapse to a single recompute
  per frame. **This is the question the instrumentation answers** — without
  numbers, we can't tell whether the rewrite is worth the risk.

**Instrumentation in place:**

- `frontend/src/lib/components/Conversation.svelte` now has two
  `console.count` calls (DEV only) on the `turns` and `timeline` derivations,
  tagged `bearings:audit:buildTurns` and `bearings:audit:timeline`.

**Reproduction:**

1. `cd frontend && npm run dev`
2. Open the UI, pick a session, send a prompt that produces a long
   tool-heavy reply (e.g. a Bash command with streaming output).
3. Watch the DevTools console. Compare counter increments against:
   - WS event count (Network tab → WS frames),
   - approximate token rate from the model.
4. If counters track WS events ~1:1 → confirmed hot, proceed to refactor.
   If counters fire ≪ WS events (batched per frame) → close the audit, the
   `$derived` scheduler already mitigates it.

**Measured 2026-04-21 (one tool-heavy turn: 3 bash commands + summary
paragraph; estimated ~200–300 WS frames):**

- `bearings:audit:buildTurns`: **224 fires**
- `bearings:audit:timeline`:  **227 fires**

Ratio to estimated WS frames is essentially 1:1. Svelte's `$derived`
scheduler is **not** batching these — every WS event walks the full
message + tool-call list in `buildTurns` and rebuilds + resorts the
whole `timeline`. The 3-fire gap is `timeline` reacting to the
`audits` array fetched on session load, which `buildTurns` doesn't
see. **Audit verdict: hot. Refactor is justified.**

**Refactor sketch (only if confirmed hot, and only after sibling
`Profile event frequencies before deeper work` lands real numbers):**

- Promote `turns` and `timeline` from `$derived` to `$state` arrays held
  inside `ConversationStore`, keyed by session id.
- Build the full array once on `load(sessionId)` and `loadOlder()`.
- Mutate the **tail turn** in place during streaming: push tokens into
  `tail.streamingContent`, append tool calls to `tail.toolCalls`. Push a
  new tail on `message_complete`.
- Insert audits at their sorted position only on `refreshAudits()` —
  audit timestamps don't shift mid-stream, so no per-event resort.
- Keying via `{#each timeline as item (item.key)}` already in place; just
  needs the underlying array to mutate-in-place rather than re-allocate.

**Cleanup ticket:** ~~remove the two `console.count` calls before merging
the refactor~~ — done 2026-04-23, both probes dropped when item 5 shipped.

**Resolution 2026-04-23 (commit `82c0bfa`):** shipped as a narrower
variant of the sketch rather than the full $state promotion. `turns.ts`
split into `buildSettledTurns` (cheap, WeakMap-cached on assistant
Message identity — returns reference-stable Turn objects when nothing
about the settled portion changed) + `buildStreamingTail` (rebuilds
only the live tail per token event). `Conversation.svelte` now has
two stacked `$derived.by` blocks: `settledTurns` (invalidates only on
messages/toolCalls array changes) and `turns` (cheap combine of
settled + tail). Scope:benefit ratio beat the full reducer-owned-
$state rewrite because it fixes the MessageTurn re-render storm
without churning the reducer/state ownership model.

Remaining headroom if this doesn't close the sluggishness entirely:
the sketch's per-turn tail mutation would additionally prevent the
streaming `turns` array from re-allocating per token, but the
settled-turn cache already handles the dominant cost (MessageTurn
reflow of every already-settled turn).

**Resolution 2026-04-24 (item 29 / full $state promotion):** the
remaining-headroom variant landed. `turns`, `audits`, and `timeline`
are now first-class `$state` arrays on `SessionState`, owned by the
reducer. Per-event paths (`token`, `thinking`, `tool_call_start`,
`tool_output_delta`, `tool_progress`, `tool_call_end`,
`message_complete`) mutate the existing tail Turn in place — no
`buildSettledTurns` / `buildStreamingTail` / sort fires per WS frame.
Full rebuilds (`rebuildTurnsFromMessages` + `recomputeTimeline`)
only run on `load`, `loadOlder`, `refreshMessages`, `applyMessagePatch`,
and `setAudits` — the points where the underlying arrays change shape
wholesale. `Conversation.svelte` now reads `conversation.timeline`
directly and the local `audits = $state(...)` declaration moved
into the store as `setAudits` + a `$derived` getter so the timeline
re-merge happens server-side of the view. Test coverage added in
`stores/conversation.svelte.test.ts` under "in-place tail mutation"
asserts: tail Turn identity stable across 50 token events, tail
`toolCalls` array reference stable across 25 deltas, finalize
preserves Turn identity (only `isStreaming` / `assistant` flip),
open-user-turn absorption on `message_start`, and timeline array
reference stability across token events. The Svelte 5 $state proxy
quirk where pushing the same plain object into two proxied arrays
yields two distinct proxies was caught by the toolCalls-stability
test — the reducer now re-reads the post-push proxy from
`state.toolCalls` before pushing into `tail.toolCalls` so both
arrays share the reactive identity.

### 2026-04-21 — Profile event frequencies (wire + DB)

Pulled `/metrics` and queried SQLite to confirm which event types
dominate and whether historical volume justifies FTS5 and/or timeline
virtualization before we build them.

**Wire event mix** (one process lifetime: 40 assistant turns, 299 tool
calls; captured `bearings_ws_events_sent_total` via
`curl /metrics`). Share of total = 2369 events emitted:

| type              | count | share  | per assistant turn |
|-------------------|------:|-------:|-------------------:|
| token             |  1561 | 65.9%  |              39.0  |
| tool_call_start   |   300 | 12.7%  |               7.5  |
| tool_call_end     |   299 | 12.6%  |               7.5  |
| thinking          |    88 |  3.7%  |               2.2  |
| message_start     |    41 |  1.7%  |               1.0  |
| context_usage     |    40 |  1.7%  |               1.0  |
| message_complete  |    40 |  1.7%  |               1.0  |
| tool_output_delta |     0 |  0.0%  |               0.0  |

- `token` dominates at 2/3 of all frames — this is the wire-volume
  bottleneck.
- `tool_call_*` pairs are the second-biggest block at 25% combined.
- Average turn = ~60 wire events. The frontend re-derivation audit
  measured 227 fires on one tool-heavy turn, so heavy-turn fan-out is
  roughly 4× the average (variance is real, tail is long).
- `tool_output_delta` never fired in this sample. Either streaming tool
  output is rare in Dave's actual usage or the translator in
  `session.py` doesn't currently emit it for any observed tool shape.
  Worth a follow-up but not a blocker — it can only increase the token
  dominance, not flip the verdict.

**DB / historical scale** (read directly from SQLite):

| metric                                   | value |
|------------------------------------------|------:|
| db.sqlite size                           |  15MB |
| sessions                                 |    41 |
| messages                                 |   518 |
| tool_calls                               | 4 146 |
| avg msgs / session                       |  14.0 |
| avg tool_calls / session                 | 105.5 |
| sessions with >100 timeline items        |    15 |
| sessions with >300 timeline items        |     3 |
| largest session (msgs + tool_calls)      |   580 |

**Verdicts:**

- **Timeline virtualization: justified, schedule after frontend
  re-derivation refactor.** Three of 41 sessions already exceed 300
  timeline items and the largest is 580. Combined with the sibling
  audit's 1:1 re-derivation finding, opening a large session walks
  every item on every WS frame — hundreds of nodes × hundreds of
  frames. Virtualization is only worthwhile *after* the re-derivation
  fix promotes `turns`/`timeline` to `$state` arrays that mutate in
  place; until then, virtualization optimizes rendering of a structure
  that's also being needlessly rebuilt per event. Sequence matters.
- **FTS5 search: stop.** 518 messages and 4146 tool calls in a 15MB DB
  is inside "LIKE scans in milliseconds" territory. Revisit if total
  messages cross ~50k or if a search UX ships and profiling shows
  query latency above ~50ms. Noting the decision here so a future
  session doesn't re-open it without new data.
- **Token event reduction: out of scope for this pass, but flag it.**
  66% of wire frames is token streaming. If the re-derivation refactor
  + virtualization still leave the UI janky under streaming, the next
  lever is token batching on the server (coalesce N tokens per frame,
  like `_flush_tool_buffer` already does for tool output). Do not do
  this pre-emptively — measure first.

**Next checklist items implied:**

- Keep `Performance optimization` open with two live children:
  - Implement frontend re-derivation refactor (sibling; now unblocked
    by these numbers).
  - After that lands, add timeline virtualization for sessions >N
    items (N = 200 as starting threshold, well below the observed 580
    max but above the 100 average).
- FTS5 and token-batching stay off the checklist.

**Resolution 2026-04-24 (item 34 / timeline virtualization):** shipped
on the heels of item 29's full $state promotion. New
`frontend/src/lib/components/VirtualItem.svelte` is a per-entry
lazy-mount wrapper backed by IntersectionObserver + ResizeObserver:
off-screen items render as a `min-height` placeholder that resolves to
the item's measured height after the first paint, on-screen items
render their full slot. `Conversation.svelte` flips on virtualization
when `timeline.length > 200` (the threshold from this audit) and force-
mounts the streaming tail plus the bottom-30 warm band so auto-scroll
and the in-place reducer mutations land on real DOM. Below threshold
the existing `{#each}` render is preserved verbatim — virtualization
isn't free (one IO + one RO per item) so we only pay the cost when
there's something to recover. `loadOlder`'s existing scroll-anchor
arithmetic (`scrollTop = scrollHeight - prevHeight`) keeps working
unchanged because the placeholder reserves height via `min-height`,
so prepended items contribute their fallback or measured height to
`scrollHeight` immediately. Test coverage in
`frontend/src/lib/components/VirtualItem.test.ts`: starts unmounted,
promotes on intersection, returns to placeholder with measured min-
height on exit, applies `fallbackHeightPx` before first measurement,
threads `scrollRoot` + `rootMargin` to the IO, disconnects on unmount,
fails open (renders content) when IntersectionObserver is unavailable.
Threshold + warm-tail logic in `Conversation.svelte` is trivial inline
math (`> 200`, `idx >= length - 30`) so no integration test was added
— the meaningful behavior is in `VirtualItem` itself.

### 2026-04-23 — Follow-up audit: additional sluggishness sources

Dave reported the app is "very very sluggish." Re-read the hot path end
to end. The 2026-04-21 re-derivation finding still holds and is the
headline. Additional issues found, in priority order:

- [x] **Reducer allocates new `toolCalls` array per delta.** Shipped
  2026-04-23. `frontend/src/lib/stores/conversation/reducer.ts` —
  `tool_call_start` now `push`es into `state.toolCalls`, and
  `tool_output_delta` / `tool_call_end` now `find` the matched tc and
  mutate its fields in place. Restores the "mutate in place" invariant
  the file header already documented. Original finding retained below
  for the audit trail.
  `frontend/src/lib/stores/conversation/reducer.ts:229,256,276`.
  The `tool_call_start` / `tool_output_delta` / `tool_call_end` arms
  all do `state.toolCalls = state.toolCalls.map(...)` or
  `[...state.toolCalls, newOne]` — a fresh array of fresh objects per
  event, despite the file's "mutate in place" header. This is the
  upstream cause of the 1:1 `buildTurns` rebuilds measured on
  2026-04-21: every delta invalidates `state.toolCalls`, which
  invalidates `turns`, which invalidates `timeline`. Fix by mutating
  the matched `tc` in place (`tc.output = capped.output`) and
  `state.toolCalls.push(...)` for the start case. Svelte 5 `$state`
  proxies propagate in-place mutation. **This fix is a prerequisite
  for the sibling re-derivation refactor to actually pay off** — even
  after promoting `turns` to `$state`, if the reducer keeps replacing
  `toolCalls`, downstream rebuilds still fire.

- [x] **Streaming assistant turn re-parses markdown + re-runs shiki
  on every token.** (fixed 2026-04-23.) Picked option (b) over (a) so
  the streaming user still sees formatted headings / fenced code, but
  the marked+shiki pass now runs at most once per browser frame.
  `CollapsibleBody.svelte` maintains a `renderedHtml` `$state` that is
  updated synchronously when `disabled=false` (settled turn, pinned /
  search / pagination paints stay instant) and rAF-coalesced when
  `disabled=true` (streaming assistant turn). Pending rAFs are
  canceled on prop flip and on unmount. New coverage:
  `CollapsibleBody.test.ts` — sync-paint assertion when not streaming,
  rAF-coalesce assertion that three content flips during streaming
  only fire the marked pass once.

- [ ] **MessageTurn re-serializes tool-call input per delta.**
  `frontend/src/lib/components/MessageTurn.svelte:173-193` and
  `MessageTurn.svelte:61-66`. The `{#each toolCalls}` block calls
  `JSON.stringify(call.input, null, 2)` inline in the template;
  every `tool_output_delta` currently replaces `toolCalls`
  wholesale (see reducer issue above), so every call's `input` is
  re-stringified on every delta even though `input` is immutable
  after `tool_call_start`. The `toolStreamSignal` reduce also
  walks every call's output string per event. Fix: precompute
  `inputPretty` once when the reducer creates the LiveToolCall
  (store it on the object); replace the reduce signal with a
  reducer-incremented counter. Mostly moot once the reducer fix
  above lands, but the precomputed `inputPretty` still wins.

- [x] **Per-event orjson encode + decode hop in the WS fan-out.**
  Shipped 2026-04-23. `_Envelope` now carries a pre-encoded `wire: str`
  built once in `_emit_event`; `ws_agent._forward_events` and the
  replay loop both `send_text(env.wire)` directly. Removes one
  `orjson.dumps(...).decode()` per subscriber per event (and per
  envelope in the replay window). `_send_frame` retained for the
  one-off `runner_status` snapshot on connect. Original finding
  retained below for the audit trail.
  `src/bearings/agent/runner.py:_emit_event` calls
  `event.model_dump()` (full Pydantic dict materialization) per
  Token; `src/bearings/api/ws_agent.py:134-158` then calls
  `orjson.dumps(frame).decode()` in each subscriber forwarder —
  encoding to bytes then decoding back to str because
  `send_text` wants str. With two tabs attached that's 2× wasted
  encode + decode per wire frame (2369 frames measured in the
  2026-04-21 sample). Fix: pre-encode once in `_emit_event`
  (cache the bytes on the envelope), then use
  `websocket.send_bytes(...)` or the raw ASGI send dict path
  with the already-encoded JSON string. Removes one full JSON
  round-trip per subscriber per event.

- [ ] **~35 DB commits per turn.** `src/bearings/db/_messages.py`
  has seven per-helper `await conn.commit()` sites (lines 59, 116,
  273, 290, 315, 342, 365). A typical turn =
  insert_message(user) + insert_message(assistant) + 15× tool_call
  (start + end) + append_tool_output(×N) + attach_tool_calls +
  cost bump ≈ 30–40 commits. WAL + synchronous=NORMAL makes each
  an fsync of the WAL (not the main DB), so this is less
  catastrophic than fsync-FULL would be, but still ~35
  `run_in_executor` hops through the aiosqlite worker thread per
  turn. Fix: wrap the turn in one transaction — remove per-helper
  commits, commit once at the end of `_persist_assistant_turn`,
  commit per-flush-batch for tool output. Read paths on a separate
  connection don't see mid-turn state; fine, the UI rebuilds from
  wire events anyway.

- [x] **Session `load()` eagerly fetches every tool call.** (fixed
  2026-04-23, item 3 of the audit follow-up.) `list_tool_calls` now
  takes an optional `message_ids` filter; the DB helper scopes the
  `SELECT` to `message_id IN (...)` and drops orphans. Route exposes
  it as repeated `?message_ids=` query params. `load()` derives the
  ids from the 50-message page it just fetched, and `loadOlder()`
  now pulls the matching tool_calls for each paginated older page
  so the ToolDrawer still renders under historical messages. Export
  / checkpoint / reorg callers pass `message_ids=None` and keep the
  full-history behavior. New coverage: `test_store.py::
  test_list_tool_calls_filters_by_message_ids`, `test_routes_sessions
  .py::test_get_tool_calls_filters_by_message_ids`.

- [ ] **Subscribe replay walks full 5k ring buffer on every new
  WS.** `src/bearings/agent/runner.py:163-166`. Two tabs reconnecting
  each scan 5000 envelopes. Fix: keep a parallel `dict[seq → index]`
  or use `bisect` over a sorted `deque` for O(log n) replay start.
  Low-priority unless reconnect storms show up in practice.

- [ ] **Unbounded subscriber queues.** `src/bearings/agent/runner.py:341-348`.
  Already flagged in the 2026-04-21 security audit cleanup section;
  noting the performance angle here too. A slow WS client can make
  runner memory balloon; bound the queue (match
  `SessionsBroker.SUBSCRIBER_QUEUE_MAX = 500`) and drop slow
  subscribers — they reconnect with `since_seq`.

**Recommended fix order** (by "ratio of impact to diff size"):
1. Reducer in-place mutation. *(shipped 2026-04-23, `90a1bb7`)*
2. CollapsibleBody rAF markdown coalesce. *(shipped 2026-04-23, `d7b1c3b`)*
3. Split `buildTurns` + WeakMap-cache settled turns. *(shipped 2026-04-23,
   `82c0bfa`)* — narrower variant of the original "$state promotion"
   sketch; see the Resolution note in the 2026-04-21 audit section.
4. Pre-encode WS frames once in `_emit_event`. *(shipped 2026-04-23, `90a1bb7`)*
5. One-transaction-per-turn on the DB.
6. Paginated `listToolCalls` for session load. *(shipped 2026-04-23, `aa54d0a`)*

Items 1–3 are frontend-only and together address the majority of the
streaming-CPU burn. 4–5 matter most when multiple tabs are attached
or heavy concurrent sessions run. 6 fixes session-switch latency
independently.

## Security audit (2026-04-21) — pre-public-release

Full findings live in this session's transcript. Three audits ran in
parallel: privilege/agent-autonomy surface, architectural questionable
decisions, exposed-secrets sweep. Secrets sweep came back clean (modulo
identity leaks listed below). The other two converged on the same root
cause: the codebase was built assuming "localhost = safe" and that
assumption is wired into a dozen separate decisions.

### Ship-blockers (fix before first public push)

These are bugs, not preferences — no toggle, just fix.

- [x] **WS has no Origin check.** `src/bearings/api/ws_agent.py` +
  `src/bearings/api/ws_sessions.py`. Fixed 2026-04-23:
  - New `check_ws_origin` / `_allowed_origins` helpers in
    `bearings.api.auth`. Allowlist derives loopback defaults from
    `server.port` (`http://127.0.0.1:<port>`, `http://localhost:<port>`,
    `http://[::1]:<port>`) and merges in the new
    `ServerCfg.allowed_origins` config field for dev/reverse-proxy
    scenarios.
  - Both WS handlers now close with `4403` + `reason="origin not
    allowed"` before auth runs and before any subscription registers.
    Missing `Origin` fails closed.
  - Test fixtures (`tests/conftest.py`, `tests/test_auth.py`) inject
    `http://testserver` into both the client and the allowlist so
    existing tests keep working.
  - New `tests/test_ws_origin.py` (7 tests) covers missing/foreign/
    allowlisted origin on both endpoints plus helper unit coverage.
  - 718/718 pytest, ruff + mypy clean.
- [x] **Markdown XSS via `marked` + `{@html}` with no sanitizer.**
  `frontend/src/lib/render.ts` + every consumer that mounts
  `renderMarkdown` output via `{@html}` (`CollapsibleBody.svelte:155`,
  `TagEdit.svelte:308`). Fixed 2026-04-23: added `isomorphic-dompurify`
  (frontend dep), wrapped `marked.parse()` output with
  `DOMPurify.sanitize()` using a narrow tag/attr allowlist that keeps
  the shiki `class`/`style` markup and the
  `data-bearings-code-block`/`data-language` attrs needed by the
  context-menu delegate. New `frontend/src/lib/render.test.ts` pins
  sanitizer behavior (script strip, event-handler strip, javascript:
  URL strip, iframe strip, fenced-block wrapper preservation).
  521/521 vitest green; bundle rebuilt + synced into
  `src/bearings/web/dist`. `SidebarSearch.svelte:106`'s `highlightText`
  is already XSS-safe (escapes before mark-injection, test at
  `highlight.test.ts:23` covers it) — not a hole.
- [x] **`tests/test_tags.py`** — `/home/beryndil/Projects/Bearings`
  hardcoded as test fixture. Identity leak in tracked code. Replaced
  with `/srv/example-project` at the four hit sites (2026-04-23;
  actual lines 529/532/583/589, not 453/456/507/513 as originally
  logged). `uv run pytest tests/test_tags.py` green. Remaining mentions
  of `/home/beryndil` in tracked tree are limited to `TODO.md` and
  `TODO-archive-2026-04-22.md` — operational logs, not fixtures; left
  in place pending an explicit decision on public-repo TODO scrubbing.
- [x] **Migrations run with no transaction wrapping, no checksum, no
  downgrade detection.** Fixed 2026-04-23:
  - New `MigrationDriftError` + `_checksum` + `_ensure_migrations_table`
    in `bearings.db._common`. `schema_migrations` now carries a `checksum`
    column; pre-existing DBs get the column added via
    `pragma_table_info` + `ALTER TABLE` (SQLite has no `ADD COLUMN IF
    NOT EXISTS`). The tracking table is managed at Python level, not
    as a numbered SQL migration — otherwise the runner would depend on
    its own output column.
  - `_apply_migrations` now runs a drift pass before the apply pass:
    unknown applied rows (downgrade / deleted file) are fatal;
    checksum mismatches (edited-after-application) are fatal; NULL
    checksums on pre-existing rows are backfilled from the current
    file. New migrations are recorded with their sha256 on apply.
  - No `BEGIN/COMMIT` wrapping: `executescript` auto-commits inside
    SQLite (documented constraint), so wrapping it is a no-op. The
    INSERT-into-`schema_migrations` only fires on success, so a failed
    migration simply isn't recorded and re-runs next boot — migrations
    must therefore remain idempotent (`IF NOT EXISTS` for creates;
    `ALTER TABLE` changes need manual cleanup on failure). Comment in
    `_apply_migrations` records the constraint.
  - `tests/test_migrations.py` covers: fresh checksum record, NULL
    backfill, unknown-row-fatal, mismatch-fatal, repeat-init
    idempotence, legacy (pre-checksum column) DB upgrade, and
    direct-invocation of `_apply_migrations` against an open
    connection. 729/729 pytest, ruff + mypy clean.
- [x] **`/api/fs/list` enumerates the entire host.** Fixed 2026-04-23:
  - New `FsCfg.allow_root: Path` (default `Path.home()`) in
    `bearings.config`.
  - `list_dir` now takes a `Request`, resolves the configured root
    with `strict=False`, resolves the requested target with
    `strict=True`, and 403s any target that isn't equal to or beneath
    the root. `parents`-based check means symlink escapes (inside-root
    symlink pointing at `/etc`, etc.) are caught.
  - `tmp_settings` fixture points `fs.allow_root` at `tmp_path` so
    every existing test still operates inside the clamp.
  - `test_list_defaults_to_home` renamed to
    `test_list_defaults_to_allow_root`; new dedicated test
    `test_list_root_parent_is_null_when_allow_root_is_filesystem_root`
    replaces the old `/`-parent coverage using an inline
    `FsCfg(allow_root=Path("/"))` client.
  - Four new clamp tests (`test_list_rejects_path_outside_allow_root`,
    `_sibling_of_allow_root`, `_symlink_escape`,
    `test_list_accepts_nested_subdir`). 722/722 pytest, ruff + mypy
    clean. `/fs/pick` left alone — user-initiated native dialog.
- [x] **Resolve `CLAUDE.md:12` "Repository TBD"** — pick the org or remove
  the note before the README ships. (Org chosen 2026-04-22:
  `Beryndil/Bearings`. CLAUDE.md edited 2026-04-23.)
- [x] **Commit-email exposure scrubbed from history** (2026-04-23).
  Two personal email addresses (one school-adjacent, one mainline
  personal) appeared across ~190 commits. Resolved by rewriting all
  history via `git filter-repo --mailmap` to collapse both to a single
  public brand identity — `Beryndil <beryndil@users.noreply.github.com>`
  — and setting the same as the local-repo `user.name`/`user.email`
  override so future commits stay on-brand. Zero occurrences remain in
  commit metadata or tree content. Force-push to `origin/main` still
  pending — remote is already public (beryndil/Bearings) but has no
  forks and no PRs, so the blast radius is GitHub's own cached history
  and whatever's in its blame/activity views; those update on
  force-push. Pre-rewrite backup preserved at
  `~/Projects/Bearings.pre-filter-repo-backup-*` (remove once the
  remote is confirmed clean).

### Permission profiles / toggle layer (v0.2 release scope)

Three profiles selected at first run or via `bearings init <profile>`:

- **`safe`** (public default) — auth on with auto-generated token,
  `working_dir` defaults to `~/.local/share/bearings/workspaces/<id>`
  (sandbox subdir, *not* `$HOME`), `setting_sources=[]` so no global
  Claude config inherits, no MCP inherit, no hook inherit,
  `bypassPermissions` mode disabled and not persisted, Origin check
  enforced (overlaps ship-blocker), `/api/fs/list` clamped to working_dir,
  command/skill scanner scoped to project `.claude/` only, default
  `max_budget_usd` ceiling.
- **`workstation`** (middle) — auth on, `working_dir` defaults to `$HOME`
  but Edit/Write requires per-call approval, MCP/hook inherit allowed,
  `bypassPermissions` allowed but ephemeral (not persisted), everything
  else as `safe`.
- **`power-user`** (Dave's current behavior, opt-in) — current defaults
  restored. Startup banner in stdout lists every gate that's open so the
  user sees exactly what they're running.

Each profile is a preset that writes `config.toml`. Every individual
switch is also independently togglable for mix-and-match. Active profile
shown in UI header.

Implementation order:

- [x] Land all ship-blockers above (they're not behind a toggle).
- [x] Add config schema for every togglable gate. **Shipped v0.11.0
  (2026-04-24).** New knobs: `agent.workspace_root`,
  `agent.allow_bypass_permissions`, `agent.setting_sources`,
  `agent.inherit_mcp_servers`, `agent.inherit_hooks`,
  `agent.default_permission_mode`, top-level `[profile]` section
  (`name`, `show_banner`). Existing knobs (`commands.scope`,
  `agent.default_max_budget_usd`, `fs.allow_root`,
  `runner.idle_ttl_seconds`, `auth.enabled`/`token`) cover the
  remaining audit gates. Wired through to actual behavior:
  - `setting_sources` / `inherit_mcp_servers` / `inherit_hooks` →
    `AgentSession.stream` adds them to `ClaudeAgentOptions` only when
    they diverge from SDK defaults so power-user profile produces a
    byte-identical SDK call to pre-toggle-layer behavior.
  - `allow_bypass_permissions` → `ws_agent.py` `set_permission_mode`
    handler refuses `bypassPermissions` escalation when False, returns
    an `error` wire frame instead of silently ignoring.
  - `workspace_root` → `routes_sessions.py` POST `/api/sessions`
    materializes a per-session sandbox subdir at
    `<workspace_root>/<session_id>` when the caller omits
    `working_dir`. Caller-supplied path still wins. New
    `store.set_working_dir` helper supports the post-create resolution.
  - `default_permission_mode` → `_build_runner` uses it as fallback
    when the persisted `permission_mode` is NULL.
- [x] Build the three preset profiles. **Shipped v0.11.0.** New
  `bearings.profiles` module: `apply_profile(name) → nested dict` of
  config overrides, `merge_profile_into_toml(existing, profile_data)`
  for section-shallow overlay (preserves operator-edited keys the
  profile doesn't touch). `safe`/`workstation`/`power-user` literals
  in `ProfileName`. Auth tokens auto-generated via
  `secrets.token_urlsafe(32)`; re-running rotates.
- [x] Add startup banner that prints active profile + which gates are
  open. **Shipped v0.11.0.** New `_print_profile_banner` +
  `_format_gate_state` helpers in `cli.py`. Visible by default on
  every `bearings serve`; `profile.show_banner = false` opts out.
  Same banner runs at end of `bearings init --profile X` so the
  operator sees their posture immediately.
- [x] Rewrite README intro around the profile model. **Shipped
  v0.11.0.** New top-level §"Permission profiles" section with the
  three-profile gate matrix, before the §Status block. Config table
  extended with every new gate knob.

Test coverage added:
- `tests/test_profiles.py` (12 cases): preset gate values, token
  rotation, merge semantics, round-trip via `_write_profile` →
  `load_settings`, banner format axes, banner with/without active
  profile.
- `tests/test_routes_sessions.py` +2: workspace sandbox materialized
  on POST when working_dir absent; explicit caller path wins.
- `tests/test_agent_session.py` +2: `safe`-profile knobs land on
  `ClaudeAgentOptions`; `power-user` defaults don't add empty
  override values.
- `tests/test_ws_agent.py` +2: `bypassPermissions` refused when gate
  closed; allowed under default config.

929 backend tests pass; ruff + mypy strict + format clean.

### High but not ship-blocker (fold into toggle layer)

All seven items landed 2026-04-23 in the same pass. Where the fix is
an unconditional bug-fix (constant-time compare, DB perms, bind
interlock, systemd hardening) it's applied unconditionally. Where
the item is a policy knob that different profiles will want different
values for (commands scope, idle TTL, global budget ceiling) the
config schema now carries the knob with a backward-compatible default,
and the profile presets (sibling session — "Permission profiles —
safe/workstation/power-user") will flip them. 761/761 pytest,
ruff + mypy clean.

- [x] **Auth-token-in-WS-query-string + non-constant-time compare.**
  `src/bearings/api/auth.py`. Fixed 2026-04-23:
  - Compare routed through `secrets.compare_digest` (helper `_consteq`).
    Applies to both `require_auth` (REST) and `check_ws_auth` (WS).
  - New `Sec-WebSocket-Protocol` transport: client offers
    `bearings.bearer.v1, bearer.<tok>`; server extracts the token
    from the second entry and echoes only the marker via
    `ws_accept_subprotocol` — secret never lands in the negotiated
    protocol response header. Keeps the token out of URLs, access
    logs, browser history, process listings.
  - Query-string path preserved for `bearings send` (CLI, no
    convenient subprotocol plumbing).
  - Frontend migration landed same day (2026-04-23):
    `frontend/src/lib/api/core.ts` now builds a `wsBearerProtocols()`
    list and passes it as the `WebSocket` constructor's second arg;
    `openAgentSocket` and `openSessionsSocket` no longer append
    `token=` to the URL. Browser clients keep the secret out of
    access logs / Referer / browser history entirely.
  - `tests/test_auth.py` +3 tests (subprotocol-good-token,
    subprotocol-bad-token, marker-without-bearer-entry).
  - `frontend/src/lib/api/core.test.ts` +5 vitest cases (agent socket
    subprotocol path, agent socket no-token path, since_seq in URL
    with no token leakage, sessions socket subprotocol path, sessions
    socket no-token path).
- [x] **DB file written at default umask.** `src/bearings/db/_common.py`.
  Fixed 2026-04-23: `init_db` now calls `_clamp_db_permissions(path)`
  after the connection opens and migrations commit, chmod'ing the
  main DB, `-wal`, and `-shm` sidecars to `0o600`. Idempotent across
  reboots so DBs created pre-fix get clamped on next startup.
  `OSError` from exotic filesystems is swallowed (best-effort
  defense-in-depth). `tests/test_migrations.py` +1 test asserts the
  mode after `init_db` + a write to force WAL to materialize.
- [x] **Runner idle_ttl knob toggle-ready.** Already a config knob
  (`runner.idle_ttl_seconds`, default 900.0) per the existing
  `RunnerCfg`. No code change needed — the `safe` profile preset in
  the sibling session will set it to a small value (e.g. 30s or 0)
  when the profile lands.
- [x] **Systemd unit hardening.** `config/bearings.service`. Fixed
  2026-04-23: added `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`,
  `ProtectSystem=strict`, `ProtectKernel{Tunables,Modules,Logs}`,
  `ProtectControlGroups`, `ProtectClock`, `ProtectHostname`,
  `ProtectProc=invisible`, `RestrictSUIDSGID`, `RestrictRealtime`,
  `RestrictNamespaces`, `LockPersonality`, empty
  `CapabilityBoundingSet` + `AmbientCapabilities`,
  `SystemCallArchitectures=native`, `MemoryMax=2G`, `TasksMax=256`.
  `ProtectHome` intentionally omitted — Bearings reads `~/.claude`
  and writes `~/.local/share/bearings` + `~/.config/bearings`, so
  locking home would require per-path `ReadWritePaths` overrides
  that break the `%h/.local/bin/bearings` ExecStart.
- [x] **Skill/command scanner walks `~/.claude/plugins`.**
  `src/bearings/api/commands_scan.py`. Fixed 2026-04-23:
  - New `CommandsScope = Literal["all", "user", "project"]` +
    `CommandsCfg.scope` (default `"all"`, today's behavior).
  - `collect()` takes a `scope` kwarg; `"user"` skips the plugin
    walk, `"project"` skips both user and plugin walks. Route
    (`routes_commands.py`) reads
    `request.app.state.settings.commands.scope` and passes it
    through.
  - `tests/test_commands_scan.py` +3 tests (scope=all default,
    scope=user skips plugins, scope=project skips user+plugins).
  - Profile presets: `safe` will set `scope = "project"`,
    `workstation` will set `scope = "user"`, `power-user` leaves
    `scope = "all"`.
- [x] **`cfg.server.host=0.0.0.0` no interlock when auth=off.**
  `src/bearings/cli.py`. Fixed 2026-04-23:
  - New `_check_bind_auth_interlock(cfg)` helper + `_LOOPBACK_BINDS`
    frozenset (`127.0.0.1`, `localhost`, `::1`, `::ffff:127.0.0.1`).
  - `serve` subcommand runs the check before `uvicorn.run(...)` and
    returns exit code 2 with a stderr explanation when the operator
    bound a non-loopback host without configuring `auth.enabled +
    auth.token`. Reverse-proxy scenarios stay supported (auth on +
    host=0.0.0.0 → allowed).
  - `tests/test_config.py` +6 interlock tests covering loopback
    pass-through, wildcard/LAN refusal, auth-on pass-through, and
    the `auth.enabled=true + token=None` config-error edge.
- [x] **No global `max_budget_usd` default.** Fixed 2026-04-23:
  - New `AgentCfg.default_max_budget_usd: float | None = None`.
    Default `None` keeps today's uncapped behavior; profiles override
    (`safe` will set a small ceiling).
  - Both session-create call sites apply the default when the
    caller didn't specify: `routes_sessions.py` POST `/api/sessions`
    and `routes_checklists.py` POST paired-chat spawn. Per-session
    explicit overrides still win.
  - `tests/test_routes_sessions.py` +1 test confirms the config
    default lands on new session rows and that an explicit body
    value overrides it. `tests/test_config.py` +2 config tests
    (default-None, config-file-positive-float).

### Cleanup (low priority)

All six items shipped 2026-04-24 in the audit-cleanup pass:

- [x] `LIKE` query unescaped wildcard DOS — `search_messages` now
  escapes `%`, `_`, `\` and uses `LIKE ? ESCAPE '\\'`. Test:
  `test_search_escapes_like_wildcards`.
- [x] `permission_mode` SQL CHECK — schema.sql gets the inline CHECK,
  migration 0030 adds equivalent BEFORE INSERT/UPDATE triggers for
  already-migrated DBs (SQLite can't ALTER an existing column to add
  CHECK). Test: `test_permission_mode_check_constraint_blocks_invalid_writes`.
- [x] WS subscriber queues bounded — `SUBSCRIBER_QUEUE_MAX = RING_MAX`
  caps each subscriber's queue. A stalled subscriber is evicted on
  overflow; healthy subscribers keep flowing. Test:
  `test_stalled_subscriber_evicted_when_queue_fills`.
- [x] `import_session` validation — 16 MB raw-body cap (413), shape
  validation on `session`/`messages`/`tool_calls`, per-list size caps,
  and the existing `ensure_default_severity` call preserves the
  "every session has ≥1 tag" invariant. Tests:
  `test_import_rejects_non_object_root`, `…_non_list_messages`,
  `…_non_object_message_entries`, `…_oversized_body`.
- [x] `commands_scan` symlink follow — rewritten to a manual stack walk
  that skips symlinked files and dirs; the skills walker and the
  marketplaces walker do the same. Tests:
  `test_collect_skips_symlinked_command_files`,
  `…_command_subdirs`, `…_skill_dirs`.
- [x] Silent `except Exception` swallows — narrowed in `agent/session.py`
  (`ClaudeSDKError` / `OSError` / `AttributeError` for SDK calls,
  `aiosqlite.Error` for DB reads, `(TypeError, ValueError)` for
  parsing), `agent/runner.py` (`ClaudeSDKError` for SDK interrupts,
  `aiosqlite.Error` for DB writes), and `api/routes_tags.py`
  (`sqlite3.IntegrityError` / `aiosqlite.IntegrityError` for the
  UNIQUE-name handler).

### v0.3+ — OS-level sandbox (DEFERRED, do not surface in "what's next")

**Do not surface this entry when Dave asks "what's next" until the
ship-blockers and toggle layer above have shipped.** This is intentionally
parked for v0.3+ planning, after v0.2 closes.

Once the toggle layer exists, add an opt-in `--sandbox=bwrap` mode that
wraps each session in bubblewrap with a single bind-mounted project dir
(the configured `working_dir`), no `$HOME`, no `~/.claude/`, no `~/.ssh`,
no `/run/user/<uid>/keyring`. Flag "experimental" until proven.

Why deferred:

- `claude-agent-sdk` doesn't expose a clean wrapping point for the CLI
  subprocess. Path is "swap the executable for a `bwrap`-wrapping shim"
  or fork the SDK. Both are real engineering, not a config knob.
- Fights the `power-user` profile by design — Dave wants `$HOME` reach.
  Means a sandbox toggle on top of the profile system.
- Toggle layer + `safe` profile already covers ~80% of the realistic
  threat model for a stranger downloading the app. Sandbox is the
  remaining 20% (defense vs. a jailbroken agent actively trying to
  escape).

When v0.3 planning starts, revisit this entry. Until then: silence.

## Per-session input ergonomics (deferred from 2026-04-22)

Original ask (paraphrased from the prompt lost in the 2026-04-22 mid-turn
incident — see v0.6.1 / `tests/test_runner_replay.py`):

> When I leave a session and come back to it any text I typed and
> didn't enter is gone. I'd also like each session to be able to
> press up or down on the keyboard to navigate input history.

Two discrete UI features, same input surface:

- [ ] **Draft persistence.** Unsent text in a session's composer should
  survive a page reload / tab switch / reconnect. Per-session key (not
  global), cleared on submit. Candidates: `localStorage` keyed by
  `session_id` (lives across reloads, dies on history clear), or
  `sessionStorage` (dies on tab close — weaker but simpler). Probably
  `localStorage` with a small size cap and a TTL so abandoned drafts
  don't accumulate forever.
- [ ] **Arrow-key history navigation.** `↑` / `↓` in the composer walks
  the caller's prior `user` messages for *this session*, newest-first
  on first `↑`. `Esc` or typing past the end restores the in-progress
  draft (don't clobber the user's typing). Scope: per-session only
  (don't leak prompts across sessions). Load from `list_messages(session_id)`
  filtered to role='user', or cache in the store on first use.

Treat as a single small PR (both live in the Conversation composer).
Research + plan before implementing — this is the explicit follow-up
to the 2026-04-22 research session that got eaten by the turn-loss
bug now fixed in v0.6.1.

## Live session list — Phase 2 follow-ups

Phase 2 (`/ws/sessions` broadcast) shipped in v0.7.0 — see CHANGELOG.
Two follow-ups remain (poll stays until the broadcast has earned trust
via metrics / uptime):

- [ ] Drop the `softRefresh` call from `startRunningPoll` once the
  broadcast has a few weeks of clean data. `sessions.softRefresh`
  itself stays — it's the reconnect reconciliation path.
- [ ] Drop the `running`-set poll once the broadcast's `runner_state`
  frames have earned the same trust. Requires a reconnect-time
  snapshot of currently-running sessions (the WS currently has no
  replay buffer; either a short `/api/sessions/running` tick on
  connect or a `runner_state_snapshot` frame would work).

## Drag-and-drop file uploads — follow-ups

Initial slice shipped 2026-04-22 (`POST /api/uploads` + drop handler in
`Conversation.svelte`). Config: `[uploads] upload_dir`,
`max_size_mb` (default 25), `blocked_extensions` (default executables).
Remaining:

- [ ] **GC for upload dir.** Time-based sweep of `upload_dir` — e.g.
  delete files older than `uploads.retention_days` (default 30) on
  server start and on a daily timer. Currently the directory grows
  unbounded; low-priority because uploads are small and localhost
  disk is cheap, but it'll accumulate over years of use. Consider
  tying cleanup to session deletion instead (per-session upload
  subdirs) if the attachment-chip work lands first.
- [ ] **Attachment chip above user bubble.** Render a small chip
  (filename + size + click-to-preview-or-open) above the user's
  message when the prompt contains one of our upload paths. Requires
  either persisting the upload metadata alongside the message OR
  teaching the turn renderer to detect `upload_dir`-prefixed paths
  in content and look them up. The `UploadOut` model already carries
  `filename` / `size_bytes` / `mime_type` for this shape; need a way
  to persist them per-turn.
- [ ] **Progress UI for large uploads.** Current fallback fires with
  a static "Uploading dropped file…" overlay; a 25 MB PDF on a slow
  bus is a noticeable pause. Options: XHR with `upload.onprogress`
  (gives real byte-count feedback) or a Fetch-based streaming POST
  with a `ReadableStream` tee. Cheap wins first — a dots-animation
  is probably enough for typical drops.
- [ ] **Batch POST for multi-file drops.** Today each file is a
  separate round-trip. For 10+ small files on a slow link this
  adds up. Not urgent — typical drop is 1-3 files.
- [ ] **Live smoke test on Kubuntu + Hyprland + Chrome.** Tests and
  typecheck are green; the in-browser drop test happens after the
  next server restart (restart would kick the live Bearings session
  — defer until Dave picks his moment).

## Severity backfill — remaining Low-defaulted sessions (2026-04-22)

Context: the first severity-classification pass on 2026-04-22 15:14
reclassified 76 sessions by examining content. Since then ~106 new
sessions landed; 33 of them currently still carry the default `Low`
severity tag auto-attached by `ensure_default_severity` on create.
Most look like paired-chat / checklist-item sessions with bracketed
titles (`[I5]`, `[DN10]`, `[S10]`, etc.) where the severity
reflects the item's real priority and Dave is the only judge of
which ones are actually Low vs higher.

- [ ] Review the 33 post-first-pass Low-tagged sessions and decide
  which deserve escalation. Query to enumerate:
  ```sql
  SELECT s.id, s.title, s.created_at FROM sessions s
  JOIN session_tags st ON st.session_id = s.id
  JOIN tags t ON t.id = st.tag_id
  WHERE t.name = 'Low' AND t.tag_group = 'severity'
    AND s.created_at > '2026-04-22 15:14'
  ORDER BY s.created_at;
  ```
  Current distribution (2026-04-22 evening): Blocker=17,
  Critical=36, Medium=64, Low=40, QoL=25 (total 182). The sidebar
  severity filter + color picker shipped in v0.7.2/v0.7.3 make
  this a click-through pass rather than a SQL exercise. No
  automated classification attempted: title signals (e.g.
  "security audit: cleanup (low priority)") are usually
  trustworthy but project-scoped bracketed items need Dave's
  judgment on their actual priority.

## Live TodoWrite widget (deferred from 2026-04-22)

Initial spike landed 2026-04-22 — `TodoWriteUpdate` WS event, sticky
`LiveTodos.svelte` widget above the turn stream, `GET /sessions/{id}/todos`
for first-paint. Derived from the latest `tool_calls` row where
`name='TodoWrite'`, no schema migration.

**Design record (what we decided and why):**
- SDK has no TodoWrite-aware event; the tool arrives as a regular
  `ToolUseBlock(name="TodoWrite", input={todos:[...]})`. Input is a
  full replacement of the list every call — positional identity, no
  item ids. Status enum: `pending | in_progress | completed`.
- State model is **derive on the fly** from `tool_calls`. No session
  column; `sessions.latest_todos_json` was considered and rejected
  because the sub-millisecond MAX(started_at) query already exists.
- Rendering surface is **sticky at the top of the Conversation pane**
  (option b from the scouting report), not inline per-turn (would
  render 40+ stale widgets on a chatty session) and not a new
  Inspector tab (demotes operational progress to audit/debug land).
- **Does NOT reuse the existing `checklists` / `checklist_items`
  subsystem.** Those are a separate session kind (`kind='checklist'`,
  PK'd by `session_id`) — fighting that invariant to shoehorn an
  in-chat progress list would blur two UX concepts. Keep the
  TodoWrite view purely over `tool_calls`.

**Follow-ups left on the table:**

- [ ] **Auto-collapse policy.** Current widget always shows when the
  session has any todos. Candidate rule: collapse ~30s after the
  latest update lands and every item is `completed`. Flicker risk if
  the agent emits a fresh "pending" item immediately after; build and
  tune against a real multi-turn session before committing.
- [ ] **Historical navigation.** Every TodoWrite payload is still in
  `tool_calls` (not just the latest). A "step back through todo
  states" affordance would let Dave see the progression. Not v1 — no
  evidence the audit trail is useful in-band; the Inspector's raw
  tool-call list already covers debug cases.
- [ ] **Push unchecked items to working-dir TODO.md on session close.**
  Dave greenlit this 2026-04-22 ("yes") — promoted from deferred to
  an active follow-up, though still blocked on resolving the "Nearest
  TODO.md" ambiguity flagged in the research-agent action-row entry
  above. Manual "Send these to TODO.md" button on the widget is the
  right shape; auto-dump is not. Concrete next step: once the
  action-row nearest-TODO.md picker lands, reuse the same resolver
  here and add a "Push N unchecked to {path}" affordance on the
  LiveTodos card header (visible only when at least one pending or
  in_progress item is present).
- [ ] **Widget placement interaction with ContextMeter/TokenMeter.**
  First-pass lives above the turn stream; if the conversation header
  gets more sticky elements, a dedicated "status strip" region should
  be refactored out. Defer until a second sticky row shows up.
- [ ] **Hide widget when `todos` is an empty list.** Spike treats empty
  array as "render with 0 items" for simplicity; v2 should treat it
  as "no active todo session, hide the card entirely."
- [x] **Dave's adoption question — ANSWERED 2026-04-22: yes, adopt.**
  Dave greenlit using TodoWrite as part of his workflow going forward
  once the widget shipped in v0.8.0 and eyeballed clean against the
  Checklists session. This means the deferred follow-ups above are
  no longer "waiting for someone to care" — they're now gated on
  real usage surfacing the pain points (auto-collapse timing,
  widget-placement conflicts with future sticky rows, empty-list
  hide-vs-show). Re-evaluate each when the agent has run a handful
  of real TodoWrite turns in Dave's normal workflow.

## Agent-authored artifacts — Phase 1 shipped, Phases 2–4 open — 2026-04-24

**Phase 1 shipped.** Outbound file-display surface: the agent writes a
file, `POST /api/sessions/{sid}/artifacts` registers the path, and
`GET /api/artifacts/{id}` streams it back with inline
`Content-Disposition` so the existing markdown `<img>` allowlist
renders it in the conversation view. Migration 0028 adds the
`artifacts` table (id, session_id, path, filename, mime_type,
size_bytes, sha256, created_at). Config: `[artifacts] artifacts_dir`
(default `$XDG_DATA_HOME/bearings/artifacts`), `serve_roots` (default
artifacts_dir + uploads_dir), `max_register_size_mb` (default 100).
18 tests in `tests/test_routes_artifacts.py` cover happy path,
path-allowlist, cross-session isolation, serve-time revocation, and
MIME detection overrides for svg/markdown.

**Phase 2 — PDF + HTML preview.**

- [ ] **FilePreview Svelte component.** MIME-keyed dispatch — image
  goes straight to `<img>`, text/json/csv to a shiki code block, PDF
  to `pdfjs-dist`, html to a sandboxed `<iframe src="/api/artifacts/{id}"
  sandbox>`. Component owns the loading + error states so every
  embedder gets consistent UX. Lives alongside the existing message
  renderer; the markdown pass emits a stub `<artifact-preview>` tag
  that the Svelte layer upgrades post-sanitize.
- [ ] **Add `pdfjs-dist` to frontend deps.** Canvas-based inline
  viewer; budget ~400 KB gzipped lazy-loaded chunk. Render a single
  first page by default with a "next page" affordance; full-document
  scroll is overkill for agent-generated one-pagers.
- [ ] **Sandboxed HTML preview.** Use `<iframe src="/api/artifacts/{id}"
  sandbox="allow-scripts">` — no allow-same-origin, no allow-top-
  navigation. Consider a strict CSP header served with `text/html`
  artifacts. The agent can already produce an HTML file via Write; no
  new install needed for this slice.
- [ ] **Text / markdown / JSON / CSV.** Fetch the artifact, render via
  the existing `renderMarkdown()` for `text/markdown`, shiki for
  code, a table component for CSV. No new deps — everything's already
  in the bundle for chat rendering.

**Phase 3 — DOCX + XLSX + PPTX.**

- [ ] **Add `python-docx`, `openpyxl`, `python-pptx`** to
  `pyproject.toml`. Server-side preview endpoint
  `GET /api/artifacts/{id}/preview` returns HTML rendered from the
  Office format; result is cached per artifact id (bytes don't
  change — sha256 is stable). Frontend `FilePreview` routes these
  MIMEs to the rendered HTML viewer.
- [ ] **Download-original path.** `?download=1` already flips the
  disposition; the original DOCX/XLSX download works today, only
  inline preview needs the conversion step.

**Phase 4 — Authoring tools.**

- [ ] **Add Pillow + matplotlib + reportlab** to a dev-time
  installable extra so the agent can generate raster images + PDFs
  without a separate `pip install`. Keep `weasyprint` out of the
  default set — it pulls large C deps (cairo, pango). Agent can
  `uv add --script` for one-off needs.
- [ ] **Convenience tool for "generate + register" as one step.**
  Today Claude does `Write` then `curl POST /api/sessions/.../artifacts`;
  a helper MCP tool / CLI subcommand (`bearings artifact register
  <path>`) would make it one call. Low priority — curl works and is
  traceable in the transcript.

**Unblocked upstream by Phase 1:**

- Attachment-chip UI (see § "Drag-and-drop file uploads — follow-ups"
  above) now has a backing store. To light up the inbound-chip path,
  extend `routes_uploads.upload_file` to also `store.create_artifact`
  for the uploaded bytes and persist the resulting `artifact_id` on
  the message row. Shared GC sweep can then walk the `artifacts`
  table's `created_at` column instead of scanning the upload dir by
  mtime.
