# BEARINGS_ANALYTICS_v1.md

**Status:** Spec, ready for Claude Code implementation
**Depends on:** v0.1 base (`ARCHITECTURE.md`), v1 routing spec (`BEARINGS_MODEL_ROUTING_v1.md`)
**Conflicts with:** None. Adds tables and one right-pane tab. Does not modify core session/tag flow.

---

## 1. Why this exists

Bearings sits in the request path. Every turn passes through it. That means we can measure where the $200/month Max bucket is actually going — per tag, per session, per injected context block — without a separate observability layer.

Two problems this solves:

1. **Bucket attribution.** Which tags are consuming the bucket fastest? When `infra` has burned 40% of weekly with three days left, the routing spec's quota guard needs concrete numbers to act on. Right now it has bucket totals and nothing else.

2. **Redundancy detection.** Plugs (injected context: CLAUDE.md, tag memories, system prompt additions) get re-sent every turn of every session. When the same block repeats across sessions for days, that's a candidate for tag memory consolidation or an `on_open.sh` hook. Right now there's no way to see this.

This is *not* a generic observability layer. It is two specific views built on a shared event stream, plus a length monitor on the injection layer.

---

## 2. Scope

**In scope:**

- Per-turn token logging (input, output, cache read, cache creation) tied to session, tag, model
- Bucket snapshot polling (`/usage`) and tag-share computation
- Plug block hashing, repeat detection, diff view, promotion to tag memory or `on_open.sh`
- Plug length monitoring with green / yellow / red thresholds
- "Start new session with fresh plug" workflow: AI drafts the new plug, user reviews in modal, user fires when ready
- New right-pane tab housing all three views

**Out of scope:**

