<script lang="ts">
  /**
   * Chat composer — multi-line textarea + Send button.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"Composer & message submission" —
   *   Enter sends, Shift+Enter inserts a newline (mirrors the v0.17.x
   *   convention; sign-off decision 2026-05-01 in
   *   ``~/.claude/plans/unblocking-v1-dogfood.md``).
   * - ``docs/behavior/prompt-endpoint.md`` — submit POSTs to
   *   ``/api/sessions/{id}/prompt`` and awaits the 202 ack before
   *   clearing the draft. Failure modes (404 / 409 / 413 / 422 / 429)
   *   surface inline as the ``sendFailed`` notice; the textarea retains
   *   its draft so the user can retry without retyping.
   * - Item 2.3 slash-command palette — typing ``/`` at the start of the
   *   draft opens the :component:`CommandMenu` typeahead; arrow keys +
   *   Tab/Enter select; Escape dismisses.
   * - Item 2.5 composer essentials — auto-grow textarea; Up/Down history
   *   walk through prior user messages; per-session draft persistence in
   *   ``localStorage`` via :mod:`lib/composer/draftStore.svelte`.
   *
   * The component is presentational: it owns its own draft state +
   * inflight flag, calls :func:`sendPrompt` directly, and reports
   * nothing back to its parent. The conversation pane picks the new
   * user turn up via the existing per-session WebSocket subscription —
   * there is no event-bus contract to honor.
   */
  import { ApiError } from "../../api/client";
  import { sendPrompt } from "../../api/prompt";
  import { COMPOSER_STRINGS, PROMPT_CONTENT_MAX_CHARS } from "../../config";
  import { clearDraft, loadDraft, saveDraft } from "../../composer/draftStore.svelte";
  import { InputHistory } from "../../composer/inputHistory";
  import CommandMenu from "./CommandMenu.svelte";

  interface Props {
    /** Active chat session id; the composer submits prompts against this row. */
    sessionId: string;
    /**
     * If true, the composer renders read-only with the closed-session
     * hint instead of the textarea. The default is ``false`` — callers
     * that already have the session row in hand pass ``closed_at !==
     * null`` so we don't have to re-fetch.
     */
    disabled?: boolean;
  }

  const { sessionId, disabled = false }: Props = $props();

  let draft = $state("");
  let inflight = $state(false);
  let errorMessage = $state<string | null>(null);
  let textareaEl = $state<HTMLTextAreaElement | null>(null);
  // Ref to the CommandMenu component instance for keyboard delegation.
  let menuRef = $state<CommandMenu | null>(null);

  // In-memory history ring for Up/Down navigation (per page-load, not
  // cross-session — see inputHistory.ts for the design rationale).
  const history = new InputHistory();

  const overCap = $derived(draft.length > PROMPT_CONTENT_MAX_CHARS);
  const trimmed = $derived(draft.trim());
  const canSend = $derived(!disabled && !inflight && !overCap && trimmed.length > 0);

  // ---------------------------------------------------------------------------
  // Draft persistence (item 2.5)
  //
  // Load the persisted draft whenever ``sessionId`` changes (including the
  // initial mount). The history walker is also reset on session switch —
  // the in-memory ring is per-page-load and should not bleed across sessions.
  // ---------------------------------------------------------------------------

  $effect(() => {
    draft = loadDraft(sessionId);
    history.reset();
  });

  // Persist every draft change. ``saveDraft`` removes the key on empty
  // string, so a successful send (draft = "") tidies storage automatically.
  $effect(() => {
    saveDraft(sessionId, draft);
  });

  // ---------------------------------------------------------------------------
  // Auto-grow textarea (item 2.5)
  //
  // Resets height to ``auto`` so the scrollHeight measurement reflects the
  // true content height (not the previous explicit pixel value), then sets
  // it to scrollHeight. Capped at ``max-h-64`` (16 rem) via CSS; beyond
  // that the textarea scrolls instead of expanding.
  // ---------------------------------------------------------------------------

  $effect(() => {
    // Reading ``draft`` here registers it as a dependency so the effect
    // re-runs on every keystroke. ``textareaEl`` is also tracked.
    draft;
    if (textareaEl !== null) {
      textareaEl.style.height = "auto";
      textareaEl.style.height = `${textareaEl.scrollHeight}px`;
    }
  });

  // ---------------------------------------------------------------------------
  // Slash-command palette logic (item 2.3)
  //
  // The menu is active when the draft starts with ``/`` (leading whitespace
  // is ignored).  The query is the text between the ``/`` and the first
  // whitespace or newline — this matches the "single-word at start"
  // convention used by Slack / Discord.
  // ---------------------------------------------------------------------------

  /**
   * True when the draft starts with ``/`` AND the command token has not
   * yet been followed by a space/newline.  A trailing space means the
   * user has confirmed a selection and is now typing arguments — the
   * palette should be closed at that point.
   */
  const menuOpen = $derived.by(() => {
    if (disabled) return false;
    const t = draft.trimStart();
    if (!t.startsWith("/")) return false;
    // Once the first token after ``/`` contains whitespace the command
    // word is complete — close the menu.
    return !/\s/.test(t.slice(1));
  });

  /** The text typed after the leading ``/``, used to filter the list. */
  const menuQuery = $derived.by(() => {
    if (!menuOpen) return "";
    const afterSlash = draft.trimStart().slice(1);
    // Query is everything up to (but not including) the first whitespace.
    const spaceIdx = afterSlash.search(/\s/);
    return spaceIdx === -1 ? afterSlash : afterSlash.slice(0, spaceIdx);
  });

  /**
   * Called by :component:`CommandMenu` when the user confirms a command.
   *
   * Replaces the ``/<query>`` prefix with ``/<name> `` and moves focus
   * back to the textarea so the user can continue typing the rest of the
   * prompt after the command.
   */
  function handleCommandSelect(insertion: string): void {
    // Find where the ``/`` appears and splice in the selected name.
    const slashPos = draft.indexOf("/");
    if (slashPos === -1) {
      draft = insertion + " ";
    } else {
      // Replace from the slash up to the end of the current word
      // (first whitespace after the slash, or end of string).
      const afterSlash = draft.slice(slashPos + 1);
      const spaceIdx = afterSlash.search(/\s/);
      const endOfWord = spaceIdx === -1 ? draft.length : slashPos + 1 + spaceIdx;
      draft = draft.slice(0, slashPos) + insertion + " " + draft.slice(endOfWord);
    }
    textareaEl?.focus();
  }

  function handleCommandClose(): void {
    // Remove the leading slash so the menu closes, leaving the rest of
    // the draft intact (user may have been exploring before deciding).
    const slashPos = draft.indexOf("/");
    if (slashPos !== -1) {
      draft = draft.slice(0, slashPos) + draft.slice(slashPos + 1);
    }
    textareaEl?.focus();
  }

  // ---------------------------------------------------------------------------
  // Submit + keydown
  // ---------------------------------------------------------------------------

  async function submit(): Promise<void> {
    if (!canSend) return;
    inflight = true;
    errorMessage = null;
    const payload = draft;
    try {
      await sendPrompt(sessionId, payload);
      // Record before clearing — push deduplicates consecutive identical sends.
      history.push(payload);
      draft = "";
      // ``saveDraft`` effect fires on ``draft = ""`` and removes the key,
      // but call ``clearDraft`` explicitly here as a belt-and-braces guard
      // in case the effect batches after a potential component unmount.
      clearDraft(sessionId);
      // Refocus so a quick "send + keep typing" loop stays on the
      // keyboard. The textarea reference may be ``null`` if the parent
      // unmounts the composer mid-send — guarded.
      textareaEl?.focus();
    } catch (error) {
      const detail =
        error instanceof ApiError
          ? (extractDetail(error.body) ?? COMPOSER_STRINGS.sendFailed)
          : COMPOSER_STRINGS.sendFailed;
      errorMessage = detail;
    } finally {
      inflight = false;
    }
  }

  function handleKeydown(event: KeyboardEvent): void {
    // When the command palette is open, delegate navigation + confirm
    // keys to the menu.  The menu's handleKey returns true when it
    // consumed the event, so we stop here.
    if (menuOpen && menuRef !== null) {
      if (menuRef.handleKey(event)) return;
    }

    // ---------------------------------------------------------------------------
    // History walk (item 2.5)
    //
    // ArrowUp when the cursor is at the very start of the textarea walks back
    // through sent messages (oldest-first).  ArrowDown when the cursor is at
    // the very end (and we're already in history mode) walks forward.  Modified
    // arrow keys (Shift/Ctrl/Alt/Meta) are left for the browser / OS.
    // ---------------------------------------------------------------------------
    if (!event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey) {
      if (event.key === "ArrowUp" && textareaEl !== null) {
        if (textareaEl.selectionStart === 0 && textareaEl.selectionEnd === 0) {
          const previous = history.up(draft);
          if (previous !== null) {
            event.preventDefault();
            draft = previous;
            // Move cursor to end after Svelte flushes the DOM update.
            requestAnimationFrame(() => {
              if (textareaEl !== null) {
                textareaEl.setSelectionRange(textareaEl.value.length, textareaEl.value.length);
              }
            });
            return;
          }
        }
      }

      if (event.key === "ArrowDown" && history.inHistory && textareaEl !== null) {
        if (textareaEl.selectionStart === textareaEl.value.length) {
          event.preventDefault();
          draft = history.down();
          requestAnimationFrame(() => {
            if (textareaEl !== null) {
              textareaEl.setSelectionRange(textareaEl.value.length, textareaEl.value.length);
            }
          });
          return;
        }
      }
    }

    // Enter without modifiers submits; Shift+Enter inserts a newline
    // (browser default). Ctrl/Alt/Meta + Enter falls through to the
    // browser default — the OS-keybind layer (Hyprland, etc.) might be
    // intercepting for window-manager work.
    if (event.key !== "Enter") return;
    if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
    event.preventDefault();
    void submit();
  }

  function extractDetail(body: unknown): string | null {
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
    return null;
  }

  function handleDragOver(event: DragEvent): void {
    // Allow drops by preventing the default behavior
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
  }

  function handleDrop(event: DragEvent): void {
    // Insert the dragged text (e.g. markdown link from vault row) into the textarea
    event.preventDefault();
    if (event.dataTransfer === null || textareaEl === null) return;
    const text = event.dataTransfer.getData("text/plain");
    if (!text) return;
    // Insert at cursor position
    const start = textareaEl.selectionStart;
    const end = textareaEl.selectionEnd;
    const before = draft.slice(0, start);
    const after = draft.slice(end);
    draft = before + text + after;
    // Move cursor after the inserted text
    textareaEl.focus();
    requestAnimationFrame(() => {
      if (textareaEl !== null) {
        const newCursorPos = start + text.length;
        textareaEl.setSelectionRange(newCursorPos, newCursorPos);
      }
    });
  }
