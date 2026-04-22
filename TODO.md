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

## File-size audit (CLAUDE.md: max 400 lines)

Several files were split during v0.2/v0.3 work — see the archive's
`## Open follow-ups` § "File-size audit" for the full record. One
regression remains:

- [ ] `src/bearings/agent/runner.py` regressed to 657 lines after
  tool-output coalescer landed (was 379 after the prior split).
  Extract the `_ToolOutputBuffer` + `_buffer_tool_output` /
  `_delayed_flush` / `_flush_tool_buffer` / `_flush_all_tool_buffers`
  / `_drop_tool_buffer` cluster into `agent/tool_output_coalescer.py`
  with a tiny `ToolOutputCoalescer` class that holds the buffers
  dict and takes `db` + `session_id` via constructor. Runner keeps
  one reference and calls `await coalescer.buffer(id, chunk)` /
  `coalescer.drop(id)` / `await coalescer.flush_all()`. Should land
  runner.py back under 400.

## Browser verification — deferred to pre-1.0.0

Consolidated pre-1.0.0 regression pass lives in `TESTING_NOTES.md`
§"Pre-1.0.0 browser regression pass — TODO". The old per-slice
v0.2.13 / v0.3.1 / v0.3.3 checklists are stale (app has moved on) —
rewrite the list against the 1.0.0-candidate UI at the time and run
it then. Do not exercise the historical checklists as-is.

## Open feature work

- [ ] **Investigate long hang on a single assistant turn (2026-04-21).**
  Dave reported I sat silent for far too long between his "are you hung
  up?" prompt and the eventual plan-agent response during the token-cost
  mitigation planning session (transcript
  `~/.claude/projects/-home-beryndil-Projects-Bearings/f57209ca-38b8-41b8-a6e7-cf1439c0b50d.jsonl`).
  Unknown whether the culprit is (a) a long-running sub-agent not
  forwarding progress events, (b) the WS pipeline buffering without
  flushing partial deltas, or (c) Claude Code itself. Check: does the
  Bearings stream-loop emit any keepalive / "thinking" frames while a
  Task sub-agent is running? Does `message_delta` make it to the socket
  mid-sub-agent? Does the frontend show *anything* during the gap or a
  dead spinner? Reproduce with a deliberately long Task call and
  instrument.

- [ ] **Feature: "More info" button next to Copy on assistant responses
  (2026-04-21).** Dave's ask: each assistant turn already has a Copy
  button in its action row; add a sibling button that, when clicked,
  sends a follow-up prompt to the agent asking it to go into more
  detail on the *same* issue/topic from that response. Should feel
  like a one-click "elaborate" shortcut — no typing required.
  Likely surface: the message actions component in
  `frontend/src/lib/components/MessageTurn.svelte` (lines 344–356).

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
  fresh session, replan there.

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

### Blocking investigation (do first)

- [ ] **Verify SDK custom-tool registration in `claude-agent-sdk` 0.1.63.**
  Grep `.venv/lib/python3.12/site-packages/claude_agent_sdk/` for a way
  to register an in-process Python callable as a tool the model can
  invoke. If present, this unlocks Path B (below) without a fork.
- [ ] **Protocol trace of `subprocess_cli.py`.** Dump the raw JSON the
  Claude CLI sends over stdout during a long Bash call to confirm
  whether partial tool output is ever emitted on the wire. If the CLI
  only sends complete `ToolResultBlock`s, Path A gets you nothing —
  the limitation is in the closed-source CLI.

### Paths

- **Path C — Synthetic-delta spike (2–3h).** Add `ToolOutputDelta`
  event + reducer + fake backend emission (split final output into
  chunks with setTimeout). Proves frontend + event schema end-to-end.
  De-risk step before committing to A or B.
- **Path B — Bearings-owned Bash tool via SDK custom tool (6–10h).**
  Register an in-process Bash implementation; run the subprocess
  locally; stream chunks to the WS event bus; return final combined
  output to the SDK synchronously. No fork. Cleanest path *if SDK
  exposes custom-tool registration*.
- **Path A — SDK fork + subprocess stream parsing (8–16h + merge tax).**
  Fork `claude-agent-sdk`, modify `_internal/transport/subprocess_cli.py`
  to emit partial chunks as the CLI streams bytes. Only viable if the
  protocol trace confirms the CLI actually sends partial output.

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

### Decision

Path C first (proves the pipe). Then Path B if SDK supports it. Path A
only if B is unavailable and the protocol trace justifies it. If
protocol trace shows the CLI itself buffers, kill the feature with a
dated note in this TODO explaining why — genuine upstream limit, not a
Bearings shortcoming.

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
- **Still to do:**
  - [ ] Identify the TERM sender next time it happens. Add an `ExecStopPost`
        hook that dumps `/proc/self/status` + `last` + `loginctl` state,
        or enable audit rule `-a always,exit -F arch=b64 -S kill -F
        a1=15 -k bearings_term` so the sender is captured.
  - [ ] Consider `MemoryMax=4G` (soft guard; current peak 2.2G leaves
        headroom, but Slice-5+ reorg work could grow the footprint).

### 2026-04-21 — slice 5 frontend shipping a request the backend doesn't serve