- Cross-session "similar task" semantic comparison (would need an LLM call inside the tracker — not worth it)
- Cost-per-token math (subscription, no per-token cost exists; the unit is bucket consumption)
- "Savings vs all-Sonnet baseline" KPI (already retired)
- Conversation history token tracking (handled by Claude Code's `/compact` — different layer)
- Per-token dollar amounts in UI (subscription model — show bucket headroom, not dollars)

---

## 3. Critical constraints

### 3.1. Tokens are real money

User is on Max plan ($200/mo). Bucket runs out. Bucket running out means buying more. Every UI string and metric must respect this. Never frame tokens as "free," "negligible," or "noise." Headroom remaining and burn rate are the primary signals.

### 3.2. Tokenizer-aware logging

Claude Opus 4.7 (released April 16, 2026) shipped a new tokenizer that produces up to 35% more tokens for identical text. **Never aggregate token counts across models without splitting by model first.** Schema enforces this: every token count row carries its `model` field. Aggregation queries that don't group by model are bugs.

### 3.3. Soft warnings, not forced choices

User explicitly does not want hard modals that block work. The yellow popup is a dismissible suggestion. The red warning is a persistent banner, not a blocker. The user makes the call. The system surfaces the data.

### 3.4. Plug = injected context, not conversation history

Throughout this doc, "plug" means the layer Bearings injects at session start and that Claude Code reloads on `/compact`: CLAUDE.md, tag memories, system prompt additions, MCP tool descriptions, skill descriptions. It does **not** mean the conversation that grows turn-by-turn. The conversation is Claude Code's domain.

---

## 4. Data model

### 4.1. New tables

```sql
-- Per-turn token accounting. One row per Claude API turn.
CREATE TABLE turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL,                     -- 0-based within session
    timestamp INTEGER NOT NULL,                       -- unix ms
    model TEXT NOT NULL,                              -- 'claude-opus-4-7', 'claude-sonnet-4-6', etc.
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, turn_index)
);
CREATE INDEX idx_turns_session ON turns(session_id);
CREATE INDEX idx_turns_timestamp ON turns(timestamp);
CREATE INDEX idx_turns_model ON turns(model);

-- Plug blocks: each unique injected context block, hashed.
-- Same block reused across sessions = same row.
CREATE TABLE plug_blocks (
    hash TEXT PRIMARY KEY,                            -- sha256 of normalized content
    block_type TEXT NOT NULL,                         -- 'claude_md' | 'tag_memory' | 'system_addition' | 'mcp_tools' | 'skill_desc' | 'other'
    content TEXT NOT NULL,                            -- the raw block text
    token_count INTEGER NOT NULL,                     -- counted at first sight
    token_count_model TEXT NOT NULL,                  -- which model's tokenizer was used
    first_seen INTEGER NOT NULL,                      -- unix ms
    last_seen INTEGER NOT NULL,
    source_path TEXT                                  -- file path if applicable (e.g. ~/.claude/CLAUDE.md)
);
CREATE INDEX idx_plug_blocks_type ON plug_blocks(block_type);
CREATE INDEX idx_plug_blocks_last_seen ON plug_blocks(last_seen);

-- Which plug blocks were injected into which sessions.
-- Plugs are session-scoped, not turn-scoped (they reload on /compact, but the
-- same set is used for the session's lifetime).
CREATE TABLE session_plug_blocks (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    block_hash TEXT NOT NULL REFERENCES plug_blocks(hash),
    injected_at INTEGER NOT NULL,                     -- unix ms
    PRIMARY KEY (session_id, block_hash)
);
CREATE INDEX idx_spb_block ON session_plug_blocks(block_hash);

-- Snapshots of /usage polling. One row per poll.
CREATE TABLE bucket_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,                       -- unix ms
    five_hour_used INTEGER,                           -- tokens used in current 5h window
    five_hour_limit INTEGER,                          -- 5h window cap
    weekly_used INTEGER,                              -- tokens used in current weekly window
    weekly_limit INTEGER,                             -- weekly cap
    raw_response TEXT                                 -- JSON dump of /usage response for debugging
);
CREATE INDEX idx_bucket_snapshots_ts ON bucket_snapshots(timestamp);

-- User-suppressed warnings. When user dismisses "this plug is large" for a
-- given block hash, don't keep nagging.
CREATE TABLE suppressed_warnings (
    block_hash TEXT NOT NULL REFERENCES plug_blocks(hash),
    warning_type TEXT NOT NULL,                       -- 'yellow_length' | 'red_length'
    suppressed_at INTEGER NOT NULL,
    PRIMARY KEY (block_hash, warning_type)
);
```

### 4.2. FTS index

Add `plug_blocks.content` to the existing FTS5 index so the redundancy view can search inside block content (e.g., "show me blocks mentioning `aiosqlite`"). Use `content='plug_blocks'` and `content_rowid` linkage.

### 4.3. What this does NOT add

- No `project_files` table.
- No semantic embedding table.
- No "context library" mirror of file contents.
- No per-token cost column.

---

## 5. Plug capture and hashing

### 5.1. When a session is created

1. Bearings assembles the plug (CLAUDE.md + matching tag memories + any system prompt additions + MCP tool descriptions Claude Code will see + skill descriptions).
2. For each block:
   - Normalize: strip trailing whitespace per line, normalize line endings to `\n`, trim leading/trailing blank lines. Do **not** lowercase or reformat — diffs need fidelity.
   - Hash: `sha256(normalized_content)`.
   - Insert into `plug_blocks` with `INSERT OR IGNORE`. If the row exists, update `last_seen`.
   - Insert into `session_plug_blocks`.
3. Token-count each block using the model the session is configured for. Store the count and model on the `plug_blocks` row only on insert (first sighting). Don't recount on every reuse — the cost is in the API hit, not our local accounting.

### 5.2. Block identity rules

- **CLAUDE.md** is one block per distinct file content. Edit the file → new hash → new row. Old row stays (for history).
- **Tag memory** is one block per `(tag, version)`. Same tag, edited memory → new hash, but `block_type='tag_memory'` and we can detect the lineage via tag name in the source path or a separate `tag` column if useful (not required for v1).
- **System prompt additions** hash by content alone. Same addition across sessions = same row.
- **MCP tool descriptions and skill descriptions** can be lumped under their own types but are lower priority — they're rarely the redundancy that matters. Capture them anyway for completeness; the user can filter them out in the redundancy view.

### 5.3. Token counting

Use Anthropic's `count_tokens` endpoint or the local tokenizer that ships with the Claude Code SDK. Always pass the target model. Record the model used in `token_count_model`.

---

## 6. Bucket attribution

### 6.1. Polling

A background task polls `/usage` on the cadence already defined in the routing spec. Each poll inserts a row into `bucket_snapshots`. Don't try to deduplicate; the table is a time-series.

### 6.2. Per-tag share computation

A tag's share over a window is:

```
share(tag, window) = sum(turn.input + turn.output for turns in window where session.tags contains tag)
                     / sum(turn.input + turn.output for all turns in window)
```

Critically:

- A turn only counts toward a tag if the session has that tag at the time of the turn. Use the session's tag set as it stood when the session was active. (If we want temporal accuracy we'd need a `session_tags_history` table — defer until anyone actually needs it.)
- **Group by model first.** If a query mixes Opus 4.7 and Sonnet 4.6 token counts, results are misleading by up to 35%. The view returns either a per-model breakdown or a normalized number with the normalization made explicit.

