# API reference

Bearings exposes a typed HTTP/WebSocket API. Authoritative wire
shapes live in [`openapi.json`](openapi.json) — this page is a
human-readable orientation grouped by route prefix, with one
table per group and a curl example for the most representative
endpoint.

The server binds to `127.0.0.1:8788` by default. Auth is optional
for the localhost case; when enabled, every request needs the
token from `~/.config/bearings/config.toml` as either a
`Bearer` header or the `?token=` query param.

> **121 paths across 25 route groups.** This page documents the
> shape; for full schemas, query/path parameters, response
> models, and required vs optional fields, point your tools at
> `docs/openapi.json` (e.g. import into Postman, generate an SDK
> via openapi-generator).

## Quick links

* [Conventions](#conventions)
* [WebSocket channels](#websocket-channels)
* Route groups — alphabetical:
  * [analytics](#analytics) · [checklists](#checklists) ·
    [checklist-items](#checklist-items) · [checkpoints](#checkpoints) ·
    [commands](#commands) · [diag](#diag) · [fs](#fs) ·
    [health](#health) · [history](#history) · [import](#import) ·
    [memories](#memories) · [messages](#messages) ·
    [metrics](#metrics) · [pending](#pending) ·
    [preferences](#preferences) · [quota](#quota) ·
    [routing](#routing) · [sessions](#sessions) · [shell](#shell) ·
    [tag-groups](#tag-groups) · [tags](#tags) ·
    [templates](#templates) · [uploads](#uploads) · [usage](#usage) ·
    [vault](#vault)

---

## Conventions

* **All responses are JSON** unless noted (`/api/sessions/{id}/export`
  carries `Content-Disposition: attachment`; `GET /api/uploads/
  {id}/content` returns the upload's raw bytes; `/metrics` returns
  Prometheus exposition format).
* **`POST /api/sessions/{id}/prompt`** and the two regenerate
  endpoints return **`202 Accepted`** with `Location:
  /api/sessions/{id}` and body `{"queued": true, "session_id": "<id>"}`.
* **`409 Conflict`** is returned when posting to a closed session or
  importing a session whose UUID already exists. The import endpoint
  accepts `?force=true` to delete-and-re-insert.
* **`422 Unprocessable Entity`** is returned for tag-cardinality
  violations (more than one project or severity tag), invalid
  routing match expressions, malformed import payloads, and
  closing a `kind='checklist'` session.
* **`429 Too Many Requests`** is returned by the prompt endpoint
  when the runner queue is full; carries a `Retry-After` header.

## WebSocket channels

Two channels:

| Path | Purpose |
|---|---|
| `/ws/agent/{session_id}` | Per-session agent event stream — token deltas, tool-call lifecycle, status events. Reconnect-replay backed by a 5 000-event ring buffer. |
| `/ws/sessions` | Sidebar-list pubsub — `runner_state` events (`is_running`, `is_awaiting_user`), `session_upsert` events for new/updated row state. |

Reconnect: clients send `Sec-WebSocket-Protocol: bearings,<token>`
when auth is enabled, then resume from the last seen sequence id
via the `?since=` query param. A reconnect after the ring buffer
has rolled over starts fresh from the latest event with no replay.

---

## analytics

Cross-session rollups + redundancy detection. See
[guide/analytics.md](guide/analytics.md).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/analytics/attribution` | Per-tag bucket attribution view. |
| `GET` | `/api/analytics/bucket/current` | Current bucket snapshot. |
| `POST` | `/api/analytics/draft-new-session` | AI-draft a new plug. |
| `POST` | `/api/analytics/sessions/from-draft` | Create a session from a drafted plug. |
| `GET` | `/api/analytics/redundancy` | Plug-block repeat table. |
| `POST` | `/api/analytics/plug-blocks/batch` | Batch lookup of plug-block hashes. |
| `GET` | `/api/analytics/plug-blocks/{hash}` | Plug-block detail + appearances. |
| `GET` | `/api/analytics/plug-blocks/{hash}/versions` | Plug-block version history. |
| `POST` | `/api/analytics/plug-blocks/{hash}/promote-to-tag-memory` | Promote block to a tag memory. |
| `POST` | `/api/analytics/plug-blocks/{hash}/promote-to-on-open` | Promote block to an `on_open.sh` hook. |
| `GET` | `/api/analytics/sessions/{session_id}/plug-summary` | Per-session plug breakdown. |
| `POST` | `/api/analytics/turns` | Internal — record a turn (called by the agent runner). |
| `POST` | `/api/analytics/warnings/suppress` | Suppress a redundancy / length warning. |

```bash
curl -sS http://127.0.0.1:8788/api/analytics/attribution
```

## checklists

Whole-checklist surface (items live under [checklist-items](#checklist-items)). See [guide/checklists.md](guide/checklists.md).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/checklists/{checklist_id}` | Overview (header + counts). |
| `GET` | `/api/checklists/{checklist_id}/items` | List items. |
| `POST` | `/api/checklists/{checklist_id}/items` | Create item. |
| `POST` | `/api/checklists/{checklist_id}/run/start` | Start the autonomous driver. |
| `POST` | `/api/checklists/{checklist_id}/run/stop` | Stop the run. |
| `POST` | `/api/checklists/{checklist_id}/run/pause` | Pause (soft stop). |
| `POST` | `/api/checklists/{checklist_id}/run/resume` | Resume after pause. |
| `POST` | `/api/checklists/{checklist_id}/run/skip-current` | Skip the current item. |
| `GET` | `/api/checklists/{checklist_id}/run/status` | Live driver status (counters, current item, leg). |

## checklist-items

Per-item operations + paired-chat surface. See
[guide/checklists.md](guide/checklists.md) and
[guide/paired-chats.md](guide/paired-chats.md).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/checklist-items/{item_id}` | Read. |
| `PATCH` | `/api/checklist-items/{item_id}` | Edit label / notes. |
| `DELETE` | `/api/checklist-items/{item_id}` | Delete (cascades to children + paired chat). |
| `POST` | `/api/checklist-items/{item_id}/check` | Check (closes paired chat). |
| `POST` | `/api/checklist-items/{item_id}/uncheck` | Uncheck. |
| `POST` | `/api/checklist-items/{item_id}/block` | Mark blocked. |
| `POST` | `/api/checklist-items/{item_id}/unblock` | Unmark blocked. |
| `POST` | `/api/checklist-items/{item_id}/move` | Drag-reorder target. |
| `POST` | `/api/checklist-items/{item_id}/indent` | Tab — nest under prev sibling. |
| `POST` | `/api/checklist-items/{item_id}/outdent` | Shift+Tab — pop one level. |
| `POST` | `/api/checklist-items/{item_id}/spawn-chat` | **💬 Work on this** — spawn paired chat. |
| `POST` | `/api/checklist-items/{item_id}/link` | Link to existing chat. |
| `POST` | `/api/checklist-items/{item_id}/unlink` | Detach paired chat. |
| `GET` | `/api/checklist-items/{item_id}/legs` | Audit history of driver legs on this item. |

## checkpoints

Bearings' own snapshot/restore points (distinct from the SDK's
`enable_file_checkpointing`).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/checkpoints` | List checkpoints (filter by session). |
| `POST` | `/api/checkpoints` | Create checkpoint at a message. |
| `DELETE` | `/api/checkpoints/{checkpoint_id}` | Delete. |
| `POST` | `/api/checkpoints/{checkpoint_id}/fork` | Fork a new session from this checkpoint. |

## commands

Slash-command palette for the composer.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/commands` | Scan installed commands and skill descriptions. |

## diag

Diagnostic introspection — useful for the daily probe and for
debugging.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/diag/server` | Bearings version, build commit, uptime. |
| `GET` | `/api/diag/sessions` | All sessions + their runner state. |
| `GET` | `/api/diag/drivers` | All autonomous-driver runs + their state. |
| `GET` | `/api/diag/quota` | Current quota state + last poll outcome. |

## fs

FS picker (sandboxed under `fs.allow_root` in config).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/fs/list` | Walk a directory; returns dirent rows. |
| `POST` | `/api/fs/pick` | Pick a path (validates it's under `allow_root`). |
| `GET` | `/api/fs/read` | Read a file (markdown / text only — sized cap applies). |

## health

Liveness probe.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/health` | `{"status":"ok","version":"…","uptime_s":…,"db_ok":true,"data_dir":"…"}` |

## history

The `history.jsonl` event stream that `.bearings/` directories
maintain.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/history/jsonl` | List entries for a directory. |
| `GET` | `/api/history/search` | Substring search across entries. |

## import

Bulk-import sessions from a v0.17.x install or any export bundle.

| Method | Path | Summary |
|---|---|---|
| `POST` | `/api/import/bearings` | Import bundle (accepts `?force=true`). |

## memories

Tag-keyed system-prompt overlays. See
[guide/vault-and-memories.md](guide/vault-and-memories.md).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/memories` | Global flat-list (across every tag). Query `?only_enabled=true`. |
| `GET` | `/api/memories/{memory_id}` | Read one. |
| `PATCH` | `/api/memories/{memory_id}` | Update. |
| `DELETE` | `/api/memories/{memory_id}` | Delete. |

> Per-tag create / list lives under [tags](#tags) — see
> `POST /api/tags/{tag_id}/memories` and
> `GET /api/tags/{tag_id}/memories`.

## messages

Per-message edit + admin operations. See
[guide/sessions.md](guide/sessions.md) for the user-facing flows.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/messages/{message_id}` | Read one message + its tool calls. |
| `DELETE` | `/api/messages/{message_id}` | Delete (admin — destructive). |
| `PATCH` | `/api/messages/{message_id}/hidden` | Hide from context (excluded from next prompt). |
| `PATCH` | `/api/messages/{message_id}/pinned` | Pin (kept across `/compact`). |
| `POST` | `/api/messages/{message_id}/move` | Move to a different session (used by reorg). |

## metrics

Prometheus exposition for `prometheus-fastapi-instrumentator`.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/metrics` | Prometheus exposition format. |

## pending

Mutate `.bearings/pending.toml` from the UI (alternative to
`bearings pending …`). See [guide/cli.md §`bearings pending`](guide/cli.md#bearings-pending).

| Method | Path | Summary |
|---|---|---|
| `POST` | `/api/pending/{name}/resolve?directory=<abs>` | Mark resolved. |
| `DELETE` | `/api/pending/{name}?directory=<abs>` | Dismiss. |

Both return `204 No Content` on success, `404` when the named op
does not exist, `500` on OS write failure. The `directory` query
param is the absolute path to the project root.

## preferences

Per-instance settings. See [guide/settings.md](guide/settings.md).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/preferences` | Read all. |
| `PATCH` | `/api/preferences` | Update touched fields (`model_fields_set` semantics). |
| `GET` | `/api/preferences/avatar` | Read avatar bytes. |
| `POST` | `/api/preferences/avatar` | Upload avatar. |
| `DELETE` | `/api/preferences/avatar` | Clear avatar. |
| `POST` | `/api/preferences/sync_from_system` | Refresh display name / locale from OS. |

## quota

Quota guard inputs. See [guide/routing.md §quota guard](guide/routing.md#force-a-fresh-quota-snapshot).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/quota/current` | Latest snapshot. **`404` when no snapshot has ever been recorded** (fresh install or v0.17.x migration). |
| `GET` | `/api/quota/history` | All snapshots in the retention window. |
| `POST` | `/api/quota/refresh` | Force an immediate poll outside the regular cadence. |

## routing

System routing rules + the routing-preview endpoint. Per-tag
rules live under [tags](#tags). See [guide/routing.md](guide/routing.md).

| Method | Path | Summary |
|---|---|---|
| `POST` | `/api/routing/preview` | Dry-run the evaluator with `{tag_ids, first_message}`. |
| `GET` | `/api/routing/system` | List system rules. |
| `POST` | `/api/routing/system` | Create system rule. |
| `PATCH` | `/api/routing/system/{rule_id}` | Update. |
| `DELETE` | `/api/routing/system/{rule_id}` | Delete. |
| `PATCH` | `/api/routing/{rule_id}` | Update tag rule (any tag — id is global). |
| `DELETE` | `/api/routing/{rule_id}` | Delete tag rule. |

## sessions

The largest group — every per-session surface. See
[guide/sessions.md](guide/sessions.md).

### CRUD + lifecycle

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/sessions` | List (with filters). |
| `POST` | `/api/sessions` | Create. |
| `GET` | `/api/sessions/{session_id}` | Read one. |
| `PATCH` | `/api/sessions/{session_id}` | Update (title, description, tags, …). Tag cardinality enforced. |
| `DELETE` | `/api/sessions/{session_id}` | Delete (cascades). |
| `POST` | `/api/sessions/{session_id}/close` | Archive. **`422` for `kind='checklist'`.** |
| `POST` | `/api/sessions/{session_id}/reopen` | Reopen a closed session. |
| `POST` | `/api/sessions/{session_id}/recover` | Recover a session whose runner crashed. |
| `POST` | `/api/sessions/{session_id}/viewed` | Mark viewed (clears the green pip). |
| `PATCH` | `/api/sessions/{session_id}/pinned` | Pin / unpin. |
| `PATCH` | `/api/sessions/{session_id}/model` | **Mid-session executor swap.** Calls `runner.set_model()`. |
| `PATCH` | `/api/sessions/{session_id}/permission_mode` | Mid-session permission-mode change. |
| `GET` | `/api/sessions/{session_id}/system_prompt` | Assembled system prompt with per-layer kinds. |
| `GET` | `/api/sessions/{session_id}/tokens` | Per-session token totals. |
| `GET` | `/api/sessions/{session_id}/todos` | TODO entries scoped to the session's working dir. |
| `GET` | `/api/sessions/{session_id}/paired-chat-info` | Breadcrumb info (parent checklist + item). |

### Conversation + messages

| Method | Path | Summary |
|---|---|---|
| `POST` | `/api/sessions/{session_id}/prompt` | **Send a message.** Returns `202` (queued). `409` on closed session. `429` on full queue. |
| `POST` | `/api/sessions/{session_id}/regenerate` | Regenerate the last assistant turn. `202`. |
| `POST` | `/api/sessions/{session_id}/regenerate_from/{message_id}` | Regenerate from a specific message. `202`. |
| `POST` | `/api/sessions/{session_id}/stop` | Stop the in-flight turn. |
| `GET` | `/api/sessions/{session_id}/messages` | List messages (paginated). |
| `GET` | `/api/sessions/{session_id}/tool_calls` | List tool calls (paginated). |
| `POST` | `/api/sessions/{session_id}/approvals/{request_id}` | Resolve an `AskUserQuestion` / tool-approval request. |

### Tags + reorg

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/sessions/{session_id}/tags` | List session's attached tags. |
| `PUT` | `/api/sessions/{session_id}/tags/{tag_id}` | Attach a tag (cardinality-checked). |
| `DELETE` | `/api/sessions/{session_id}/tags/{tag_id}` | Detach. |
| `POST` | `/api/sessions/{src_id}/reorg/merge` | Merge `src` into a destination session. |
| `POST` | `/api/sessions/{src_id}/reorg/split` | Fork a session from a chosen message. |
| `POST` | `/api/sessions/{src_id}/reorg/move` | Move messages between sessions. |
| `GET` | `/api/sessions/{dst_id}/reorg/audits` | Reorg audit log. |
| `DELETE` | `/api/sessions/{dst_id}/reorg/audits/{audit_id}` | Delete an audit row. |

### Spawn + bulk + import/export

| Method | Path | Summary |
|---|---|---|
| `POST` | `/api/sessions/{parent_id}/spawn_from_reply/{message_id}` | Fork a chat from an assistant message; idempotent. |
| `POST` | `/api/sessions/bulk` | Atomic batch close / delete / export / tag / untag. |
| `GET` | `/api/sessions/{session_id}/export` | Download session JSON. |
| `POST` | `/api/sessions/import` | Import session JSON (`?force=true` to overwrite). |

```bash
# Send a message
curl -sS -X POST http://127.0.0.1:8788/api/sessions/<id>/prompt \
  -H 'Content-Type: application/json' \
  -d '{"content":"hello"}'
# Response: 202 Accepted
# Body: {"queued": true, "session_id": "<id>"}
```

## shell

| Method | Path | Summary |
|---|---|---|
| `POST` | `/api/shell/exec` | argv dispatch — opens an external editor / file manager / browser. Sandboxed by config. |

## tag-groups

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/tag-groups` | List tag groups (the slash-namespaced `<group>/<name>` back-compat surface). |

## tags

Tag CRUD + per-tag routing rules + per-tag memories. See
[guide/settings.md §Tags page](guide/settings.md#tags-page-separate-route)
for the UI surface; [guide/routing.md](guide/routing.md) for
rules; [guide/vault-and-memories.md](guide/vault-and-memories.md)
for memories.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/tags` | List. |
| `POST` | `/api/tags` | Create. |
| `GET` | `/api/tags/{tag_id}` | Read. |
| `PATCH` | `/api/tags/{tag_id}` | Update. |
| `DELETE` | `/api/tags/{tag_id}` | Delete (cascades to rules + memories + session attachments). |
| `PUT` | `/api/tags/sort-order` | Bulk sort-order update. |
| `PATCH` | `/api/tags/{tag_id}/pinned` | Pin a tag in the sidebar. |
| `GET` | `/api/tags/{tag_id}/memories` | List memories under a tag. |
| `POST` | `/api/tags/{tag_id}/memories` | Create memory under a tag. |
| `GET` | `/api/tags/{tag_id}/routing` | List per-tag routing rules. |
| `POST` | `/api/tags/{tag_id}/routing` | Create rule. |
| `PATCH` | `/api/tags/{tag_id}/routing/reorder` | Reorder rules within the tag. |

## templates

Reusable session scaffolds. See
[guide/sessions.md §Save a session as a template](guide/sessions.md#save-a-session-as-a-template).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/templates` | List. |
| `POST` | `/api/templates` | Create. |
| `GET` | `/api/templates/{template_id}` | Read. |
| `PATCH` | `/api/templates/{template_id}` | Update. |
| `DELETE` | `/api/templates/{template_id}` | Delete. |
| `POST` | `/api/templates/{template_id}/instantiate` | Create a session from a template. |

## uploads

Content-addressed file uploads (shared across sessions globally —
no per-session attachment table yet).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/uploads` | List. |
| `POST` | `/api/uploads` | Upload (multipart). |
| `GET` | `/api/uploads/{upload_id}` | Metadata. |
| `GET` | `/api/uploads/{upload_id}/content` | Raw bytes. |
| `DELETE` | `/api/uploads/{upload_id}` | Delete. |

`bearings gc uploads` prunes upload subdirs older than the
retention window — see [guide/cli.md](guide/cli.md#bearings-gc-uploads).

## usage

Cross-session token rollups. See
[guide/inspector.md §Usage tab](guide/inspector.md#usage-tab) for
the per-session inline view; [guide/analytics.md](guide/analytics.md)
for the full Analytics page.

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/usage/by_model` | Last 7 days, totals by executor model. |
| `GET` | `/api/usage/by_tag` | Same window, totals by tag. |
| `GET` | `/api/usage/override_rates` | Rolling 14-day per-rule override rate (rules-to-review source). |
| `GET` | `/api/usage/turns` | Per-turn rows for filtered windows. |

## vault

Read-only vault surface. See
[guide/vault-and-memories.md](guide/vault-and-memories.md).

| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/vault` | List plans + TODOs. |
| `GET` | `/api/vault/search` | Case-insensitive substring search. |
| `GET` | `/api/vault/{vault_id}` | Read a doc by id. |
| `GET` | `/api/vault/by-path` | Read a doc by absolute path (gated by allowlist; symlinks resolve to real path). |

---

## See also

* [`openapi.json`](openapi.json) — authoritative wire shapes
  (regenerate via the recipe in [`CLAUDE.md`](../CLAUDE.md)).
* [concepts.md](concepts.md) — what the data behind these
  endpoints actually represents.
* [guide/](guide/) — task-oriented walkthroughs that consume
  these endpoints from the UI.
* [behavior/](behavior/) — observable per-subsystem behavior,
  including the 202 + 409 + 422 + 429 contracts referenced above.
* [architecture-v1.md §1.1.5](architecture-v1.md#115-bearingsweb--httpws-surface)
  — `web/routes/*.py` decomposition.
