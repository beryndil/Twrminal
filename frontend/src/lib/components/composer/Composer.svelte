<script lang="ts">
  /**
   * Chat composer — multi-line textarea + Send button + attachment chips.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/chat.md`` §"Composer & message submission" —
   *   Enter sends, Shift+Enter inserts a newline (mirrors the v0.17.x
   *   convention; sign-off decision 2026-05-01 in
   *   ``~/.claude/plans/unblocking-v1-dogfood.md``).
   * - ``docs/behavior/chat.md`` §"Composer — attachment ingestion" —
   *   dragging files onto the composer uploads each file via
   *   ``POST /api/uploads``, shows per-chip progress, blocks submit
   *   while uploads are in-flight, and includes the resolved upload ids
   *   in the prompt POST body (gap-cycle-03-001).
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
  import { createCheckpoint } from "../../api/checkpoints";
  import { sendPrompt } from "../../api/prompt";
  import { uploadFile } from "../../api/uploads";
  import {
    CHECKPOINT_GUTTER_STRINGS,
    COMPOSER_ATTACHMENT_STRINGS,
    COMPOSER_STRINGS,
    MENU_ACTION_ATTACHMENT_COPY_FILENAME,
    MENU_ACTION_ATTACHMENT_COPY_PATH,
    MENU_ACTION_ATTACHMENT_REMOVE,
    MENU_TARGET_ATTACHMENT,
    PROMPT_CONTENT_MAX_CHARS,
  } from "../../config";
  import { contextMenu } from "../../actions/contextMenu";
  import { clearDraft, loadDraft, saveDraft } from "../../composer/draftStore.svelte";
  import { InputHistory } from "../../composer/inputHistory";
  import { bumpCheckpointRefresh } from "../../stores/checkpointBus.svelte";
  import { conversationStore } from "../../stores/conversation.svelte";
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
    /**
     * Working directory of the active session. Forwarded to
     * :component:`CommandMenu` so its slash-command list is scoped to
     * this session's project commands (gap-cycle-13-005).
     */
    workingDir?: string | null;
  }

  const { sessionId, disabled = false, workingDir = null }: Props = $props();

  let draft = $state("");
  let inflight = $state(false);
  let errorMessage = $state<string | null>(null);
  let textareaEl = $state<HTMLTextAreaElement | null>(null);
  // Ref to the CommandMenu component instance for keyboard delegation.
  let menuRef = $state<CommandMenu | null>(null);

  // In-memory history ring for Up/Down navigation (per page-load, not
  // cross-session — see inputHistory.ts for the design rationale).
  const history = new InputHistory();

  // ---------------------------------------------------------------------------
  // Attachment chip state (gap-cycle-03-001)
  //
  // Each dropped file gets a PendingChip. The chip lives in state from
  // first drop through either successful prompt send (cleared in bulk)
  // or explicit removal (cleared individually). AbortControllers are
  // stored outside $state in a Map to avoid Svelte proxy interference
  // with the browser built-in.
  // ---------------------------------------------------------------------------

  /** Local discriminator for a pending composer attachment. */
  interface PendingChip {
    id: string;
    filename: string;
    status: "uploading" | "done" | "error";
    /** Server-assigned id once the upload resolves. */
    uploadId: number | null;
    /** Inline error text when ``status === "error"``. */
    errorMessage: string | null;
  }

  let pendingChips = $state<PendingChip[]>([]);

  /**
   * AbortControllers for in-flight uploads — keyed by chip id, outside
   * $state so Svelte's proxy doesn't wrap the browser built-in.
   */
  const chipAborts = new Map<string, AbortController>();

  function generateChipId(): string {
    return `chip-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  }

  const hasPendingUploads = $derived(pendingChips.some((c) => c.status === "uploading"));

  const overCap = $derived(draft.length > PROMPT_CONTENT_MAX_CHARS);
  const trimmed = $derived(draft.trim());
  /**
   * Submit gate:
   * - not disabled, not already sending, content within cap, non-empty
   * - no chips are still uploading (block until all settle, per behavior doc)
   */
  const canSend = $derived(
    !disabled && !inflight && !overCap && trimmed.length > 0 && !hasPendingUploads,
  );

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

  /**
   * Detect ``/advisor`` as the first token (G9). When matched, the
   * prompt is submitted normally but with ``force_advisor: true``
   * attached to the POST body so the SDK loop prepends the advisor-
   * override instruction to the content it sends to the executor.
   * The command token (and any trailing whitespace) is stripped before
   * submission so the executor sees only the user's actual message.
   *
   * Returns the content to submit (stripped), or ``null`` when the
   * token is not ``/advisor``.
   */
  function tryParseAdvisorCommand(value: string): { matched: true; content: string } | null {
    const t = value.trimStart();
    if (!t.startsWith("/advisor")) return null;
    const rest = t.slice("/advisor".length);
    if (rest.length > 0 && !/^\s/.test(rest)) {
      // ``/advisors`` or similar — not the same command.
      return null;
    }
    return { matched: true, content: rest.trim() };
  }

  /**
   * Detect ``/checkpoint`` as the first token. When matched, intercept
   * submit and POST a checkpoint instead of a prompt. The optional
   * argument is the label (everything after the command word and a
   * single space). G6 — ``docs/behavior/chat.md`` §"Slash commands in
   * the composer".
   */
  function tryParseCheckpointCommand(value: string): { matched: true; label: string } | null {
    const trimmed = value.trimStart();
    if (!trimmed.startsWith("/checkpoint")) return null;
    const rest = trimmed.slice("/checkpoint".length);
    if (rest.length > 0 && !/^\s/.test(rest)) {
      // ``/checkpointer`` or similar — not the same command.
      return null;
    }
    return { matched: true, label: rest.trim() };
  }

  async function handleCheckpointCommand(label: string): Promise<void> {
    // The anchor is the most recent message turn. If the conversation
    // is empty, surface an inline error and leave the draft intact so
    // the user can edit and retry.
    const turns = conversationStore.turns;
    if (turns.length === 0) {
      errorMessage = CHECKPOINT_GUTTER_STRINGS.createNoAnchor;
      return;
    }
    const anchor = turns[turns.length - 1];
    inflight = true;
    errorMessage = null;
    try {
      await createCheckpoint({
        sessionId,
        messageId: anchor.id,
        label: label.length > 0 ? label : undefined,
      });
      bumpCheckpointRefresh();
      draft = "";
      clearDraft(sessionId);
      textareaEl?.focus();
    } catch (error) {
      const detail =
        error instanceof ApiError
          ? (extractDetail(error.body) ?? CHECKPOINT_GUTTER_STRINGS.createFailed)
          : CHECKPOINT_GUTTER_STRINGS.createFailed;
      errorMessage = detail;
    } finally {
      inflight = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Attachment upload logic (gap-cycle-03-001)
  // ---------------------------------------------------------------------------

  /**
   * Kick off an upload for one dropped file. Creates a chip in
   * ``"uploading"`` state, fires ``POST /api/uploads``, then updates
   * the chip to ``"done"`` (with the server's upload id) or ``"error"``
   * (with the detail string).
   *
   * An ``AbortError`` thrown when the user clicks the chip's remove
   * button is silently swallowed — the chip is already gone from the
   * array at that point.
   */
  async function startFileUpload(file: File): Promise<void> {
    const chipId = generateChipId();
    const abort = new AbortController();
    chipAborts.set(chipId, abort);
    pendingChips = [
      ...pendingChips,
      {
        id: chipId,
        filename: file.name,
        status: "uploading",
        uploadId: null,
        errorMessage: null,
      },
    ];
    try {
      const result = await uploadFile(file, abort.signal);
      chipAborts.delete(chipId);
      pendingChips = pendingChips.map((c) =>
        c.id === chipId ? { ...c, status: "done" as const, uploadId: result.id } : c,
      );
    } catch (error) {
      chipAborts.delete(chipId);
      if (error instanceof Error && error.name === "AbortError") {
        // The chip was removed by removeChip() — nothing left to update.
        return;
      }
      const detail =
        error instanceof ApiError
          ? (extractDetail(error.body) ?? COMPOSER_ATTACHMENT_STRINGS.uploadFailed)
          : COMPOSER_ATTACHMENT_STRINGS.uploadFailed;
      pendingChips = pendingChips.map((c) =>
        c.id === chipId ? { ...c, status: "error" as const, errorMessage: detail } : c,
      );
    }
  }

  /**
   * Remove a chip by id. If the upload is still in-flight, the
   * associated ``AbortController`` is triggered first so the fetch is
   * cancelled. The chip disappears immediately from the UI regardless
   * of upload state.
   */
  function removeChip(chipId: string): void {
    chipAborts.get(chipId)?.abort();
    chipAborts.delete(chipId);
    pendingChips = pendingChips.filter((c) => c.id !== chipId);
  }

  async function submit(): Promise<void> {
    if (!canSend) return;
    const checkpointCmd = tryParseCheckpointCommand(draft);
    if (checkpointCmd !== null) {
      await handleCheckpointCommand(checkpointCmd.label);
      return;
    }
    // ``/advisor`` per-turn override (G9): strip the command token and
    // attach ``force_advisor: true`` to the POST body.
    const advisorCmd = tryParseAdvisorCommand(draft);
    const content = advisorCmd !== null ? advisorCmd.content : draft;
    const forceAdvisor = advisorCmd !== null;
    // Guard: if /advisor was the entire message and there is no body
    // after stripping, treat as empty — canSend already checks
    // ``trimmed.length > 0`` for the raw draft, but the stripped
    // content could become empty (e.g. the user typed only ``/advisor``
    // with no following text).
    if (content.trim().length === 0) return;
    inflight = true;
    errorMessage = null;
    const payload = content;
    // Collect resolved upload ids from done chips to pass along with
    // the prompt. The backend's PromptIn ignores the field today
    // (extra="ignore") — it is a forward-compatible placeholder.
    // See docs/behavior/chat.md §"Composer — attachment ingestion".
    const uploadIds = pendingChips
      .filter((c) => c.status === "done" && c.uploadId !== null)
      .map((c) => c.uploadId as number);
    try {
      await sendPrompt(sessionId, payload, { forceAdvisor, uploadIds });
      // Record before clearing — push deduplicates consecutive identical sends.
      history.push(payload);
      draft = "";
      // ``saveDraft`` effect fires on ``draft = ""`` and removes the key,
      // but call ``clearDraft`` explicitly here as a belt-and-braces guard
      // in case the effect batches after a potential component unmount.
      clearDraft(sessionId);
      // Clear all attachment chips on successful send.
      pendingChips = [];
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
    event.preventDefault();
    if (event.dataTransfer === null) return;

    // File drops take priority: upload each file as an attachment chip.
    // The text/plain branch below handles vault markdown-link drags
    // which arrive with no files in the transfer.
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) {
      for (const file of files) {
        void startFileUpload(file);
      }
      return;
    }

    // Fall through: insert dragged text (e.g. vault markdown link) at cursor.
    if (textareaEl === null) return;
    const text = event.dataTransfer.getData("text/plain");
    if (!text) return;
    const start = textareaEl.selectionStart;
    const end = textareaEl.selectionEnd;
    const before = draft.slice(0, start);
    const after = draft.slice(end);
    draft = before + text + after;
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
        {workingDir}
        onselect={handleCommandSelect}
        onclose={handleCommandClose}
      />
    {/if}
    {#if pendingChips.length > 0}
      <div
        class="flex flex-wrap gap-1 px-0.5"
        data-testid="composer-attachment-chips"
        aria-label={COMPOSER_ATTACHMENT_STRINGS.chipsAreaAriaLabel}
      >
        {#each pendingChips as chip (chip.id)}
          <span
            class="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs {chip.status === 'error' ? 'border-red-400 text-red-400' : 'border-border bg-surface-1 text-fg-muted'}"
            data-testid="composer-attachment-chip"
            data-chip-id={chip.id}
            data-chip-status={chip.status}
            use:contextMenu={{
              target: MENU_TARGET_ATTACHMENT,
              handlers: {
                [MENU_ACTION_ATTACHMENT_COPY_PATH]: () => {
                  void navigator.clipboard.writeText(chip.filename);
                },
                [MENU_ACTION_ATTACHMENT_COPY_FILENAME]: () => {
                  void navigator.clipboard.writeText(chip.filename);
                },
                [MENU_ACTION_ATTACHMENT_REMOVE]: {
                  handler: () => removeChip(chip.id),
                  confirmMessage: `Remove "${chip.filename}"?`,
                  confirmLabel: "Remove",
                },
              },
              data: { chipId: chip.id },
            }}
          >
            {#if chip.status === "uploading"}
              <span
                class="inline-block animate-spin"
                aria-label={COMPOSER_ATTACHMENT_STRINGS.uploadingAriaLabel}
                aria-hidden="false"
              >⟳</span>
            {/if}
            <span>{chip.filename}</span>
            {#if chip.status === "error" && chip.errorMessage !== null}
              <span class="ml-0.5" title={chip.errorMessage}>⚠</span>
            {/if}
            <button
              type="button"
              class="ml-0.5 opacity-60 hover:opacity-100"
              aria-label={COMPOSER_ATTACHMENT_STRINGS.removeChipAriaLabel(chip.filename)}
              data-testid="composer-chip-remove"
              onclick={() => removeChip(chip.id)}
            >×</button>
          </span>
        {/each}
      </div>
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