### 6.3. Burn rate

`burn_rate(tag, window) = tokens(tag, window) / wall_clock_minutes(window)`

Used in the UI to flag tags trending upward fast. Compare current 30-min burn rate to last-7-days median for that tag.

---

## 7. Redundancy detection

### 7.1. Definition

A block is "redundant" when its hash appears in `session_plug_blocks` for **N or more sessions** within the user-selected scope. Default N = 3.

### 7.2. Scope filters (UI)

Keep the filter UI minimal. Two controls:

- **Tag** — single dropdown, defaults to "all tags" or the currently active sidebar filter.
- **Session count** — slider, "last N sessions," default 25, range 5–200.

Date range is *not* a separate control in v1. "Last N sessions" is the more intuitive scope for this user.

### 7.3. Ranking

Sort blocks by:

1. **Repeat count** within scope (descending).
2. **Total token cost** — `repeat_count × token_count` (descending tiebreaker).

The second metric matters: a 50-token block repeated 100 times is less worth fixing than a 5,000-token block repeated 10 times. Both numbers are surfaced in the UI.

### 7.4. Diff view

When a user expands a block:

- Show the canonical content of the current hash.
- List sessions where it appeared (session title, timestamp, tag chips).
- If multiple hashes share the same `source_path` and `block_type`, show a between-versions diff (unified diff format, rendered with monospaced font and red/green line styling).

### 7.5. Promote actions

Each block exposes two promote buttons:

**Promote to tag memory:**

- Opens a modal pre-filled with the block content, scaffolded as markdown.
- Tag selector pre-populated with the most common tag among sessions that used this block.
- On save: writes the tag memory file, **auto-applies the tag to the next-created session** so the user doesn't need to remember to attach it.
- Suggests deleting the block from CLAUDE.md or wherever it currently lives, but does not perform that delete (user owns that).

**Promote to `on_open.sh`:**

- Opens a modal with the block content shown for reference.
- Editor area scaffolds an `on_open.sh` snippet — typically `cat <<'EOF' > .bearings/scratch/<name>.md ... EOF` or an environment setup command, depending on block content.
- Saves into the active working directory's `.bearings/on_open.sh`, creating the directory if missing (per the v0.4.x directory context spec).
- Block content itself is *not* deleted; the user reviews and removes from source after.

---

## 8. Plug length monitoring

### 8.1. Thresholds

Computed as the sum of all plug block token counts for a session at injection time, model-normalized.

| Status | Range (tokens) | UI |
|--------|----------------|-----|
| Green | < 500 | No indicator (default state) |
| Yellow | 500 – 1499 | Dismissible popup on session creation, persistent yellow dot in the right-pane tab |
| Red | ≥ 1500 | Persistent banner at top of session view, red dot in the right-pane tab. NOT modal. NOT blocking. |

### 8.2. Yellow popup behavior

Triggers once per session creation when the assembled plug crosses 500 tokens.

Body text:

> This session's plug is approaching critical size (X tokens). At this length it starts eating bucket headroom on every turn. Consider starting a fresh session with a tighter plug, or consolidating repeats into a tag memory.

Three buttons:

- **Start new session with fresh plug** (primary)
- **Continue anyway** (secondary, dismisses for this session)
- **Don't show again for this block** (tertiary, writes to `suppressed_warnings`)

