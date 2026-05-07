# Vault — observable behavior

The vault is a read-only browser over the user's on-disk planning markdown — `~/.claude/plans/*.md`, project `TODO.md` files, and any other locations the user has configured into the vault surface. It exists so the user does not have to terminal-hop to read these documents while a Bearings session is open. This document lists what the user observes; implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [context-menus](context-menus.md), [keyboard-shortcuts](keyboard-shortcuts.md).

## Vault entry types

The user sees two kinds of vault entries:

* **Plans** — `.md` files directly under any configured plan root (e.g. `~/.claude/plans/`). Plan roots are flat — sub-directories under a plan root are treated as archival and are not surfaced.
* **Todos** — `TODO.md` files matched by the configured glob set (e.g. `~/Projects/**/TODO.md`).

Both kinds carry: an absolute path, a slug (derived from the filename without extension), an optional title (the first `# heading` in the file body), an mtime, and a size. The list is bucketed by kind, sorted newest-first within each bucket.

## CRUD flow

The vault is **read-only**. The user can:

* **list** every vault-visible doc;
* **open** any one of them and read the full markdown body, rendered;
* **search** across the full set;
* **copy** content out of a doc into the active chat composer (see [context-menus](context-menus.md) → code-block / link actions surface inside the rendered body).

The user cannot create, edit, rename, or delete vault docs from inside Bearings. The TODO-discipline rule — "append the moment work is deferred" — would race a UI editor; the on-disk files are the source of truth for tools that live outside Bearings (the user's editor, git, agent sessions). The vault renders the latest on-disk content; if the user edits a file in their editor and re-opens it in the vault, the new content is visible.

## When the user opens the vault

The user opens the vault by clicking the **Vault** entry in the sidebar's primary nav rail (between Memories and Analytics). The link carries `data-testid="sidebar-nav-vault"`, `href="/vault"`, and `aria-label="Open vault (plans + TODOs)"`. SvelteKit navigates to the `/vault` route, which renders `VaultPanel`. On first open, the user sees:

* **Plans** section — every plan-root markdown, sorted most-recent-mtime first. Each row shows the title (or, when no `# heading` exists, the slug), the parent directory short name, and a relative mtime ("2 days ago").
* **Todos** section — every matched `TODO.md`, also sorted most-recent-mtime first, with the project directory name as the visible label.
* A **search** box at the top of the pane.
* An **empty state** when the configured roots / globs match nothing: "No plans found under `<configured roots>`. No TODO.md files match `<configured globs>`." The empty state names the configured paths so the user can tell whether the configuration or the filesystem is empty.

Selecting a row opens the doc in a reading panel to the right of the list (or as a full-pane takeover, depending on the user's app-shell configuration). The doc title becomes the panel header; the body renders as Markdown using the same renderer as the [chat](chat.md) conversation body, including the linkifier (clickable `https://`, `file://`, and resolved-path anchors).

## Search semantics

Typing in the search box runs a **case-insensitive substring** query over every vault doc. The query is treated as a literal string — typing `foo.bar` matches the literal `foo.bar`, not a regex. Results render as a flat list of hits, each showing:

* the source doc title and its kind (Plan / Todo);
* the line number;
* a snippet of the matching line (trimmed to a hard cap; long single-line entries wrap inside the snippet container).

Clicking a hit jumps to that doc and (when feasible) scrolls to the matching line. Result count has a hard cap; when the cap is reached the user sees a "showing first N — narrow your query for more" indicator. The query is not stored; refreshing the pane clears it.

## Paste-into-message behavior

The vault is wired to feed the active chat composer:

* **Drag** a vault row onto the conversation composer to paste the doc's title-as-Markdown-link (`[Title](file:///abs/path)`) into the composer at the cursor.
* **Right-click → Copy as Markdown link** in the vault row's [context menu](context-menus.md) puts the same link on the clipboard.
* **Right-click → Copy doc body** copies the full markdown body to the clipboard.
* **Selecting** text inside the rendered body and copying via the OS clipboard works the same way it does in the conversation panel.

Quoting the doc into a chat does not modify the source on disk.

## Redaction rendering

Vault docs may contain sensitive content (API tokens, secrets accidentally pasted into a TODO entry). The vault renderer:

* **Detects** common secret shapes (high-entropy strings adjacent to keywords like `key`, `token`, `secret`, `password`) and replaces the visible text with a `••••••••` mask plus a "Show" toggle. The mask is a render-time overlay; the underlying clipboard-copy paths still receive the literal text (so the user can paste it where they need it after consciously toggling Show).
* **Does not** transmit modifications back to disk. The on-disk file is unchanged regardless of toggle state.
* **Persists no toggle state.** Re-opening the doc renders it masked again.

Paths are never redacted; only credential-shaped tokens. The redaction is an interactive aid, not a security control: a determined reader can always view the underlying file directly.

## Tag association

Vault docs themselves are not tagged the way [chat](chat.md) sessions are. The user does not get to attach tags to a plan or TODO file. However:

* When the active chat session is in focus, the vault offers an "Open against this session" affordance that opens the doc in the reading panel and visually pins the chat session to its header — so right-clicking the open vault doc and "Paste into composer" targets that specific chat.
* When a vault doc's path appears inside a chat message body (e.g. the agent referenced `~/.claude/plans/foo.md`), the linkifier (see [chat](chat.md)) renders it as a clickable anchor. Clicking the anchor opens the doc in the vault pane in-place rather than spawning a new browser tab — so vault is the canonical reader for plans cited in conversation.

## Failure modes

* **Configured root missing.** Plan roots that don't exist on disk are silently dropped from the index — the user sees the rest of the vault, and the empty state appears only when *every* root is missing.
* **Read error on a single doc.** A doc the server can't read (permissions, deleted between scan and read) does not crash the index; the row is rendered with the metadata that was scannable and an inline "unable to read" badge appears in the reading panel when the user tries to open it.
* **Path outside the vault.** Attempts (e.g. via a hand-crafted URL) to open a path that is not in the current index are refused — the user sees "this path is outside the vault." Symlinks are resolved before the allowlist check, so a symlink trick into the vault still resolves to the real path and is gated correctly.
* **Search-cap reached.** The "showing first N" indicator is surfaced; the user is asked to narrow the query rather than the UI silently truncating with no signal.
* **Stale mtime.** The vault re-scans on every list request; mtimes always reflect the current filesystem state.

## What the vault does NOT do

* It does not run the agent against vault content.
* It does not edit, rename, or delete files.
* It does not surface non-`.md` content (the configured globs / plan-root walks restrict to markdown).
* It does not crawl recursively under plan roots — only the immediate `.md` children of each plan root are listed; nested directories are intentionally not browsable. (The TODO globs accept `**` recursion because that's how project trees are shaped.)
