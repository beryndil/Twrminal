# Bearings v1 UI/UX Gap Audit
**vs. Behavioral Specs (docs/behavior/*.md)**  
**Status: v1.0 + v1.1 closing sweep**  
**Audit Date: 2026-05-03**

---

## Executive Summary

V1 has ~70% of the specified UI built. The app shell, core conversation flow, checklists, and most context menus are complete and functional. **Gaps fall into four categories:**

1. **Paired-chat wiring** — component exists but unmounted
2. **User interaction affordances** — buttons, modals, inline feedback missing
3. **Advanced conversation features** — regenerate, message splitting, template save
4. **Power-user surfaces** — command palette, cheat sheet, pending operations

Most gaps are **non-blocking for basic operation** but degrade the discoverability and polish of more advanced workflows.

---

## Category 1: Core Surfaces — COMPLETE ✓

These are built and functional per spec:

| Surface | Status | Notes |
|---------|--------|-------|
| **Conversation pane** | ✓ Complete | Message rendering, tool-work drawer, routing badges, model info |
| **Checklist pane** | ✓ Complete | Add/edit/delete/reorder items, nesting, item-status colors |
| **Inspector pane** | ✓ Complete | Agent / Context / Instructions tabs; Routing + Usage incomplete (see below) |
| **Sidebar + session list** | ✓ Complete | Rows, tags, pins, closed group, severities |
| **Composer** | ✓ Complete | Multi-line input, basic send, Stop button during turn |
| **Settings page** | ✓ Complete | Theme picker, default model/permission/workdir, system routing rules |
| **Vault pane** | ✓ Complete | Plans / TODOs list, read-only rendering, paste-to-composer |
| **Tags management** | ✓ Complete | Per-session tag attach/detach, tag editing |

---

## Category 2: Paired-Chat Wiring — BUILT BUT UNMOUNTED

**Component exists:** `frontend/src/lib/components/conversation/PairedChatIndicator.svelte`  
**Status:** Ready to mount; blocked on backend endpoint lookup.

### Missing:
1. **Conversation header breadcrumb** — `<parent checklist> › <item label>`  
   - Location: `/frontend/src/routes/+layout.svelte` line ~398 (conversation header)  
   - Requires: Backend `GET /api/sessions/{id}/paired-chat-info` endpoint (deferred per TODO.md)

2. **Sidebar annotation** — `↳ <parent checklist title>` under paired chat rows  
   - Location: `frontend/src/lib/components/sidebar/SessionRow.svelte`  
   - Requires: Same backend endpoint above

3. **Paired-chat link spawn** — "💬 Work on this" button on checklist items  
   - Location: `frontend/src/lib/components/checklist/ChecklistView.svelte` (item rendering)  
   - Status: `PairedChatLinkSpawn.svelte` component exists but not mounted  
   - Requires: Checkbox to spawn vs. existing-pairing affordance

### Spec Reference
- `docs/behavior/paired-chats.md` §"What 'paired' means observably" & §"Indicator placement"
- `docs/behavior/checklists.md` §"Item ↔ chat-session linking"

---

## Category 3: Conversation Interaction Affordances — PARTIALLY BUILT

### Missing UI Elements

| Feature | Spec Location | Status | Notes |
|---------|---------------|--------|-------|
| **"Ask for more detail" button** | `chat.md` §"What a message turn looks like" | ✗ Missing | Hover-RHS button on assistant bubble; tooltip-documented but not implemented |
| **Regenerate from message** | `chat.md` / `context-menus.md` | ⚠ Partial | Menu action exists; UI handlers unbuilt |
| **Message split dialog** | `context-menus.md` `message.split_here` | ✗ Missing | Carves conversation into sibling session |
| **Model switch dialog** | `chat.md` §"Manual mid-session model switch" | ⚠ Partial | Dropdown exists (header); confirmation modal missing |
| **Recovery button** | `chat.md` §"Error states" | ✗ Missing | "Recover" action when agent hits error (phase 2 deferral) |
| **Undo stop inline** | `chat.md` §"Stopping or interrupting" | ✗ Missing | ~3s ephemeral inline re-issue prompt suggestion |
| **Thinking block toggle** | `chat.md` §"What a message turn looks like" | ✓ Likely present | Check `MessageTurn.svelte` |
| **Message pin to header** | `context-menus.md` `message.pin` | ✗ Unimplemented | Floats bubble into conversation header when pinned |
| **Hide from context** | `context-menus.md` `message.hide_from_context` | ✗ Unimplemented | Greys message; drops from next prompt |
| **Move to session** | `context-menus.md` `message.move_to_session` | ✗ Unimplemented | Session picker modal + message relocation |

### Spec References
- `docs/behavior/chat.md` §"What a message turn looks like", §"Manual mid-session model switch", §"Error states"
- `docs/behavior/context-menus.md` §"Message bubble" actions

---

## Category 4: Power-User Surfaces — NOT IMPLEMENTED

### Global Keyboard / Discovery

| Binding | Spec | Action | Status |
|---------|------|--------|--------|
| `?` | `keyboard-shortcuts.md` | Cheat-sheet modal (all bindings + descriptions) | ✗ Missing |
| `Ctrl+Shift+P` | `keyboard-shortcuts.md` | Command palette (slash-commands + actions) | ✗ Missing |
| `Ctrl+Shift+O` | `keyboard-shortcuts.md` | Pending operations card (global floating) | ✗ Missing |
| `t` | `keyboard-shortcuts.md` | Template picker modal | ✗ Missing |
| `Shift+C` | `keyboard-shortcuts.md` | New chat **without** seeded defaults | ⚠ Partial | Binding wired; form-state reset missing |

### Slash Commands & Session-Lifecycle

| Feature | Spec | Status | Notes |
|---------|------|--------|-------|
| **Slash command palette** (`/advisor`, `/checkpoint`, etc.) | `chat.md` §"Slash commands in the composer" | ✗ Missing | Composer shows no completion/hint UI |
| **`/advisor`** | `chat.md` | ✗ Missing | Per-turn advisor override (wired at SDK; UI unbuilt) |
| **`/checkpoint`** | `chat.md` | ✗ Missing | Named gutter mark for fork points |
| **Save as template** | `context-menus.md` `session.save_as_template` | ✗ Missing | Dialog to name + store new template |
| **Templates list** | `keyboard-shortcuts.md` `t` binding | ✗ Missing | Picker modal populated from saved templates |
| **Fork from last message** | `context-menus.md` | ✗ Missing | New session with shared history |

### Vault Features

| Feature | Spec | Status | Notes |
|---------|------|--------|-------|
| **Vault search** | `vault.md` §"Search semantics" | ✗ Missing | Case-insensitive substring match over plans + TODOs |
| **Redaction overlay** | `vault.md` §"Redaction rendering" | ✗ Missing | Mask high-entropy tokens; Show toggle |
| **Drag-to-composer** | `vault.md` §"Paste-into-message" | ✗ Missing | Drag vault row → inserts title link |

---

## Category 5: Modal Dialogs & Confirmations — MOSTLY MISSING

| Dialog | Spec | Status | Blocking? |
|--------|------|--------|-----------|
| **New-session form** | `chat.md` §"When the user creates a chat" | ✓ Implemented | No |
| **Model switch confirmation** | `chat.md` §"Manual mid-session model switch" | ✗ Missing | No (basic flow works) |
| **Destructive action confirm** | `context-menus.md` | ✓ Implemented | No |
| **Session rename inline** | `context-menus.md` | ✓ Likely present | No |
| **Tag picker** | `context-menus.md` `session.edit_tags` | ✓ Likely present | No |
| **Session duplicate** | `context-menus.md` | ? Unclear | No |
| **Template save** | `context-menus.md` | ✗ Missing | No |
| **Message regenerate** | `context-menus.md` | ✗ Missing | No |
| **Split message** | `context-menus.md` | ✗ Missing | No |
| **Move message to session** | `context-menus.md` | ✗ Missing | No |

---

## Category 6: Inspector Tabs — PARTIAL

| Tab | Spec | Status | Notes |
|-----|------|--------|-------|
| **Agent** | `chat.md` §"Inspector pane" | ✓ Complete | Executor model, permission mode, working dir, budget, message count |
| **Context** | `chat.md` §"Inspector pane" | ✓ Complete | Title, description, context %, tokens, max, assembled-context placeholder |
| **Instructions** | `chat.md` §"Inspector pane" | ✓ Complete | Read-only per-session system prompt |
| **Routing** | `model-routing-v1-spec.md` §5 | ⚠ Partial | Per-message badge timeline; advisor totals; quota delta; "Why this model?" chain unbuilt |
| **Usage** | `model-routing-v1-spec.md` §10 | ⚠ Partial | 7-day headroom chart; by-model breakdown; advisor effectiveness unbuilt |

**Issue:** The Routing and Usage tabs need backend data wiring (per-message token logs, historical quota rollups) that may not be fully landed yet.

---

## Category 7: New-Session Dialog — MOSTLY COMPLETE

Per `chat.md` §"When the user creates a chat":

| Element | Status | Notes |
|---------|--------|-------|
| Tags selector | ✓ Present | Required ≥1 |
| Working directory | ✓ Present | Free-text + browse |
| Routing selection (model/advisor/effort) | ✓ Present | Executor dropdown; advisor checkbox (maybe) |
| First message body | ✓ Present | Multi-line textarea |
| Routing preview line | ⚠ Partial | Exists but may not update ~300ms post-keystroke per spec |
| Quota bars (overall + Sonnet) | ⚠ Partial | Component `QuotaBars.svelte` exists; wired to live quota? |
| Quota-downgrade banner | ✗ Missing | Yellow warning when quota guard downgrades the routed choice |
| Override quota button | ✗ Missing | "[Use Opus anyway]" in the downgrade banner |

---

## Category 8: Keyboard Bindings — 60% WIRED

**Implemented:**
- `c` / `Shift+C` — new chat (with/without defaults)
- `j` / `k` / `Alt+[` / `Alt+]` — sidebar navigation
- `Alt+1..9` — jump to sidebar slot
- `Esc` — global cascade (close overlay, defocus input)

**Missing:**
- `?` — cheat sheet modal
- `Ctrl+Shift+P` — command palette
- `Ctrl+Shift+O` — pending operations
- `t` — template picker
- `Ctrl+K` — sidebar search focus (may be wired in-component)
- **Checklist-pane-focused bindings:** Tab (nest), Shift+Tab (un-nest), Enter (add item)
- **Context-menu keyboard:** Arrow keys (navigate), Enter (activate), Right (submenu), Mnemonic letters

---

## Category 9: Theme & Appearance — NEARLY COMPLETE

| Feature | Spec | Status | Notes |
|---------|------|--------|-------|
| **Theme picker dropdown** | `themes.md` | ✓ Complete | Three options (Midnight Glass, Default, Paper Light) in Settings → Appearance |
| **Immediate re-theme** | `themes.md` | ✓ Complete | Synchronous; no flash |
| **Persistence** | `themes.md` §"Persistence boundary" | ⚠ Partial | localStorage only (deferred server-sync per TODO.md) |
| **OS fallback** | `themes.md` | ✓ Implemented | light-scheme → Paper Light; dark → Midnight Glass |
| **Silent flip bug** | TODO.md "Theme picker silently flips" | ✗ Known issue | Boots evergreen, flickers to OS fallback without user action |
| **Mobile chrome color** | `themes.md` | ? Unclear | Meta tag for address bar color |

---

## Category 10: Quota & Cost Indicators — PARTIAL

| Feature | Spec Location | Status |
|---------|----------------|--------|
| Total cost in header | `chat.md` §"When user opens an existing chat" | ✓ Present |
| Context-window meter | `chat.md` | ✓ Present (ContextMeter.svelte) |
| Quota bars in new-session | `chat.md` §"When user creates a chat" | ⚠ Component exists; unclear if live |
| Per-message cost in Inspector | `chat.md` §"What a message turn looks like" | ⚠ Partial (routing badge present; token counts?) |
| Advisor-specific costs | `model-routing-v1-spec.md` | ⚠ Unclear |
| 7-day headroom in Usage tab | `model-routing-v1-spec.md` §10 | ✗ Unbuilt |

---

## Summary by Priority

### **MUST-HAVE for basic operation** — DONE ✓
- Core conversation rendering
- Checklist CRUD
- Settings
- Sidebar navigation
- Inspector basics

### **SHOULD-HAVE for good UX** — ~50% DONE
- Keyboard shortcuts (basics done; power-user missing)
- Context menus (structure done; some handlers missing)
- Modals (new-session done; others missing)
- Paired-chat indicator (component ready; need endpoint)

### **NICE-TO-HAVE for power users** — ~20% DONE
- Cheat sheet + command palette
- Advanced message actions (regenerate, split, fork)
- Pending operations
- Templates + cloning workflows

---

## Recommended Filing Order

1. **PairedChatIndicator wiring** — 1 endpoint + 2 mount sites
2. **Modal dialogs** — Model switch, message regenerate, message split
3. **"Ask for more detail" button** — Small UX win
4. **Keyboard power-user suite** — Cheat sheet, palette, pending ops
5. **Slash-command hints** — Composer autocomplete for `/advisor`, `/checkpoint`
6. **Template save + picker** — Session lifecycle feature
7. **Advanced message actions** — Message pin, hide from context, move, fork
8. **Vault search + redaction** — Nice-to-have
9. **Inspector Routing/Usage tabs completion** — Data pipeline dependent
10. **Theme server-sync** — Low-priority deferral

---

## Notes

- **Reference read**: No v0.17.x source consulted. All gaps identified from behavior spec discrepancies.
- **Backend blockers**: Paired-chat endpoint, message regenerate API, template CRUD routes may not exist. Verify per v1's route surface.
- **Test coverage**: The UI gaps have corresponding component / integration tests (per component test patterns in tree) that may be passing the stub/mock, exposing the incomplete wiring on visual inspection.
