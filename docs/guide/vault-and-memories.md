# Vault and memories

The vault and memories are two separate surfaces that share a
theme: both surface markdown content into the active session. The
**vault** is a read-only browser over your on-disk plans + TODOs;
**memories** are tag-keyed system-prompt overlays that the agent
sees on every turn.

For the conceptual picture see
[../concepts.md §6](../concepts.md#6-vault-memories-and-the-system-prompt).
For the full observable contract see
[../behavior/vault.md](../behavior/vault.md) and
[../behavior/memories.md](../behavior/memories.md).

## What you can do here

### In the vault

* [Open the vault](#open-the-vault)
* [Search across plans + TODOs](#search-across-plans--todos)
* [Read a plan or TODO inline](#read-a-plan-or-todo-inline)
* [Drag a doc into the active composer](#drag-a-doc-into-the-active-composer)
* [Copy a doc body / link](#copy-a-doc-body--link)
* [Pin the vault to the active session](#pin-the-vault-to-the-active-session)

### With memories

* [View every memory across every tag](#view-every-memory-across-every-tag)
* [Filter by tag](#filter-by-tag)
* [Edit or create a memory under a tag](#edit-or-create-a-memory-under-a-tag)
* [Enable / disable a memory without deleting it](#enable--disable-a-memory)
* [Audit which memories are layered into a session](#audit-which-memories-are-layered)

---

## Walkthrough — Vault

### Open the vault

Click **Vault** in the sidebar's primary nav rail (between
Memories and Analytics). SvelteKit navigates to `/vault`, which
renders `VaultPanel`.

You'll see two sections:

* **Plans** — every `.md` file directly under each configured
  plan root (e.g. `~/.claude/plans/`). Sorted most-recent-mtime
  first. Each row shows the title (or slug when no `# heading`
  exists), the parent directory short name, and a relative mtime
  (*"2 days ago"*).
* **Todos** — every `TODO.md` matched by the configured globs
  (e.g. `~/Projects/**/TODO.md`). Same sort and metadata shape,
  with the project directory name as the visible label.

If the configured roots / globs match nothing:

> *"No plans found under `<configured roots>`. No TODO.md files
> match `<configured globs>`."*

The empty state names the configured paths so you can tell
whether the configuration or the filesystem is empty.

> The vault is **read-only**. You cannot create, edit, rename, or
> delete vault docs from inside Bearings. The on-disk files are
> the source of truth — the agent and your editor write to them
> directly. The vault re-scans on every list request, so external
> edits surface on the next open.

### Search across plans + TODOs

The search box at the top of the pane runs a **case-insensitive
substring** query over every vault doc. The query is treated as a
literal string — typing `foo.bar` matches the literal `foo.bar`,
not a regex.

Results render as a flat list. Each hit shows:

* the source doc title and its kind (Plan / Todo);
* the line number;
* a snippet of the matching line (clipped to a hard cap; long
  single-line entries wrap inside the snippet container).

Clicking a hit jumps to that doc and scrolls to the matching line.

When the result count hits the cap a *"showing first N — narrow
your query for more"* indicator appears. The query is not stored;
refreshing the pane clears it.

### Read a plan or TODO inline

Selecting a row opens the doc in a reading panel to the right of
the list (or as a full-pane takeover, depending on your app-shell
configuration). The doc title becomes the panel header; the body
renders as Markdown using the same renderer as the conversation
pane, including the linkifier (clickable `https://`, `file://`,
and resolved-path anchors).

#### Redaction of secret-shaped tokens

The vault renderer detects common secret shapes (high-entropy
strings adjacent to keywords like `key`, `token`, `secret`,
`password`) and replaces the visible text with a `••••••••` mask
plus a **Show** toggle.

* The mask is a render-time overlay — clipboard-copy paths still
  receive the literal text (so you can paste credentials where
  you need them after consciously toggling Show).
* The on-disk file is never modified.
* Toggle state is **not persisted**. Re-opening the doc renders
  it masked again.

Paths are never redacted; only credential-shaped tokens. The
redaction is an interactive aid, not a security control — a
determined reader can always view the underlying file directly.

### Drag a doc into the active composer

The vault is wired to feed the active chat composer in three
ways:

* **Drag** a vault row onto the conversation composer to paste
  the doc's title-as-Markdown-link
  (`[Title](file:///abs/path)`) at the cursor.
* **Right-click → Copy as Markdown link** puts the same link on
  the clipboard.
* **Selecting** text inside the rendered body and copying via the
  OS clipboard works the same way it does in the conversation
  panel.

Quoting a doc into a chat **does not modify the source on disk**.

### Copy a doc body / link

* **Right-click → Copy as Markdown link** — clipboard gets
  `[Title](file:///abs/path)`.
* **Right-click → Copy doc body** — clipboard gets the full
  markdown body verbatim (no redaction — see caveat above).

### Pin the vault to the active session

When the active chat session is in focus, the vault offers an
**Open against this session** affordance that:

* opens the doc in the reading panel;
* visually pins the chat session to the panel header;
* makes right-click → **Paste into composer** target that
  specific chat.

This is useful when you have multiple chats open and want to
quote the same plan into a specific one without confusing the
target.

When a vault doc's path appears inside a chat message body (the
agent referenced `~/.claude/plans/foo.md`), the linkifier renders
it as a clickable anchor. Clicking opens the doc **in the vault
pane in-place**, not in a new browser tab — vault is the
canonical reader for plans cited in conversation.

---

## Walkthrough — Memories

A memory is a markdown block stored in the database, attached to
a tag, that's resolved into the agent's system prompt on every
turn for any session carrying that tag.

### View every memory across every tag

Click **Memories** in the sidebar primary nav. The `/memories`
route renders the `MemoriesIndex` component as its default state
— a flat global view of every memory across every tag.

Layout:

* **Header** — *"Memories"* heading.
* **Tag chip row** — appears only when more than one tag is
  represented in the list (single-tag installs skip the row).
  Each chip is an `aria-pressed` toggle.
* **Flat memory list** — one row per `(tag, memory)` pair, sorted
  by `(tag_name ASC, memory_title ASC)` — grouping by tag is
  implied by the sort. Each row shows the memory title, tag-name
  badge, and a truncated body preview. Disabled memories render
  at reduced opacity with a *"disabled"* badge.
* **Empty state** — *"No memories yet — pick a tag to add one."*
  appears **only** when `GET /api/memories` returns `[]`. It is
  NOT shown when a chip filter reduces visible rows to zero
  (the full list is still non-empty).

### Filter by tag

Click any chip in the tag-chip row to activate the filter; click
the active chip again to clear it. Filtering hides rows whose tag
is not selected.

### Edit or create a memory under a tag

Two paths in:

* **From the global index.** Clicking any row opens the per-tag
  editor (`MemoriesEditor`) with the row's `tag_id` set as the
  active tag and the row's `memory_id` passed as
  `initialMemoryId`. Once the memory list loads, the editor
  automatically opens that memory for editing — the form is pre-
  filled, the save flow targets that memory id.
* **From a tag editor** (in **Tags** sidebar nav, or right-click
  any tag chip → **Edit tag**). The tag's editor includes a
  memories section with the same CRUD form.

The editor exposes:

* **Title** — required, displayed in the index.
* **Body** — markdown, free-form. This is what gets injected
  into the system prompt.
* **Enabled** — checkbox. Disabled memories are excluded from
  prompt injection but kept in the table.

Save fires `POST /api/memories` (create) or `PATCH /api/memories/
{id}` (update). On success, the next prompt sent in any session
carrying the memory's tag will see the updated body **without
restarting the runner**.

A *"← All memories"* back button returns to the global index.

### Enable / disable a memory

Toggle the **Enabled** checkbox in the editor. Disabled memories
render at reduced opacity in the index with a *"disabled"* badge,
and are excluded from system-prompt assembly on every subsequent
turn until re-enabled. Underlying body is preserved.

### Audit which memories are layered

Open the [Inspector → Instructions tab](inspector.md#instructions-tab)
on any open chat session. The tab renders the **full assembled
system prompt** with each layer's source kind distinguished:

| Source kind | Where it comes from |
|---|---|
| `tag_claude_md` | Per-tag `CLAUDE.md` filesystem content (working-dir walk-up). |
| `tag_memory` | DB-resident memory rows. `source_path` is `null`. |

Both kinds are visible in the breakdown, ordered by tag
precedence (lowest first, highest last). Memory bodies are
appended **after** the per-tag `CLAUDE.md` blocks, so memory
directives win on conflicts.

---

## Reference

### Vault failure modes

| Failure | Behaviour |
|---|---|
| Configured root missing | Plan roots that don't exist on disk are silently dropped from the index. The empty state appears only when *every* root is missing. |
| Read error on a single doc | Row renders with the metadata that was scannable; opening shows an inline *"unable to read"* badge in the reading panel. |
| Path outside the vault | Refused — *"this path is outside the vault."* Symlinks are resolved before the allowlist check, so symlink tricks resolve to the real path and gate correctly. |
| Search-cap reached | *"showing first N"* indicator surfaces; user is asked to narrow rather than silently truncating. |
| Stale mtime | The vault re-scans on every list request; mtimes always reflect the current filesystem state. |

### What the vault does NOT do

* Run the agent against vault content.
* Edit, rename, or delete files.
* Surface non-`.md` content (configured globs / plan-root walks
  restrict to markdown).
* Crawl recursively under plan roots — only the immediate `.md`
  children are listed; nested directories are intentionally not
  browsable. (TODO globs accept `**` recursion because that's
  how project trees are shaped.)

### `GET /api/memories` shape

Used by the global index. Sort: `(tag_name ASC, memory_title ASC)`.

| Field | Type | Notes |
|---|---|---|
| `tag_id` | int | Parent tag id |
| `tag_name` | str | Tag name as stored |
| `tag_color` | str \| null | Tag color hex; null if unset |
| `memory_id` | int | Memory primary key |
| `memory_title` | str | Memory title |
| `memory_body_preview` | str | Body truncated to `MEMORY_BODY_PREVIEW_MAX_LENGTH` (200) chars |
| `enabled` | bool | Enabled state |
| `updated_at` | str | ISO-8601 UTC |

Query params:

* `?only_enabled=true` — restricts to memories where `enabled =
  true`. Same semantics as the per-tag
  `GET /api/tags/{id}/memories` endpoint.

Empty database returns `[]`, not `404`.

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| List vault | Sidebar → **Vault** | `GET /api/vault` (and per-doc `GET /api/vault/{id}`) |
| Search vault | Search box | (folded into list endpoint) |
| Drag doc into composer | Drag row | (UI only) |
| Copy as Markdown link | Right-click row | (UI only — clipboard) |
| Copy doc body | Right-click row | (UI only — clipboard) |
| List memories (global) | `/memories` index | `GET /api/memories` |
| List memories (per-tag) | Tag editor | `GET /api/tags/{id}/memories` |
| Create memory | Editor → save new | `POST /api/memories` |
| Update memory | Editor → save existing | `PATCH /api/memories/{id}` |
| Delete memory | Editor → trash | `DELETE /api/memories/{id}` |
| Audit assembled prompt | Inspector → Instructions | `GET /api/sessions/{id}/system_prompt` |

---

## See also

* [../concepts.md §6](../concepts.md#6-vault-memories-and-the-system-prompt)
  — conceptual picture.
* [../behavior/vault.md](../behavior/vault.md) — full vault
  observable behavior.
* [../behavior/memories.md](../behavior/memories.md) — full
  memories observable behavior.
* [inspector.md](inspector.md) — Inspector Instructions tab.
* [settings.md](settings.md) — managing tags themselves.
* [../api.md §vault](../api.md#vault),
  [../api.md §memories](../api.md#memories).
* `src/bearings/web/routes/vault.py`,
  `src/bearings/web/routes/memories.py`,
  `src/bearings/agent/tags.py` (memory loader at
  `resolve_tag_memory_blocks`).
* `frontend/src/lib/components/vault/`,
  `frontend/src/lib/components/memories/`.