</script>

<div class="composer relative flex flex-col gap-1" data-testid="composer">
  {#if disabled}
    <p class="px-1 text-xs text-fg-muted" data-testid="composer-disabled-hint">
      {COMPOSER_STRINGS.sessionClosedHint}
    </p>
  {:else}
    {#if menuOpen}
      <CommandMenu
        bind:this={menuRef}
        query={menuQuery}
        onselect={handleCommandSelect}
        onclose={handleCommandClose}
      />
    {/if}
    <textarea
      bind:this={textareaEl}
      bind:value={draft}
      class="composer__textarea min-h-12 max-h-64 overflow-y-hidden resize-none rounded border border-border bg-surface-0 px-2 py-1 text-sm text-fg-strong focus:border-accent focus:outline-none disabled:opacity-60"
      data-testid="composer-textarea"
      aria-label={COMPOSER_STRINGS.textareaAriaLabel}
      placeholder={COMPOSER_STRINGS.textareaPlaceholder}
      rows="2"
      maxlength={PROMPT_CONTENT_MAX_CHARS}
      disabled={inflight}
      onkeydown={handleKeydown}
      ondragover={handleDragOver}
      ondrop={handleDrop}
    ></textarea>
    <div class="flex items-center justify-between">
      {#if errorMessage !== null}
        <p class="text-xs text-red-400" data-testid="composer-error">{errorMessage}</p>
      {:else if inflight}
        <p class="text-xs text-fg-muted" data-testid="composer-sending">
          {COMPOSER_STRINGS.sending}
        </p>
      {:else}
        <span></span>
      {/if}
      <button
        type="button"
        class="rounded bg-accent px-3 py-1 text-xs text-fg-strong transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
        data-testid="composer-send"
        aria-label={COMPOSER_STRINGS.sendButtonAriaLabel}
        disabled={!canSend}
        onclick={submit}
      >
        {COMPOSER_STRINGS.sendButtonLabel}
      </button>
    </div>
  {/if}
</div>
