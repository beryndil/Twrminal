# Sessions — observable behavior

A session is a row in Bearings that ties together a conversation
transcript, its messages, SDK transcript entries, checkpoints, and
metadata. This document covers the session-level actions beyond
day-to-day chatting; it does not prescribe implementation.

Sibling subsystems referenced here:
[chat](chat.md), [context-menus](context-menus.md),
[prompt-endpoint](prompt-endpoint.md).

## Inline rename

### Trigger

Double-clicking the session-row title area (the title text span, not
the checkbox or tag chips) enters inline rename mode. The same rename
flow is also reachable via **Rename** from the session row right-click
context menu (`docs/behavior/context-menus.md` §"Session row").

A plain single-click within the dblclick window is consumed by the
title span and deferred by a 300 ms guard; if no second click follows,
normal row activation (navigation + `onSelect` + `markSessionViewed`)
fires after the guard expires. Modifier clicks (ctrl / meta / shift) on
the title are passed through to the anchor for multi-select and
range-select as usual.

### Behavior

An `<input>` replaces the title text with the current title pre-filled
and selected. **Enter** commits via `PATCH /api/sessions/{id}`;
**Esc** cancels; blur commits (same as Enter).

---

## Export contract

### Trigger

Right-clicking a sidebar session row → **Export session JSON** triggers
a browser download. The file is named `<slug>.json` where `<slug>` is
the session title lowercased with non-alphanumeric runs collapsed to
`-`, leading/trailing `-` stripped. Falls back to `session.json` when
the title slug is empty.

### Backend endpoint

```
GET /api/sessions/{id}/export
```

**Success** — `200 OK` with `Content-Type: application/json` and
`Content-Disposition: attachment; filename="<slug>.json"`.

**Not found** — `404` when the session id does not exist.

Closed sessions (``closed_at`` set) are **not** rejected — this
endpoint returns `200` for any existing session regardless of close
state. (Compare: the prompt endpoint returns `409` on closed sessions.)

### Export schema

The body is a JSON object:

```json
{
  "session":     { ...SessionOut fields... },
  "messages":    [ ...MessageExport...    ],
  "tool_calls":  [ ...SDK transcript blobs... ],
  "checkpoints": [ ...CheckpointExport... ],
  "attachments": []
}
```

**`session`** — One-to-one with the `GET /api/sessions/{id}` response
shape (`SessionOut`). Contains all metadata: title, kind, model,
working_dir, routing columns, timestamps, closing_summary, etc.

**`messages`** — Every row from the `messages` table in chronological
order (`created_at ASC, id ASC`). Includes all roles: `user`,
`assistant`, `system`, `tool`. All columns are included (full-fidelity
— no fields are stripped).

**`tool_calls`** — Raw SDK transcript entries from the
`sdk_session_entries` table, in write order (`seq ASC`). These are
opaque JSON blobs produced by the Claude Code CLI during execution and
stored verbatim by Bearings. They contain structured tool input and
output records at the SDK level. Callers should treat this array as
pass-through data; Bearings does not parse or validate the entry shape.

**`checkpoints`** — Every row from the `checkpoints` table in
chronological order. Each entry carries `id`, `session_id`,
`message_id`, `label`, `created_at`.

**`attachments`** — Always `[]` in v0.18.x. Uploads are
content-addressed and shared globally; there is no per-session
attachment linking table yet. This field is reserved for a future
version.

### Context-menu integration

The action id is `session.export_json`. It appears in the **Copy**
section of the session row context menu (between "Copy share link" and
"Delete session"). The action is always visible (not gated on closed
state or session kind).

### Frontend implementation notes

`exportSessionJson(session)` in `frontend/src/lib/api/sessions.ts`:

1. `GET /api/sessions/{id}/export`.
2. On `200` — converts the response to a `Blob`, creates an object URL,
   clicks a synthetic `<a download="<slug>.json">`, then immediately
   revokes the URL.
3. On non-`2xx` — throws `ApiError` (the caller receives no feedback
   beyond the error; a future polish pass can add a toast).

---

## Import contract

### Trigger

**Sidebar → "Import session…"** button (below the New Session pill)
opens the `SessionImportDialog`. The user either pastes the contents of
a `.json` export file into the textarea, or uses the "Choose file…"
button to pick the file directly. Clicking **Import** submits the
payload to the backend.

On success the dialog closes and the newly-imported session is opened
in the conversation pane (same navigation path as clicking a session
row). On a 409 or validation error the dialog stays open and the error
detail is shown inline.

### Backend endpoint

```
POST /api/sessions/import
```

The request body must be a JSON object conforming to the `SessionExport`
wire shape (the same format produced by `GET /api/sessions/{id}/export`).

**Success** — `201 Created` with the `SessionOut` for the newly-imported
session; `Location: /api/sessions/<id>` header.

**Conflict** — `409 Conflict` when `session.id` in the payload matches
an existing session row and `?force` is absent.  Pass
`?force=true` to delete the existing row (and cascade to messages,
checkpoints, sdk_entries) before re-importing.

**Validation error** — `422 Unprocessable Entity` when the body does not
parse as `SessionExport` or any field fails DB-layer validation (unknown
model name, bad `kind`, label over the cap, etc.).

### Import semantics

* The session row is created with its **original `id`** (the UUID from
  the export) so the imported row is round-trip identical and the
  `Location` header points at the original address.
* **`checklist_item_id` is cleared** — the foreign-key target
  (`checklist_items` row) does not exist in the destination instance.
* Routing-decision columns (`routing_advisor_model`,
  `routing_advisor_max_uses`, `routing_effort_level`) are set to their
  schema defaults (`NULL / 5 / auto`) because `SessionOut` does not
  carry them.
* `error_pending` is unconditionally `false` on import — the session is
  not in an error state from the destination runner's perspective.
* Messages are inserted with their **original ids and all field values**
  (routing columns, token counts, `pinned`, `hidden_from_context`).
  `message_count` on the session row is set from the length of the
  imported messages array.
* Checkpoints are inserted with their **original ids and timestamps**.
* `tool_calls` (SDK transcript entries) are appended in order; the
  destination assigns new sequential `seq` values (monotonically
  increasing from 0 within the session).

### Frontend implementation notes

`importSessionJson(exportJson, options?)` in
`frontend/src/lib/api/sessions.ts`:

1. `POST /api/sessions/import` (or `?force=true` when
   `options.force === true`) with `exportJson` as the request body.
2. Returns the `SessionOut` on 201.
3. Throws `ApiError` on non-`2xx` (caller surfaces the `.body.detail`
   inline in the dialog).

`SessionImportDialog.svelte` in
`frontend/src/lib/components/sidebar/SessionImportDialog.svelte`:

* Textarea + "Choose file…" button (reads file text client-side).
* Submit: JSON-parses the textarea content, calls `importSessionJson`,
  invokes `onImported(session)` on 201, shows `detail` inline on error.
* Dismiss: Cancel button, backdrop click, or Escape key → `onCancel()`.