- `GET /api/sessions/{id}/reorg/audits` returned 404 in the logs right
  before the outage (unrelated to the shutdown — process was healthy
  after). The `ReorgAuditDivider.svelte` component expects that route.
- Needs: register the audits route in `src/bearings/api/routes_reorg.py`
  and back it with the `0014_reorg_audits.sql` table, or feature-gate
  the frontend fetch until the route lands.

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

**Cleanup ticket:** remove the two `console.count` calls before merging
the refactor (or sooner if the audit closes inconclusive — they're noise
in DevTools either way).

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

## Security audit (2026-04-21) — pre-public-release

Full findings live in this session's transcript. Three audits ran in
parallel: privilege/agent-autonomy surface, architectural questionable
decisions, exposed-secrets sweep. Secrets sweep came back clean (modulo
identity leaks listed below). The other two converged on the same root
cause: the codebase was built assuming "localhost = safe" and that
assumption is wired into a dozen separate decisions.

### Ship-blockers (fix before first public push)

These are bugs, not preferences — no toggle, just fix.

- [ ] **WS has no Origin check.** `src/bearings/api/ws_agent.py:144-148`.
  Any tab in the same browser can drive the agent. Reject WS handshakes
  whose `Origin` isn't `http://127.0.0.1:<port>` / `localhost`.
- [ ] **Markdown XSS via `marked` + `{@html}` with no sanitizer.**
  `frontend/src/lib/render.ts:104-107` + every consumer that mounts
  `renderMarkdown` output via `{@html}` (`CollapsibleBody.svelte:102`,
  `TagEdit.svelte:221`). Add `isomorphic-dompurify`; pipe `marked.parse()`
  through it. Agent/tool output is attacker-influenced.
- [ ] **`tests/test_tags.py:453,456,507,513`** — `/home/beryndil/Projects/Bearings`
  hardcoded as test fixture. Identity leak in tracked code. Replace with
  `tmp_path` or generic placeholder.
- [ ] **Migrations run with no transaction wrapping, no checksum, no
  downgrade detection.** `src/bearings/db/_common.py:36-49`. Wrap each
  in `BEGIN/COMMIT`; record a checksum alongside the name; refuse to
  start when applied-but-unknown rows exist.
- [ ] **`/api/fs/list` enumerates the entire host.** `src/bearings/api/routes_fs.py:43-57`.
  Clamp to a configured allow-root (default `Path.home()`).
- [ ] **Resolve `CLAUDE.md:12` "Repository TBD"** — pick the org or remove
  the note before the README ships. (Org chosen 2026-04-22:
  `Beryndil/Bearings`. CLAUDE.md edit still pending.)
- [ ] **Decide on commit-email exposure.** `beryndil@hardknocks.university`
  and `dwhennigan@gmail.com` are in commit history. If either should not
  appear publicly, run `git filter-repo` (or fresh init) before first
  push to a public remote.

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

- [ ] Land all ship-blockers above (they're not behind a toggle).
- [ ] Add config schema for every togglable gate (see findings list).
- [ ] Build the three preset profiles.
- [ ] Add startup banner that prints active profile + which gates are
  open.
- [ ] Rewrite README intro around the profile model.

### High but not ship-blocker (fold into toggle layer)

- [ ] Auth-token-in-WS-query-string + non-constant-time compare.
  `src/bearings/api/auth.py:43-53`.
- [ ] DB file written at default umask (world-readable on multi-user
  boxes). `os.chmod(path, 0o600)` after create.
- [ ] Runner survives WS disconnect for `idle_ttl_seconds=900` (closing
  the browser ≠ stopping the agent). `safe` profile: ttl=0 or much
  shorter.
- [ ] Systemd unit has zero hardening — no `ProtectHome`, `PrivateTmp`,
  `NoNewPrivileges`, `MemoryMax`. `config/bearings.service`.
- [ ] Skill/command scanner walks `~/.claude/plugins` and surfaces
  everything in the UI palette. `safe` profile: scope to project only.
- [ ] `cfg.server.host=0.0.0.0` accepted with no interlock when auth=off.
  Refuse to start if non-loopback bind + no auth + no TLS.
- [ ] No global `max_budget_usd` default — runaway loop is unbounded.

### Cleanup (low priority)

- [ ] `LIKE` query unescaped wildcard DOS. `src/bearings/db/_messages.py:281-298`.
  Use `LIKE ? ESCAPE '\\'` and escape `%` `_` `\` in input.
- [ ] `permission_mode` column has no `CHECK` constraint at SQL level.
  `src/bearings/db/schema.sql:18`.
- [ ] WS subscriber queues unbounded. `src/bearings/agent/runner.py:308-321`.
- [ ] `import_session` accepts arbitrary client-supplied JSON with no
  schema validation, no size cap, bypasses the "every session has ≥1 tag"
  invariant. `src/bearings/api/routes_sessions.py:223-232`.
- [ ] `commands_scan` follows symlinks during `rglob`.
  `src/bearings/api/commands_scan.py:60-77`.
- [ ] Multiple silent `except Exception` swallows in `agent/session.py`,
  `agent/runner.py`, `api/routes_tags.py`. Narrow the catches; surface
  a wire `error` event when a failure persists.

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
