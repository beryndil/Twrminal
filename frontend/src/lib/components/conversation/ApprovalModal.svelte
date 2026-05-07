<script lang="ts">
  /**
   * Tool-approval modal — shown when the agent calls a tool that
   * requires explicit user consent (``can_use_tool`` Slice A4).
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"Approval modal".
   *
   * The user clicks Allow or Deny; both choices POST to
   * ``/api/sessions/{id}/approvals/{request_id}``. The broker resolves
   * its future, which unblocks the SDK callback, and emits an
   * ``approval_resolved`` event over the WebSocket. Every subscribed
   * tab receives that event and clears its own modal (the
   * "second-tab closes first-tab modal" behaviour).
   *
   * ``AskUserQuestion`` tool calls are routed to
   * :component:`AskUserQuestionModal` by the parent
   * :component:`Conversation` before reaching this component.
   */
  import { onMount } from "svelte";

  import { APPROVAL_STRINGS } from "../../config";
  import { postApproval } from "../../api/approvals";
  import type { PendingApproval } from "../../stores/conversation.svelte";
  import { wsConnectionStatus } from "../../stores/sessions.svelte";

  interface Props {
    sessionId: string;
    approval: PendingApproval;
  }

  const { sessionId, approval }: Props = $props();

  let submitting = $state(false);
  let error = $state<string | null>(null);

  /**
   * Block Esc for the lifetime of this modal. A capture-phase listener
   * on window intercepts every Escape keypress before the Esc cascade,
   * command palette, cheat sheet, or any other handler sees it. The
   * intent: approval / denial is click-only — accidental Esc must not
   * resolve the gate. Mirrors v17 ApprovalModal behaviour.
   */
  onMount(() => {
    function blockEsc(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    window.addEventListener("keydown", blockEsc, true);
    return () => window.removeEventListener("keydown", blockEsc, true);
  });

  /** True only while the sessions-broadcast WebSocket is open. */
  const wsConnected = $derived(wsConnectionStatus.state === "open");

  /** Pretty-print the JSON input for display. Falls back to raw string. */
  function formatInput(raw: string): string {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }

  async function resolve(approved: boolean): Promise<void> {
    if (submitting || !wsConnected) return;
    submitting = true;
    error = null;
    try {
      await postApproval(sessionId, approval.requestId, approved);
      // Modal stays visible until the approval_resolved event arrives
      // via the WebSocket and clears pendingApproval in the store.
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      submitting = false;
    }
  }
</script>

<!-- Backdrop -->
<div
  class="approval-modal__backdrop fixed inset-0 z-40 flex items-center justify-center bg-black/50"
  aria-modal="true"
  role="dialog"
  aria-label={APPROVAL_STRINGS.dialogAriaLabel}
  data-testid="approval-modal"
>
  <div
    class="approval-modal__panel relative flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg bg-surface-1 shadow-xl"
  >
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold text-fg-strong" data-testid="approval-modal-title">
        {APPROVAL_STRINGS.dialogTitle}
      </h2>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-y-auto px-4 py-3 text-sm">
      <div class="mb-3">
        <span class="font-medium text-fg-muted">{APPROVAL_STRINGS.toolNameLabel}:</span>
        <span class="ml-2 font-mono text-fg-strong" data-testid="approval-tool-name">
          {approval.toolName}
        </span>
      </div>

      <div>
        <span class="font-medium text-fg-muted">{APPROVAL_STRINGS.toolInputLabel}:</span>
        <pre
          class="mt-1 max-h-48 overflow-y-auto rounded bg-surface-2 p-2 text-xs text-fg-strong"
          data-testid="approval-tool-input">{formatInput(approval.toolInputJson)}</pre>
      </div>

      {#if error !== null}
        <p class="mt-2 text-xs text-red-400" data-testid="approval-error">{error}</p>
      {/if}

      {#if !wsConnected}
        <p
          class="mt-2 rounded bg-amber-500/15 px-3 py-2 text-xs text-amber-400"
          data-testid="approval-reconnect-banner"
        >
          {APPROVAL_STRINGS.reconnectingBanner}
        </p>
      {/if}
    </div>

    <!-- Footer -->
    <div class="flex justify-end gap-2 border-t border-border px-4 py-3">
      <button
        type="button"
        class="rounded bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
        disabled={submitting || !wsConnected}
        data-testid="approval-deny"
        onclick={() => resolve(false)}
      >
        {APPROVAL_STRINGS.denyLabel}
      </button>
      <button
        type="button"
        class="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
        disabled={submitting || !wsConnected}
        data-testid="approval-allow"
        onclick={() => resolve(true)}
      >
        {APPROVAL_STRINGS.allowLabel}
      </button>
    </div>
  </div>
</div>
