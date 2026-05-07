# Sessions — observable behavior

A session is a row in Bearings that ties together a conversation
transcript, its messages, SDK transcript entries, checkpoints, and
metadata. This document covers the session-level actions beyond
day-to-day chatting; it does not prescribe implementation.

Sibling subsystems referenced here:
[chat](chat.md), [context-menus](context-menus.md),
[prompt-endpoint](prompt-endpoint.md).

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
