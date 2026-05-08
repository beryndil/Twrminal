# V1 Feature Audit — Ship-Blocker Findings Register

**Status:** REQUIRED BEFORE v1 SHIP.
**Audit date:** 2026-05-07.
**Method:** Fourteen-session feature-by-feature audit. Each feature in the
v1.0.0 release got a dedicated session; an executor read the relevant code,
behavior docs, and tests; findings were posted back to orchestrator session
`e997026e97154b8882e91c4b90d66aa0`.
**Surface reviewed:** the entire v1.0.0 release surface as listed in
`README.md` Highlights and `CHANGELOG.md` §1.0.0 + §0.18.0 + §[Unreleased].

---

## Executive summary

- **14 features audited; 3 formally closed, 11 with findings awaiting close.**
- **~80 distinct findings.** One is shipped-but-inverted (the Stop-undo
  inversion in #2). One is shipped-but-dead-suspected (memories→model
  injection in #7). One is whole-modules-claimed-shipped-but-absent
  (`bearings_dir/`, `cli/gc.py`, MCP tools in #10).
- **Eleven distinct defect classes** found, ranging from "spec-only / correctly
  framed" to "feature inverted." See [§Defect typology](#defect-typology).
- **Visibility-or-test-density rule** validated across all 14 audits: clean
  audits required either high human visibility OR high test density. Surfaces
  with neither (Memories, parts of Conversation streaming, missing
  `bearings_dir/`) produced every catastrophic finding.
- **The dogfood window exercised wire shapes thoroughly and behavior fidelity
  not at all.** Daily probe + differential probe + cutover-smoke verify
  endpoints respond and shapes match — none verify documented behavior fires
  end-to-end.

**Five cross-cutting work-streams emerged from the typology** — see
[§Cross-cutting work-streams](#cross-cutting-work-streams).

---

## Status table

| #  | Feature                                  | Status   | Session id                         |
|----|------------------------------------------|----------|------------------------------------|
| 1  | Session lifecycle                        | **CLOSED** (closer `8faed0b36c6b4f40a804735813056d28` · 2026-05-08) | `48f51dbdc7614587b1ad0ffea1aa8f7d` |
| 2  | Conversation & streaming                 | **CLOSED** (closer `5081bf4b6b4a4a48826e229b2f33ed24` · 2026-05-08) | `000bacc2d1894485bb4daef730f759eb` |
| 3  | Routing v1                               | **CLOSED** (closer `1fe8c517388a46d0bc87357ec5dcce2b` · 2026-05-08) | `6be4502a55cb43a4ad71eeaa92b8f79f` |
| 4  | Inspector (5-tab + context meter)        | **CLOSED** (commit `bf1d7df`) · re-verified 2026-05-08 (verifier `0cbd67a3`, 0 regressions) | `c2c372f04df64cf090ab4f230cb8a324` |
| 5  | Tags & sidebar                           | **CLOSED** (closer `a84c54273c13416a893b24dec5e3e8b8` · 2026-05-08) | `60ee46d9f2284bb88093f13fbaaa68cd` |
| 6  | Checklists, paired chats, auto-driver    | **CLOSED** (closer `7bd7658d1dd84456b6471628bf04b1e2` · 2026-05-08) | `b0f4e9f9ba554a09821f3f3183ccbb3c` |
| 7  | Vault & memories                         | **CLOSED** (closer `196d05814b1b485b9c69e9e0ef55f39a` · 2026-05-08) | `9e6f171e143542ecb8f45fbdb4864d69` |
| 8  | Preferences & settings                   | **CLOSED** (closer `1f64ed633805476b92210698bc092d9e` · 2026-05-08) | `49d639582f05465eaf1e3f84500b19a3` |
| 9  | Themes, keybindings, context menus       | **CLOSED** (closer `1d50c972b48849749b3021ef92210b8a` · 2026-05-08) | `45c0a427aea04e6d91ef11b10eb971bb` |
| 10 | Filesystem, uploads, shell, MCP          | **CLOSED** (closer `deae2e1e526c443da0b098e9d2771332` · 2026-05-08) | `e7525f366f864bdd83d49e888a29549e` |
| 11 | Reliability & dogfood                    | **CLOSED** (closer c8ec881d · 2026-05-08) | `cb4ae047ef7c4a9ea767b00afbb1e550` |
| 12 | Quality gate stack                       | **CLOSED** (closer `d3a0fc02a9e64f359aeb7bc5cfb4e18f` · 2026-05-08) | `c649e6b658634b828a5dfdde555d1e3c` |
| 13 | SemVer commitment (v1.0.0)               | **CLOSED** (closer `c6e2a79063a34e21a2fe8b01ee081ef9` · 2026-05-08) | `f4b0b90360b1437abbee9cc9f10c813c` |
| 14 | Analytics v1 (PLANNED)                   | **CLOSED** (closer `7cae7bcf40d0484b8040b98966999f55` · 2026-05-08) | `47c9b0886bf24d3c8d87fb55d2fcf2e9` |

INTERIM means: findings reported in the session's transcript, no formal
CLOSED report posted yet. The orchestrator session holds full closeout reports
for #4, #13, #14 in its description; the rest are in this document.

---

## Per-feature findings

### 1. Session lifecycle (INTERIM)

End-to-end complete. Four bounded fixes.

1. **RACE CONDITION — bulk-close broadcast** (`sessions_bulk.py:333-340`).
   After bulk tx commits, code re-fetches rows to build broadcast. Concurrent
   delete in that window → `row=None` → close not broadcast to other tabs.
   Fix: capture rows inside the tx before commit, or use data returned by
   `_bulk_close()` directly.
2. **TAG CARDINALITY NOT ENFORCED AT PATCH** (`sessions.py:~509`).
   `_validate_tag_cardinality()` runs at create but not at
   `PATCH /api/sessions/{id}`. Incremental single-attach edits can land a
   session in a 2-project-tag state. Add same validation call in patch path.
   **Same bug independently surfaced by audit #5** — high confidence.
3. **BULK EXPORT NULL FILTERING MISSING IN FRONTEND**
   (`sessionsBulk.ts:148-150`). Behavior doc says callers filter nulls before
   triggering download. TS client returns `resp.blob()` raw. Either filter
   client-side or move to server and update doc.
4. **CHECKLIST SESSIONS CAN BE CLOSED** (`sessions.py:537-551`). No kind
   guard on `POST /api/sessions/{id}/close`. Results in
   `kind=checklist + closed_at IS NOT NULL`. Prompt endpoint rejects 409
   anyway so nothing breaks, but it is a reachable inconsistent state.

### 2. Conversation & streaming (INTERIM)

Mixed shipment. Five sev-1 findings.

**Sev-1 — missing / broken:**

1. **Copy-text on linkified spans.** `linkify.ts` renders plain `<a href>`
   with no clipboard intercept. Copying a workspace-relative link gives the
   expanded `file:///` href, not the visible text. Spec
   (`tool-output-streaming.md` §Clickable file paths): copy copies visible
   text, not href.
2. **ANSI passthrough.** DOMPurify strips ANSI escapes. Spec says they pass
   through and render as colored text. Bash tool output loses all color.
   No ANSI-to-color renderer wired anywhere.
3. **Soft-cap expander missing.** `runner.py` only implements hard-cap
   truncation marker. Spec (`tool-output-streaming.md` §Very-long-output
   truncation rules) requires two tiers: soft cap folds middle into inline
   *Show full output* expander; hard cap truncates at end. Soft tier absent.
4. **`[stopped]` annotation missing.** When turn stopped, partial assistant
   bubble should gain `[stopped]` annotation. Nothing in backend or frontend
   adds it. Spec: `chat.md` §Stopping or interrupting a turn.
5. **Stop undo semantics inverted.** `StopUndoInline.svelte` implements a
   pre-stop cancel (Undo prevents the stop POST). Spec says: stop fires, then
   Undo re-issues the same prompt. Opposite behavior. **Distinct defect
   class — feature inverted.**

**Sev-2 — ambiguous / incomplete:**

6. **`ToolProgress` event dead code.** `events.py` defines it, nothing emits
   it. Elapsed timer in `ToolOutput.svelte` advances only from client
   `setInterval`. Backgrounded-tab keepalive path non-functional.
7. **Elapsed timer inflates on long-disconnect replay.** Server-reported
   timestamp path for in-flight tools absent. Keepalive heartbeats carry no
   `tool_call_id` and are not ring-buffered.
8. **Tool-work drawer always starts open** (`<details open>`). Spec implies
   user can collapse during streaming; that scenario is currently impossible.
9. **`BearingsSessionStore` adapter.** `sdk_loop.py` references it in a
   comment for history replay; import/implementation unconfirmed. **Suspected
   "module exists, unwired" — needs grep verification.**

**Confirmed solid:** scroll anchor, pagination, WS reconnect/replay,
heartbeat keepalive, ApprovalModal, AskUserQuestionModal, linkifier (except
copy-text), sessions-broadcast WS, /advisor slash-command, composer
draft+history+auto-grow.

### 3. Routing v1 (INTERIM)

Most-tested feature in the build (24 routing unit tests + 16 quota guard
tests). Three real defects, four minor quality issues, two spec errata.

**Real defects:**

1. **`evaluate()` takes `quota_snapshot` redundantly.** `evaluate()` accepts
   it only to populate `quota_state_at_decision`, which `apply_quota_guard()`
   also overwrites. Every caller passes the same snapshot to both functions.
   Fix: `evaluate()` returns `quota_state_at_decision={}`,
   `apply_quota_guard()` is the sole owner of that field.
2. **`OverrideAggregator.compute()` Pass 2 — origin CTE missing window
   filter.** The CTE finds earliest rule-fired messages per session with no
   time predicate. Works today because override happens at session-creation,
   but any scenario where a manual message appears inside the window for an
   out-of-window session would inflate the numerator silently.
   **Coupled-invariant cross-cut to #1 — regression risk on any future
   session-lifecycle change.** Fix: add
   `AND CAST(strftime('%s', created_at) AS INTEGER) >= ?` to the origin CTE
   inner subquery.
3. **`_db()` and `_quota_poller()` duplicated across three route files**
   (`routes/routing.py`, `routes/quota.py`, `routes/usage.py`). A
   `routes/_deps.py` module fixes this.

**Minor quality issues:**

4. `list_for_tags()` is N+1 — one SELECT per tag; could batch with `IN(...)`.
5. `create_tag_rule` catches all `IntegrityError` as 404 — a future UNIQUE
   constraint violation would surface as misleading "tag not found."
6. Phantom validation objects — `RoutingRule(id=0, ...)` constructed and
   discarded for validation; calling `_validate_rule_fields()` directly is
   cleaner.
7. `quota_state_dict()` uses `or 0.0` — technically correct but
   `x if x is not None else 0.0` better expresses intent.

**Spec errata** (defects in the spec itself, not the code):

- `advisor_disabled_reason` appears in spec §4 body text but is absent from
  the frozen Appendix A `RoutingDecision` shape. Code correctly follows
  Appendix A.
- No system-rule reorder endpoint in the spec. Frontend works around with N
  per-rule PATCH calls (confirmed in Svelte component comment). Works but is
  a spec gap.

### 4. Inspector — **CLOSED** (commit `bf1d7df`)

Audit confirmed all spec requirements met (5 tabs, context meter, all data
wired). Closed inline-fixed: added the documented `evaluated_rules` chain to
the Routing tab.

**Decisions:** evaluated_rules: `list[int]` (ordered rule IDs tested, up to
and including the matched rule). Skipped rules rendered muted; matched rule
highlighted in success color.

**Changes (committed `bf1d7df`):**

- `schema.sql`: `evaluated_rules TEXT DEFAULT '[]'` column on `messages`.
- `db/connection.py`: `_ADDED_COLUMNS` migration entry.
- `db/messages.py`: field, `insert_assistant` param, SELECT, row mapper,
  `import_messages`.
- `agent/persistence.py`: pass `decision.evaluated_rules` through.
- `web/models/messages.py`: `MessageOut.evaluated_rules: list[int]`.
- `web/routes/messages.py`: `_to_out()` mapping.
- `frontend/api/messages.ts`: `evaluated_rules: number[]` on `MessageOut`.
- `frontend/config.ts`: `routingTimelineEvalChainLabel` string.
- `InspectorRouting.svelte`: eval chain rendered in *Why this model?*
  expandable.
- 10 test files updated (Python + frontend fixtures).

**Open:** none — feature is ship-clean.

### 5. Tags & sidebar (CLOSED)

Fourteen findings split likely-bugs / silent-correctness / design / hardening
/ UX.

**Likely bugs:**

1. **`PATCH /api/sessions/{id}` with `tag_ids` skips
   `_validate_tag_cardinality`.** POST validates; PATCH does not. Bulk-replace
   via PATCH can permanently land a 2-project state. **Same bug as #1 finding
   2 — independently surfaced by two reviewers.**
2. **`%` and `_` in search input unescaped before LIKE.** `100%` matches
   anything starting with `100`.

**Silent correctness:**

3. **`PUT/DELETE /api/sessions/{sid}/tags/{tid}` does not call
   `publish_upsert`.** Tag-only mutations invisible to other tabs. WS stream
   shows nothing.
4. **Tag CRUD also does not broadcast** (`POST/PATCH/DELETE /api/tags`,
   sort-order). Filter panels in other tabs go stale.
5. **Single-attach cardinality hole.** User can permanently hold 2 project
   tags with no schema guard and no path that forces correction.

**Design concerns:**

6. `tag_ids_other` wire param vs `class=general` in DB — rename to
   `tag_ids_general` before param ossifies.
7. History search does not hit tags — a session tagged "Bearings v1" won't
   surface when you type "Bearings v1" unless it's also in title/description.
8. No FTS5 — bare LIKE on `messages.content` is a full-table scan on every
   keystroke.
9. **`_is_known_model` duplicated in `db/tags.py` and `db/templates.py`.** A
   `db/_validators.py` module solves without cross-import cycle.

**Hardening:**

10. `SessionsBroadcaster._fan_out` iterates the live set — no `await` mid-loop
    keeps it safe now but one future reentrant caller breaks it. Snapshot with
    `list()`.
11. Subscriber queues unbounded — a hung tab OOMs the server eventually.
12. `set_for_session` and `update_sort_orders` rely on implicit transaction
    isolation, not explicit BEGIN/COMMIT via aiosqlite context manager.

**UX/accessibility:**

13. SidebarSearch: no aria-live region, no nav hint footer, no timestamps or
    tag chips in results, no cap indicator.
14. `tag.color` populated in DB and wire shape but unused in `SessionRow`
    chip rendering.

### 6. Checklists, paired chats, auto-driver (INTERIM)

Architecture solid. Three focal areas need work.

**Critical — logic broken:**

- **Blocking followups don't recurse** (`auto_driver.py:501-507`). Child item
  is created but driver continues parent immediately. Spec: pause parent,
  drive child to terminal, resume parent.
- **Checklist auto-close cascade missing**
  (`routes/checklists.py:278-287`). Marking item checked does not (a) close
  its paired chat, (b) walk parent chain to check all siblings done,
  (c) close checklist session when all root items complete.
- **Chat deletion does not clear item pointer.** Deleting a paired chat
  leaves `chat_session_id` pointing to a dead row; item renders broken link.

**High — missing feature:**

- **Spawn-from-reply UI never wired.** Backend route
  (`routes/spawn_from_reply.py`) complete, but `+ SPAWN` action pill does
  not exist anywhere in frontend conversation pane. Zero frontend references.
  **Distinct defect class — backend-ahead-of-frontend.**
- **`visit_existing` + closed-chat unchecked** (`auto_driver.py:285-291`).
  Driver checks `chat_session_id` is set but not that the session is still
  open. Closed paired chat = hard failure instead of skip.

**Medium — edge cases / validation:**

- Followup label not validated; empty/whitespace labels create invalid items.
- No recovery if leg session vanishes mid-run; driver halts cryptically.
- Sidebar does not push leg-cutover events; users do not see fast-cycling
  rows without manual refresh.

**Stale docs:**

- `TODO.md` has two dead entries claiming `PairedChatIndicator` is unmounted
  and `ChecklistChat` was deleted — both are in place.

### 7. Vault & memories (INTERIM)

Two P0s. **One is the worst finding of the entire sweep.**

**P0 — fix before shipping:**

1. **Memories empty state fires on chip filter**
   (`MemoriesIndex.svelte:119-122`). Spec says empty state only renders when
   `GET /api/memories` returns `[]`. Component checks
   `filteredRows.length === 0`, so switching chip to a tag with no memories
   fires the onboarding copy instead of nothing. Needs fix + test.
2. **Memories not wired into system prompt** (`agent/system_prompt.py`).
   Assembler only handles session instructions + extras — no code reads
   `tag_memories` or injects them per turn. **The full CRUD surface exists
   but memories may never reach the model.** Worker/session-bootstrap path
   needs audit; if genuinely missing, this is the **shipped-but-dead** class
   and the headline ship-blocker. **Verify-or-fix takes priority over P0
   #1.**

**P1 — pre-release:**

3. **Vault cfg fallback is silent** (`routes/vault.py:73-87`). If
   `app.state.vault_cfg` is not set, silently constructs default `VaultCfg()`
   instead of 503-ing. Inconsistent with every other subsystem (tags, DB)
   which fail fast. Should assert in `create_app` or remove fallback.
4. **Frontend test coverage thin.** Vault tests miss redaction toggle, search
   debounce, drag-paste-into-composer. Memories tests miss chip-filter-empty
   scenario. Write alongside fix for item 1.

**P2 — nice to have:**

5. Vault per-doc line cap is silent. Global result cap sets
   `SearchResult.capped` flag; per-doc line cap (500 lines) quietly stops
   with no client signal. Inconsistent.

**What is solid:** full spec compliance everywhere else. Layer boundaries,
schema discipline (CHECK + dataclass `__post_init__` + Pydantic all agree),
route naming, error codes, path-safety all clean. Nine-file backend test
suite is thorough.

### 8. Preferences & settings (INTERIM)

Four real issues, three design observations.

**Real issues:**

1. **`KNOWN_EXECUTOR_MODELS` divergence** — backend has
   `frozenset({"sonnet","haiku","opus","opusplan"})` in `constants.py`;
   frontend list is `["sonnet","haiku","opus"]` — no `"opusplan"`. If
   `"opusplan"` lands in DB as `default_model`, the Defaults `<select>` has
   no matching `<option>`; browser silently shows first option, next user
   change overwrites the value without warning. **Distinct defect class —
   constants drift backend↔frontend.**
2. **`display_name` max-length not enforced at PATCH boundary.**
   `DISPLAY_NAME_MAX_LENGTH=120` exists in constants and is applied in
   `sync_from_system`, but `PreferencesPatch.display_name` has no validator.
   A direct PATCH with a 10k-char name stores it verbatim. Fix:
   `Annotated[str | None, Field(max_length=DISPLAY_NAME_MAX_LENGTH)] = None`.
   **Same shape as #1 finding 2 / #5 finding 1 — POST↔PATCH validator
   drift.**
3. **`notify_on_complete: bool | None = None` is too permissive.** Column is
   NOT NULL DEFAULT 0. Sending `{"notify_on_complete": null}` is silently
   eaten by the `is not None` guard. Should be `bool = False` — Pydantic v2
   `model_fields_set` still captures explicitly-set fields even when value
   equals default.
4. **No test suite for the four base fields** (theme, default_model,
   default_permission_mode, default_working_dir).
   `test_preferences_avatar_api.py` and `test_preferences_notify_api.py`
   exist. Nothing covers: correct defaults on GET, PATCH updates, null clears
   a nullable field, omit leaves unchanged.

**Design observations:**

- DB theme column is write-only from the UI. Defaults section writes it on
  change; boot path initializes from localStorage only (`themeStore`).
  `refreshPreferences()` on layout mount only populates
  displayName/avatarUrl/cacheBust — not theme. DB value is future-proofing
  but currently dead for hydration.
- `RoutingRulesSection` has inline string literals for heading and lede —
  every other section uses `config.ts` string tables. Low stakes but
  inconsistent.
- Theme in Appearance (`ThemePicker`) writes localStorage only; Defaults
  writes localStorage + DB. Asymmetry is intentional per spec but means
  Appearance changes don't persist to DB.

### 9. Themes, keybindings, context menus (INTERIM)

Three small bugs, one doc gap, one tracked deferral. **Cleanest interim
audit in the sweep alongside #1.**

**Bugs:**

1. **`session.edit` missing from registry.** `MENU_ACTION_SESSION_EDIT` is
   defined in `config.ts`, labeled, and wired in `SessionRow.svelte` (opens
   `SessionEdit` modal), but absent from `SESSION_ACTIONS` array in
   `context-menu/registry.ts`. Menu is driven by that array — action never
   renders. Fix: add `{ id: MENU_ACTION_SESSION_EDIT, section: MENU_SECTION_EDIT }`
   above `session.rename` in `SESSION_ACTIONS`.
2. **Ctrl+K binding marked `global:true` instead of `displayOnly:true`.**
   Inline comment and behavior doc both say it is wired by the sidebar
   search component. Not a visible bug today (no global handler = no-op) but
   it is in the runtime registry map and will fire inside the composer if a
   global handler is ever registered. Fix: replace `global:true` with
   `global:false + displayOnly:true`. **Joint action item with #5 (sidebar
   search) — same Ctrl+K chord.**
3. **Context menu cheat-sheet missing Home/End.** Behavior doc lists them,
   `ContextMenu.svelte` handles them (lines 387/394), but
   `nonRegistryBindings.ts` `context_menu` section omits them.

**Doc gap:**

4. **`session.merge_into` and `session.export_json` are fully wired**
   (registry, `SESSION_ACTIONS`, handlers in `SessionRow.svelte`,
   `SessionPickerModal.svelte` for merge) but **neither appears in
   `docs/behavior/context-menus.md`**. Action IDs are public/stable — they
   need to be documented.

**Known deferred (already in TODO.md):**

5. Theme persistence is localStorage-only; behavior doc says per-account
   server-synced. Tracked as Item 2.9 theme server-sync layer.

### 10. Filesystem, uploads, shell, MCP (INTERIM)

**Most severe finding of the sweep.** Whole modules claimed shipped don't
exist. README/CHANGELOG accuracy at v1.0.0 is in question.

**Solid (correctly built):**

- `agent/uploads.py` — content-addressed store, git-object shard layout,
  idempotent store. Clean.
- `web/routes/uploads.py` — full CRUD, streaming download, dedup. Clean.
- `agent/shell.py` — argv allowlist, `shell=False`, bounded timeout,
  kill-on-timeout. Clean.
- `web/routes/shell.py` — thin dispatch, 4xx/504 mapping. Clean.
- `agent/fs.py` — realpath allow-roots with boundary check. Clean.
- `web/routes/fs.py` — list + read + pick. Clean.
- `agent/prompt_dispatch.py` — sliding-window rate limiter, full outcome
  alphabet. Clean.
- SDK stderr → journald — `sdk_loop.py:134-138`. Fine.

**Hard gaps — not built, claimed as shipped:**

1. **`bearings_dir/` package entirely absent.** Arch §1.1.6 specifies 5
   modules:
   - `contract.py`: Pydantic models for manifest/state/pending.toml schemas
   - `io.py`: atomic TOML read/write via `tempfile + os.rename`
   - `lifecycle.py`: `note_directory_context_start()`, history.jsonl append
     + cap
   - `onboarding.py`: 7-step onboarding ritual, brief composition,
     `bearings__dir_init` tool body
   - `pending.py`: pending-ops logic (backing for the web route)

   Currently `web/routes/pending.py` reads/writes `pending.toml` directly —
   no agent-layer separation.
2. **`cli/gc.py` missing.** Arch §1.1.1 explicitly places `bearings gc
   uploads` here. v0.17.x had top-level `uploads_gc.py`; arch moved it here.
   Currently just a stub comment in `cli/app.py`, never registered as a
   subparser. Needs mark-and-sweep: collect sha256s from DB → walk on-disk
   shards → delete orphans; reverse walk for DB rows with missing files.
3. **`bearings_mcp.py` incomplete.** Only has `close_session`. The live
   v0.17.x MCP (what agents use right now) has `bearings__bash`,
   `bearings__dir_init`, `bearings__get_tool_output`. None carried over to
   v1. `dir_init` body belongs in `bearings_dir/onboarding.py` per arch.
   `get_tool_output` is the large-output retrieval escape hatch. **The v1
   MCP surface advertised to agent sessions is fiction in three places.**

**Wrong — not just missing:**

4. **`web/routes/history.py` is a DB full-text search route**
   (`GET /api/history/search?q=`). Arch says `history.py` should be the
   `history.jsonl` READER for the `.bearings/` directory context. Wrong
   module, wrong implementation. The search function belongs in `search.py`
   or `sessions.py`; `history.py` is taken by the wrong thing.
   **Module-namespace collision with #5 sidebar search** — the rename has to
   land jointly.

**Reference patterns for what needs building:**

- GC: `git gc --prune` pattern — same object-store layout already used.
  Two-direction sweep: orphaned blobs + DB rows with missing files.
  Age-based TTL additive.
- TOML atomic write: `tempfile.NamedTemporaryFile + os.replace()` (POSIX
  atomic). Current `pending.py` skips this.
- `history.jsonl`: append-only, cap by line count, trim from head via atomic
  rename.

**Short list to close this feature:**

1. `src/bearings/bearings_dir/` package (5 modules: contract, io, lifecycle,
   onboarding, pending).
2. `src/bearings/cli/gc.py` + wire into `cli/app.py`.
3. `bearings_mcp.py`: add `get_tool_output` + `dir_init` + `bash` tools.
4. Rename `web/routes/history.py` → `search.py`; build real jsonl-reader
   `history.py`.

### 11. Reliability & dogfood (INTERIM)

Five gaps.

1. **[HIGH] `tests/test_daily_probe.py` is missing.** `diff_probe` and
   `cutover_smoke` both have full test suites. `daily_probe.py` has the same
   pure-function decomposition (`run_probes`, `write_log`, `render_human`,
   `_result_to_jsonl`) and zero test coverage — it runs daily and has no
   regression net.
2. **[MEDIUM] `docs/behavior/routing.md` does not exist.** Both
   `daily_probe.py` (line 33) and `cutover_smoke.py` (line 173) cross-
   reference *"docs/behavior/routing.md §Quota guard"*. That file is not in
   `docs/behavior/` (14 files, none named `routing.md`). Dangling ref will
   break lychee lint.
3. **[MEDIUM] `diff_probe.py` has no systemd service/timer.** `config/`
   only wires `daily_probe.py` to the 09:15 timer. `diff_probe` is
   manual-only — if continuous differential monitoring during dogfood was
   the intent, it needs either its own timer or an `ExecStartPost=` chain in
   the existing unit.
4. **[LOW] No retry before FAIL.** Single-shot GET with no
   `failure_threshold`. A `bearings-v1.service` restart overlapping the
   09:15 window produces a false-positive FAIL. Standard blackbox-probe
   pattern is 3 attempts × short sleep before writing FAIL.
5. **[LOW] No log retention policy.**
   `~/.local/share/bearings-v1/probes/` accumulates one file per day
   indefinitely. No `--max-age-days` flag, no logrotate entry, no cleanup
   note in the install sequence.

### 12. Quality gate stack (INTERIM)

Seven findings. The stack is partially cosmetic.

1. **[CRITICAL] Radon gate is silently broken.** `radon cc` in v6.x has no
   `--fail-on` flag (confirmed via `uv run radon cc --help`). Always exits 0
   regardless of violations. Gate is cosmetic only. Fix: replace with
   `xenon (~=0.9)`, the enforcement wrapper radon docs recommend. Entry
   becomes `uv run xenon --max-absolute B --max-modules A --max-average A
   src`. Add xenon to dev deps, replace the hook entry.
2. **[HIGH] CI mypy misses `scripts/`.** Pre-commit hook runs
   `uv run mypy src tests scripts`. CI step runs `uv run mypy src tests`.
   Explicit path args override `pyproject.toml` `files=[...]`, so CI
   genuinely skips `scripts/`. **Joint two-axis blind spot with #11 finding 1
   — `scripts/` has no test coverage and no type coverage.** Fix: add
   `scripts` to the CI mypy step.
3. **[HIGH] `ts-prune` is EOL and TS 5.x-incompatible.** Last publish
   2021-12-12, targets TS 4.x. Project pins `typescript ^5.6.0`. `ts-prune`
   uses compiler API in ways that break silently under TS 5.x — no errors,
   just missed exports. Knip already covers dead exports better. Drop
   `ts-prune`: remove pre-commit hook, npm script, knip.md entries for it.
4. **[MEDIUM] Missing `pre-commit/pre-commit-hooks` standard suite.** —
   `check-yaml`, `check-toml`, `check-json`, `end-of-file-fixer`,
   `trailing-whitespace`, `check-merge-conflict`,
   `check-added-large-files`. All run in milliseconds, catch real mistakes.
5. **[MEDIUM] Vestigial `commit-msg` in `default_install_hook_types`.**
   Declared but zero commit-msg hooks exist, no `.githooks-v1/commit-msg`
   shim. `CLAUDE.md` mandates conventional commits but nothing enforces it
   at commit time. Either add commitlint local hook or strip `commit-msg`
   from the list.
6. **[MINOR] Ruff missing `N` ruleset (pep8-naming)** — catches non-PEP-8
   naming that mypy does not see.
7. **[MINOR] `pip-audit` `always_run: true` hits network on every commit** —
   gating on `pyproject.toml` / `uv.lock` changes preserves the security
   intent with less latency.

**Priority order:** radon→xenon swap (broken today) → CI mypy path →
ts-prune removal → pre-commit-hooks suite → commitlint or remove commit-msg
stage.

### 13. SemVer commitment (v1.0.0) — **CLOSED**

**Decisions:**

- v1.0.0 stability commitment is structurally correct but mechanically
  unenforced — promise exists in docs only, nothing in CI prevents breakage.
- Committed `docs/openapi.json` is the right approach; needs drift detection
  and a breaking-change gate around it.
- `operation_id=` pinning is a hard prerequisite for the oasdiff gate to be
  signal-clean (FastAPI auto-generates from function names; renames register
  as breaking).
- Back-compat endpoints (`tag_ids` param, `GET /api/tag-groups`) should be
  marked `deprecated=True` now — first real use of the deprecation pattern,
  currently untagged.
- Behavior docs are the contractual mechanism; `[Unreleased]` features (tag
  classes, import, SDK history, preferences, permission-mode) have none —
  must be resolved before v1.1.0 ships or contract is violated on day 1 of
  second release.

**Changes:**

- CI: spec-drift check (regenerate `docs/openapi.json`, `git diff
  --exit-code`).
- CI: DB schema drift check (same pattern against `db/schema.sql`).
- CI: version alignment check (`pyproject.toml` version ==
  `docs/openapi.json` `info.version`).
- CI: `api-compat` job using `tufin/oasdiff-action` against previous semver
  tag.
- Code: pin `operation_id=` on all 133 route decorators across
  `web/routes/*.py`.
- Code: add `deprecated=True` to `tag_ids` param and `GET /api/tag-groups`
  route.
- Code: verify `RoutingDecision` / `RoutingRule` / `SystemRoutingRule` /
  `QuotaSnapshot` are `@dataclass(frozen=True)`; fix if not.
- Docs: behavior docs for all `[Unreleased]` features before v1.1.0 tag.
- Docs: add paragraph to CHANGELOG v1.0.0 stability section scoping WS
  message shapes and CLI flag surface (in or explicitly out).
- Docs: establish deprecation convention — `deprecated=True` + `x-sunset`
  extension + `Sunset` response header from middleware.
- Docs/session: update stale "62 paths / 53 schemas" (v0.18.0 baseline) →
  current **106 paths / 94 schemas / 133 operations**.

**Open:** none — scope fully bounded.

### 14. Analytics v1 (PLANNED) — **CLOSED**

**Decisions:**

- Drop `turns` table from spec — `messages` already has all per-turn token
  data (`executor_input_tokens`, `executor_output_tokens`,
  `advisor_input/output`, `cache_read_tokens`, `advisor_calls_count`).
  Attribution queries run against `messages` directly.
- Drop `bucket_snapshots` table — `quota_snapshots` already exists and is
  polled by `QuotaPoller`. Extend it with four new columns:
  `five_hour_used`, `five_hour_limit`, `weekly_used`, `weekly_limit`.
- Drop `POST /api/analytics/turns` — token data already flows into
  `messages` via existing SDK pipeline.
- Drop parallel `GET /api/analytics/attribution` and
  `GET /api/analytics/bucket/current` — extend existing
  `GET /api/usage/by_tag` and `GET /api/quota/current` instead.
- Three genuinely new tables: `plug_blocks`, `session_plug_blocks`,
  `suppressed_warnings`. Two corrections: timestamp = INTEGER unix seconds
  not ms; add `tag_id` FK to `plug_blocks` for tag_memory lineage.
- FTS5: no existing index — create fresh `plug_blocks_fts` virtual table.
- Token counting: local `tiktoken cl100k_base`, NOT Anthropic
  `count_tokens` API endpoint (which burns bucket).
- `meta:plug-draft` synthetic tag chip → `routing_source = plug_draft` on
  the `messages` row.
- Plug capture scope: only Bearings-controlled blocks (`claude_md`,
  `tag_memory`, `session_instructions`, `system_baseline`). MCP tool
  descriptions and skill descriptions are SDK-assembled — deferred to v1.x.

**Changes — implementation order:**

1. **Phase 0 (prerequisite):** Add `cache_creation_tokens INTEGER` column to
   `messages` table. Add `MODEL_USAGE_KEY_CACHE_CREATION =
   cacheCreationInputTokens` constant. Update `extract_model_usage()` in
   `persistence.py`, `insert_assistant()` in `db/messages.py`,
   `get_token_totals()` (remove hardcoded 0), `TokenTotalsOut` response
   model.
2. **Phase 1:** Add three new tables + FTS5 virtual table to `schema.sql`.
   Extend `quota_snapshots` with four count columns. Add
   `PLUG_YELLOW_THRESHOLD=500`, `PLUG_RED_THRESHOLD=1500`,
   `PLUG_REDUNDANCY_MIN_SESSIONS=3`,
   `PLUG_REDUNDANCY_LAST_N_DEFAULT=25` to `constants.py`.
3. **Phase 2:** New `agent/plug_capture.py` module. Hook into
   `POST /api/sessions` as a `background_tasks.add_task` after tag
   attachment.
4. **Phase 3:** Extend `GET /api/usage/by_tag` — add `share_total`,
   `burn_rate_per_min` fields and 5h period option. Extend
   `GET /api/quota/current` — add four raw count fields.
5. **Phase 4:** New `web/routes/analytics.py` with redundancy query
   endpoint, plug-summary endpoint, plug-block versions endpoint (unified
   diffs via `difflib`), warning suppress endpoint.
6. **Phase 5:** Frontend right-pane Analytics tab — sections A and C
   first; section B (redundancy) last.
7. **Phase 6:** Promote-to-tag-memory, promote-to-on-open,
   draft-new-session actions.

**Open:**

- Confirm whether `QuotaPoller` `raw_payload` actually contains
  `five_hour_used/limit` and `weekly_used/limit` as numeric fields vs just
  percentages — determines whether `quota_snapshots` column extension lands
  cleanly or needs a fetcher change.
- Burn rate comparison (current 30-min vs 7-day median) deferred to v1.x.
- Per-tag custom yellow/red thresholds deferred to v1.x.
- MCP/skill description blocks deferred to v1.x pending investigation of
  SDK plug assembly visibility.

---

## Defect typology

Eleven distinct classes emerged across the 14 audits. Recurrence count
in parens.

| Class | Description | Count | Examples |
|---|---|---|---|
| Spec-only | Feature is correctly framed as not yet built. | 1 | #14 Analytics |
| Module fictional | Whole package claimed shipped, doesn't exist. | 1 | #10 `bearings_dir/`, `cli/gc.py` |
| Backend-only | Backend complete, frontend never wired. | 1 | #6 spawn-from-reply UI |
| Frontend-only / spec gap | Frontend uses N PATCHes because backend lacks a bulk endpoint. | 1 | #3 system-rule reorder |
| Module exists, unwired | Modules + tests exist; integration point doesn't import. | 1 (suspected) | #2 `BearingsSessionStore` |
| Behavior partial | Orchestration code paths exist, full state-machine doesn't fire. | 5 | #5 WS broadcasts, #6 followup recursion + cascade-close, #7 memories injection, #8 theme write-only, #11 routing.md missing |
| Feature inverted | Behavior present and wrong-direction. | 1 | #2 stop-undo |
| Validator drift POST↔PATCH | Validator runs on POST, not on PATCH. | 3 | #1.2 = #5.1, #8.2 |
| Constants drift backend↔frontend | Enum set diverges across boundary. | 1 | #8 `KNOWN_EXECUTOR_MODELS` |
| Inert gates | CI step exists, doesn't enforce. | 2+ | #12 radon cosmetic, #12 mypy skips scripts/ |
| Promise unenforced | Doc says rule, no CI checks rule. | 1 | #13 SemVer mechanism |
| Spec-internal inconsistency | Spec contradicts itself; code may follow either. | 2 | #3 `advisor_disabled_reason`, #3 missing reorder endpoint |

**Reading the typology:** "Behavior partial" and "validator drift" are the
two most-recurrent classes (5 and 3 instances). Both produce silent failure
modes — feature looks like it works, doesn't fully fire. The dogfood window
cannot have caught these by design.

---

## Cross-cutting work-streams

The typology suggests five fix-pattern work-streams, each touching multiple
features. Doing them as work-streams instead of feature-by-feature is
substantially cheaper.

### CCW-1. Behavior-doc / release-notes correction pass

**Scope:** at least six surfaces have doc-vs-reality gaps.

- `routing.md` missing entirely (#11).
- Memories injection doc lies (#7 P0 #2).
- Spawn-from-reply: backend endpoint shipped, no behavior doc (#6).
- Stop-undo semantics are spec'd one way, shipped opposite (#2 sev-1 #5).
- ANSI / soft-cap / copy-text / `[stopped]` (#2 sev-1 #1–4) — four spec
  divergences inside `tool-output-streaming.md` and `chat.md` alone.
- Context-menu action IDs `session.merge_into` and `session.export_json`
  shipped, undocumented (#9 doc gap #4).
- Tag classes / import / SDK history / preferences / permission-mode
  shipped under `[Unreleased]` with no behavior docs (#13 closeout).

**Why upstream of v1.1.0:** v1.0.0 baseline accuracy is itself the
contract. Behavior docs are the SemVer-governed surface (per #13). At least
one v1.0.0-shipped flagship feature (routing) has no behavior doc; this is
already a contract violation, not a v1.1.0 risk.

### CCW-2. POST↔PATCH validator-drift grep + fix

**Scope:** every POST handler in `web/routes/` audited for missing PATCH
counterpart.

Three confirmed instances so far, two surfaced independently:

- #1.2 / #5.1: `_validate_tag_cardinality` skipped on session PATCH.
- #8.2: `DISPLAY_NAME_MAX_LENGTH` skipped on preferences PATCH.

**Pattern says more.** A grep across `web/routes/*.py` for any POST handler
calling a `_validate_*` function whose PATCH counterpart doesn't is a
30-minute audit; the fix per instance is two lines.

### CCW-3. Broadcaster-correctness work item

**Scope:** WebSocket fan-out plumbing has at least three independent gaps.

- #1 finding 1: bulk-close races concurrent delete (re-fetch after commit).
- #5 finding 3: `PUT/DELETE /api/sessions/{sid}/tags/{tid}` skips
  `publish_upsert`.
- #5 finding 4: tag CRUD (POST/PATCH/DELETE /api/tags, sort-order)
  skips broadcast.
- #5 findings 10, 11: `_fan_out` iterates live set without snapshot;
  subscriber queues unbounded.

Multi-tab UI consistency was a v1 selling point (sessions-broadcast WS
feature). Per-event fixes are treating symptoms; the real fix is a
broadcaster contract: every mutation handler MUST call publish, no skips,
test-enforced.

### CCW-4. Utility-module scaffolding

**Scope:** two missing shared modules implied by duplication.

- #5 finding 9: `_is_known_model` duplicated in `db/tags.py` and
  `db/templates.py` → needs `db/_validators.py`.
- #3 finding 3: `_db()` and `_quota_poller()` duplicated across three route
  files → needs `web/routes/_deps.py`.

Both modules are one commit each. They're dependencies of CCW-2 (the
validator-drift fixes have to land somewhere) and several finding-level fixes
across audits.

### CCW-5. Spec audit

**Scope:** the spec itself contradicts itself in at least two places (#3
spec errata).

`docs/model-routing-v1-spec.md` is the most-cited spec in the build and
itself internally inconsistent. If the contract-fidelity audit (CCW-1) lands
without the spec being internally consistent, the next round of behavior-doc
work re-introduces the same drift.

---

## Visibility-or-test-density rule

**Validated across all 14 audits with zero counterexamples.**

Clean audits required at least one of:
- **High human visibility** — operator can see when the feature breaks
  during normal use.
- **High test density** — comprehensive unit/integration test coverage at
  the layer where the feature lives.

| Audit | Visibility | Test density | Result |
|---|---|---|---|
| #4 Inspector | high | medium | clean (1 small gap, fixed inline) |
| #9 Themes/menus | high | medium | clean (3 trim bugs) |
| #1 Session lifecycle | high | high | clean (4 bounded fixes) |
| #3 Routing v1 | low (invisible when working) | high (40 unit tests) | clean (3 small defects + spec errata) |
| #2 Conversation streaming | mixed | medium | mixed (5 sev-1, semantic inversion) |
| #14 Analytics | n/a (planned) | n/a | correctly framed as spec-only |
| #13 SemVer | low | low | mechanism unenforced (5 changes needed) |
| #11 Reliability | low | partial (diff/cutover have tests; daily doesn't) | 5 gaps |
| #12 Quality gate | low | low | 7 findings, gate partly cosmetic |
| #5 Tags & sidebar | medium | partial | 14 findings, 2 high-confidence bugs |
| #6 Checklists/auto-driver | medium | partial | 3 critical, 2 high, 4 medium |
| #8 Preferences | medium | partial (avatar/notify only) | 4 issues, 3 design gaps |
| #7 Vault & memories | low (silent failure on injection) | partial | **2 P0, one shipped-but-dead-suspected** |
| #10 Filesystem/MCP | low | partial | **whole modules absent** |

**Rule for the next audit sweep (post-v1.1):** prioritize surfaces with
neither signal first. They produce every catastrophic finding.

---

## Required before v1 ships

This is the ship-blocker register. Items in **bold** are P0; everything
else is P1.

### P0 — must fix before v1 ships

1. **#7 P0 #2 — Verify or fix memories→system-prompt wiring.** If memories
   genuinely never reach the model, the feature is shipped-but-dead and
   `docs/behavior/memories.md` lies about behavior. **Highest-priority
   ship-blocker.**
2. **#10 finding 1 — Build `bearings_dir/` package** (5 modules) OR remove
   the package from the architecture doc, README, and CHANGELOG. Currently
   shipped surface advertises a package that does not exist.
3. **#10 finding 2 — Build `cli/gc.py`** OR remove `bearings gc uploads`
   from the CLI surface in CHANGELOG and `cli/app.py` plan. Same shape as #1.
4. **#10 finding 3 — Restore MCP tools** (`bearings__bash`,
   `bearings__dir_init`, `bearings__get_tool_output`) OR remove their
   advertisement from the v1 MCP surface description.
5. **#2 sev-1 finding 5 — Fix Stop-undo inversion** OR update the spec to
   match shipped behavior. Currently the user-visible action does the
   opposite of what `chat.md` describes.
6. **#13 — All ten changes from the SemVer closeout.** Without these, the
   v1.0.0 stability commitment is unenforced. Especially: pin
   `operation_id=` on 133 routes, add `deprecated=True` to back-compat
   endpoints, behavior docs for `[Unreleased]` features.
7. **#1 finding 2 / #5 finding 1 — Tag cardinality at PATCH.** Same bug from
   two angles. Permits sessions to land in a 2-project state contradicting
   CHANGELOG's tag-classes promise.
8. **#12 finding 1 — Replace radon with xenon.** The CC ≤ 10 gate as
   shipped is cosmetic; v1 README claims it as a quality gate.
9. **#11 finding 2 — Create or fix `docs/behavior/routing.md`.** Two scripts
   reference it; lychee will catch it; the v1 SemVer commitment promises
   `docs/behavior/*` is the contract.

### P1 — fix before v1.1 if not v1

10. #2 sev-1 #1–4 — copy-text, ANSI, soft-cap, `[stopped]` annotation.
11. #6 critical 1, 2, 3 — followup recursion, cascade-close, chat-deletion
    pointer.
12. #5 finding 2 — escape `%` and `_` in LIKE search.
13. #5 findings 3, 4, 10, 11 — broadcaster correctness work-stream
    (CCW-3).
14. #8 finding 1 — `KNOWN_EXECUTOR_MODELS` divergence.
15. #8 finding 2 — `DISPLAY_NAME_MAX_LENGTH` at PATCH (CCW-2 work-stream).
16. #6 high 1 — Spawn-from-reply UI pill.
17. #9 bug 1 — `session.edit` missing from `SESSION_ACTIONS`.
18. #11 findings 1, 3 — `test_daily_probe.py`, diff_probe systemd timer.
19. #12 findings 2, 3, 4, 5 — quality gate cleanup.

### P2 — post-v1.1

20. All "minor" / "P2" / "design observation" findings across the audits.
21. Hardening items: tx isolation, queue caps, `tag.color` rendering, etc.
22. CCW-4 (utility-module scaffolding) and CCW-5 (spec audit) work-streams.

---

## Provenance

- **Orchestrator session:** `e997026e97154b8882e91c4b90d66aa0`
- **Tag attached to all 14 child sessions:** `v1 Feature Review` (id 21)
- **Audit dates:** all sessions opened 2026-05-07; closeouts received same
  day except #4 Inspector (closed inline-fixed via commit `bf1d7df`).
- **Source materials:** `README.md`, `CHANGELOG.md`,
  `docs/architecture-v1.md`, `docs/model-routing-v1-spec.md`,
  `docs/behavior/*.md`, `BEARINGS_ANALYTICS_v1.md`, `src/bearings/**`,
  `frontend/src/**`, `tests/**`, `scripts/**`.