### 8.3. Red banner behavior

Same conditions as yellow but at ≥ 1500 tokens. Persistent banner in session view. Acknowledged once per session, then collapses to a small red dot. Does not re-trigger mid-session.

Same three buttons as yellow, with text adjusted to reflect severity.

### 8.4. "Start new session with fresh plug" flow

This is the workflow primitive the user already uses manually. The flow:

1. User clicks the button.
2. Bearings sends a meta-prompt to Claude Code (the same model the user's current session is using) with the current session's most recent context summary, the active tag set, and instruction: *"Draft a tight plug for a new session that picks up where this leaves off. Aim for under 500 tokens. Output only the plug content."*
3. The draft returns and opens in a **review modal** — not auto-fired.
4. User edits if needed, then hits **Create session**. Modal closes, new session opens with the reviewed plug.
5. If the user hits **Cancel**, no session is created.

The token cost of generating the draft is itself logged as a turn under the source session, with a special tag chip `meta:plug-draft` so it's filterable out of bucket attribution if the user wants.

### 8.5. Threshold rationale

Anthropic's own context engineering guidance is that more context isn't automatically better — accuracy degrades as token count grows ("context rot"), and curating what's in context matters more than how much fits. Repeated, high-volume system prompts of 500+ tokens compound across calls.

500 / 1500 are starting values, exposed in user settings as `plug_yellow_threshold` and `plug_red_threshold` integers. Tune in production based on observed behavior.

---

## 9. API endpoints

All under `/api/analytics/`. All return JSON. All require the existing Bearings auth.

### 9.1. Logging (called by request pipeline, not UI)

```
POST /api/analytics/turns
{
  "session_id": "...",
  "turn_index": 12,
  "model": "claude-opus-4-7",
  "input_tokens": 8420,
  "output_tokens": 1102,
  "cache_read_tokens": 0,
  "cache_creation_tokens": 0
}
→ 201 Created
```

```
POST /api/analytics/plug-blocks/batch
{
  "session_id": "...",
  "blocks": [
    {"hash": "...", "block_type": "claude_md", "content": "...", "source_path": "..."},
    ...
  ]
}
→ 201 Created
```

### 9.2. Reading (UI)

```
GET /api/analytics/bucket/current
→ {
    "five_hour": {"used": 142000, "limit": 200000, "percent": 71},
    "weekly":    {"used": 1840000, "limit": 5000000, "percent": 37},
    "as_of": 1715000000000
  }
```

```
GET /api/analytics/attribution?window=5h|weekly&group_by=tag
→ [
    {"tag": "infra", "tokens_by_model": {"claude-opus-4-7": 78000, "claude-sonnet-4-6": 22000}, "share_total": 0.42, "burn_rate_per_min": 380},
    ...
  ]
```

```
GET /api/analytics/redundancy?tag=&last_n=25&min_repeats=3&block_types=
→ [
    {
      "hash": "...",
      "block_type": "claude_md",
      "token_count": 850,
      "token_count_model": "claude-opus-4-7",
      "repeat_count": 14,
      "total_cost_tokens": 11900,
      "sessions": [{"id": "...", "title": "...", "timestamp": ..., "tags": [...]}, ...],
      "source_path": "~/.claude/CLAUDE.md"
    },
    ...
  ]
```

```
GET /api/analytics/plug-blocks/{hash}
→ {full block including content + version history if multiple hashes share source_path}
```

```
GET /api/analytics/plug-blocks/{hash}/versions
→ [list of related hashes by source_path with timestamps and unified diffs]
```

```
GET /api/analytics/sessions/{id}/plug-summary
→ {
    "total_tokens": 1820,
    "status": "red",
    "blocks": [{"hash": "...", "type": "...", "tokens": 850}, ...]
  }
```

### 9.3. Actions

```
POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory
{
  "tag": "infra",
  "memory_content": "...",            // user-edited
  "auto_apply_to_next_session": true
}
→ 200 OK with new memory file path
```

```
POST /api/analytics/plug-blocks/{hash}/promote-to-on-open
{
  "working_directory": "/home/dave/infra",
  "snippet": "..."                     // user-edited
}
→ 200 OK with .bearings/on_open.sh path
```

```
POST /api/analytics/draft-new-session
{
  "source_session_id": "...",
  "carry_tags": ["infra", "monitoring"]
}
→ {
    "draft_plug": "...",
    "estimated_tokens": 320,
    "draft_cost_tokens": {"input": 4100, "output": 280}
  }
```

```
POST /api/analytics/sessions/from-draft
{
  "draft_plug": "...",                 // possibly user-edited
  "tags": ["infra"],
  "working_directory": "..."
}
→ {"session_id": "..."}
```

```
POST /api/analytics/warnings/suppress
{"block_hash": "...", "warning_type": "yellow_length"}
→ 200 OK
```

---

## 10. UI: right-pane tab

### 10.1. Placement

New tab in the right pane next to the existing plug monitor. Label: **Analytics** (or whatever fits the icon set the user prefers).

### 10.2. Three sections, top to bottom

**Section A — Bucket attribution**

- Two stacked horizontal bars at the top: 5-hour and weekly. These are the same bars the routing spec already polls for; this section shares the component, doesn't duplicate it.
- Below: per-tag attribution table. Columns: tag chip, tokens (split by model where relevant), share of bucket, burn rate, sparkline of last 24h. Sortable by share or burn rate.
- Toggle: 5-hour view / weekly view.

**Section B — Redundancy**

- Two filter controls at the top: tag dropdown, "last N sessions" slider.
- List of repeated blocks, sorted by total cost tokens. Each row shows: block type icon, first-line preview, repeat count, token count × repeats = total cost.
- Click a row to expand: full content, list of sessions, diff view between versions if applicable, promote-to-tag-memory and promote-to-on-open buttons.
- Block type chips at the top let user filter out MCP/skill descriptions if they're noise.

**Section C — Active session plug**

- Shows the current session's plug breakdown: total tokens, status color, list of blocks with their individual token counts.
- Each block has an inline "promote" affordance (same workflow as Section B).
- This section answers "what's in *my current session's* plug right now."

### 10.3. Edit-from-panel

The user wants to edit plugs directly from the panel (mentioned in the conversation: "I want to build into that the ability to edit each plug from that particular panel"). For each block listed in Section C, an edit button opens the source file (CLAUDE.md, tag memory file, etc.) in a side editor. Save updates the file *and* invalidates the current session's plug — Bearings recomputes the hash, updates `last_seen`, and on the next turn the new content is what gets sent. The session UI shows a small "plug updated mid-session" indicator.

---

## 11. Implementation order for Claude Code

1. Migrations: new tables in section 4.
2. Logging path: hook the existing Bearings request pipeline so every turn writes to `turns`. Backfill is unnecessary; this is forward-looking data.
3. Plug capture: hook session creation so the assembled plug gets hashed and recorded before the first turn fires.
4. `/usage` polling worker (if not already implemented for routing spec — coordinate with that worker, don't duplicate).
5. Read endpoints (bucket, attribution, redundancy, session plug summary).
6. Right-pane tab with sections A and C first (these need only logging + reads). Section B (redundancy) ships next because it depends on enough sessions having been logged to be useful.
7. Promote actions and draft-new-session flow last — these write to the filesystem and call out to Claude Code, more failure surface, ship after the read path is stable.

---

## 12. Things explicitly cut

- A separate dashboard pane. Right-pane tab only.
- Cross-session semantic similarity. Hash-based exact match only.
- Date range as a primary filter. "Last N sessions" replaces it.
- Hard modals on red. Persistent banner only.
- Auto-firing the new-session flow. Always goes through user-reviewed draft modal.
- Per-token cost in dollars. Bucket headroom is the unit.
- "Savings vs baseline" framing anywhere in the UI.
- A `load_context` tool. Not needed for any of this.

---

## 13. Open questions for v1.x (do not block v1)

- Should `mcp_tools` and `skill_desc` block types be auto-suppressed from the redundancy view? Probably yes after observation.
- Do we want a per-tag custom yellow/red threshold? (e.g., `infra` runs heavy, allow 1000/2500.)
- Burn rate alerts as push notifications via the existing alarm tool? Possibly useful, possibly noise. Wait for data.

---

**End of spec.**
