# Testing Notes

## v0.1.37 (2026-04-19, server http://127.0.0.1:8787, auth off)

- **[fixed in v0.1.38]** Prompt send was bound to `⌘/Ctrl+Enter` with
  Enter inserting a newline — reversed now: Enter sends, Shift+Enter
  newlines. Matches chat UI conventions (ChatGPT / Claude / Slack).
  CheatSheet and placeholder updated to match.
- **[fixed in v0.1.38]** Inspector tool-call list was flat — now
  nested under an "Agent" collapsible disclosure with model subtitle
  and a running-count badge; the aside auto-scrolls to the latest
  tool call while the agent is streaming (and the disclosure is
  open).

## v0.2.13 (2026-04-19)

### Verified programmatically

These are confirmed by the automated gates, not by browser use.

- **Migrations 0006–0009 apply in order on a fresh DB.** Covered by
  `init_db` running all migrations at test fixture setup; 168
  backend tests + a clean `pytest`.
- **Prompt assembler produces 3 layers** (base → tag memories →
  session instructions), precedence matches pinned/sort_order/id,
  tag-without-memory is silently skipped, session_instructions
  always last. 8 cases in `test_prompt_assembler.py`.
- **`/api/sessions/{id}/system_prompt`** returns the same layered
  shape the agent sends to the SDK. Full-stack case in
  `test_tag_memories.py::test_system_prompt_full_stack`.
- **`POST /api/sessions` rejects `tag_ids: []` and unknown tag ids
  with 400.** Two cases in `test_routes_sessions.py`.
- **Tag memories CRUD round-trips** (GET/PUT/DELETE on
  `/api/tags/{id}/memory`), and delete-tag cascades to
  `tag_memories` via FK. 13 cases in `test_tag_memories.py`.
- **Tag defaults round-trip** on create + partial update; explicit
  null clears. 5 cases in `test_tags.py`.
- **AgentSession passes assembled prompt as
  `ClaudeAgentOptions.system_prompt`** when `db=conn` is wired,
  omits it when `db=None`. 2 cases in `test_agent_session.py`.

### Pending Dave's browser walkthrough — DEFERRED to pre-1.0.0

**Status (2026-04-21):** Deferred to a single pre-1.0.0 regression
pass. App is at v0.3.22; these checklists were written against the
v0.2.13 surface and the UI has moved on (Inspector tabs,
conversation header, new-session form, and tag edit modal have all
been reshaped multiple times since). Rewrite this checklist against
the *then-current* UI immediately before cutting 1.0.0 — don't
exercise the stale copy below.

The one positive observation worth preserving:

- [x] **WS + CLI `send`** against a live agent (2026-04-20):
  session `74374ddb` tagged `infra` with memory "Prefer nftables
  over iptables…". Prompt "one-liner firewall rule that blocks
  SSH except from 10.0.0.0/8" got back `sudo nft add rule inet
  filter input tcp dport 22 ip saddr != 10.0.0.0/8 drop` —
  nftables, unprompted. `/system_prompt` confirmed 2 layers
  (base + infra tag_memory, 66 tokens). Event stream:
  `message_start` → `thinking` → `token` (coalesced) →
  `message_complete` with cost_usd=0.176.

## v0.3.1 / v0.3.3 browser walkthroughs — DEFERRED to pre-1.0.0

Pane-resize (v0.3.1) and TagEdit/NewSessionForm picker (v0.3.3)
checklists folded into the single pre-1.0.0 regression pass noted
above. Leaving the historical spec here for reference, but **do
not run these as-is** — the UI has changed since and the list
should be rewritten against the 1.0.0-candidate surface.

<details>
<summary>Historical v0.3.1 / v0.3.3 checklist (stale)</summary>

### v0.3.1 — resize & collapse

- **Resizable panes**: drag the handle between sidebar and
  conversation — width updates live, clamps at 200px min, snaps
  to collapsed below that, maxes out at ~50% viewport. Release
  persists the width (reload the page to confirm). Same for
  conversation/inspector handle.
- **Collapse toggles**: click the chevron button centered on
  each handle; the near pane collapses to 0px. Click again —
  pre-collapse width restored. State survives reload.
- **Keyboard resize**: Tab to a handle (sky-500 focus ring
  shows), ArrowLeft/Right nudges 16px, Shift+Arrow nudges 48px.
  Enter or Space toggles collapse. For left handle, ArrowRight
  widens sidebar; for right handle, ArrowLeft widens inspector.
- **Collapse persistence across sessions**: collapse both
  sides, reload — they stay collapsed. Expand, reload — widths
  return to the last-dragged values.

### v0.3.3 — TagEdit / NewSessionForm pickers

- **TagEdit "Order" relabel**: open `infra` ✎ — the field
  previously labeled "Sort" now reads "Order". Hover the input
  for the tooltip "Lower number = higher in sidebar. Breaks ties
  in prompt assembly (later wins)."
- **TagEdit ModelSelect**: the Default model field is a
  dropdown showing `claude-opus-4-7` / `claude-sonnet-4-6` /
  `claude-haiku-4-5-20251001` / `Custom…`. Picking a known model
  stores it. Picking Custom clears the value and reveals a
  free-text input with focus. For a tag whose default_model is
  already an unknown id (e.g. a dated snapshot), the modal opens
  in Custom mode with the input pre-populated.
- **TagEdit FolderPicker**: the Default working dir field has
  a text input + "Browse" button. Browse opens an inline tree:
  breadcrumb at top (each segment is clickable to jump),
  ⬆ parent, hidden-dir toggle, grid of subdirectory buttons.
  Click a subdir to descend; breadcrumb updates. "Use this
  folder" writes the current path back to the input and closes
  the picker. A bad path (`/nope`) surfaces "not found" inline
  without clobbering the input.
- **NewSessionForm pickers**: same ModelSelect + FolderPicker
  in the + session form. Attaching a tag with defaults still
  prefills both fields (working_dir only when empty, model
  unconditionally per last-wins).
- **`/api/fs/list` live smoke**: run `curl -s
  "http://127.0.0.1:8787/api/fs/list?path=$HOME" | jq` —
  returns `{path, parent, entries[]}` with hidden dirs omitted.
  Add `&hidden=true` to include them. `path=./relative` → 400,
  `path=/nonexistent` → 404.

</details>

## Pre-1.0.0 browser regression pass — TODO

Single consolidated walkthrough to run immediately before cutting
1.0.0. Build the checklist against the *then-current* UI — don't
port the stale items above verbatim. Cover at minimum:

- Three-pane shell: resize, collapse, keyboard resize, reload
  persistence.
- Sidebar: session list, tag filter, sidebar search, new-session
  form (including tag-seeded defaults and picker widgets as they
  exist at 1.0.0).
- Conversation header: tag chips, cost / budget readout, context
  meter color bands (slate / amber / orange / red — or whatever
  the bands are when we ship 1.0.0).
- Message turns: markdown, code highlighting, Copy / elaborate
  actions, per-turn ⋯ menu (Move / Split), bulk-select mode,
  reorg undo toast, ReorgAuditDivider rendering.
- Inspector: Context disclosure + layer editors, tool-call list,
  approval broker UI, any 1.0.0-era tabs.
- Tag sidebar: TagEdit modal (name / pinned / order /
  defaults / memory / markdown preview / delete), chip
  interactions.
- Agent round-trip: WS + `bearings send` CLI against a live
  agent, tag memory observably steering output, cost / token
  accounting matches `/api/sessions/{id}/system_prompt` and
  `/metrics`.
- Settings / auth / service install paths if 1.0.0 exposes them.
