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

  const overCap = $derived(draft.length > PROMPT_CONTENT_MAX_CHARS);
  const trimmed = $derived(draft.trim());
  const canSend = $derived(!disabled && !inflight && !overCap && trimmed.length > 0);

  async function submit(): Promise<void> {
    if (!canSend) return;
    inflight = true;
    errorMessage = null;
    const payload = draft;
    try {
      await sendPrompt(sessionId, payload);
      draft = "";
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
</script>

<div class="composer flex flex-col gap-1" data-testid="composer">
  {#if disabled}
    <p class="px-1 text-xs text-fg-muted" data-testid="composer-disabled-hint">
      {COMPOSER_STRINGS.sessionClosedHint}
    </p>
  {:else}
    <textarea
      bind:this={textareaEl}
      bind:value={draft}
      class="composer__textarea min-h-12 resize-y rounded border border-border bg-surface-0 px-2 py-1 text-sm text-fg-strong focus:border-accent focus:outline-none disabled:opacity-60"
      data-testid="composer-textarea"
      aria-label={COMPOSER_STRINGS.textareaAriaLabel}
      placeholder={COMPOSER_STRINGS.textareaPlaceholder}
      rows="2"
      maxlength={PROMPT_CONTENT_MAX_CHARS}
      disabled={inflight}
      onkeydown={handleKeydown}
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
