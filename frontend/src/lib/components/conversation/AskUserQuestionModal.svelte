<script lang="ts">
  /**
   * AskUserQuestion modal — shown when the agent calls the built-in
   * ``AskUserQuestion`` tool to pause and wait for user input (Slice A4).
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"Approval modal".
   *
   * Unlike the generic :component:`ApprovalModal` (Allow / Deny), this
   * variant presents a text input. On submit it POSTs ``{ approved:
   * true, answer: <text> }`` to the approval endpoint; the backend
   * threads the answer back to the SDK callback as
   * ``PermissionResultAllow.updated_input`` so the agent receives the
   * text as the ``AskUserQuestion`` tool result.
   *
   * The question text is extracted from the JSON-encoded ``tool_input_json``
   * field of the ``approval_request`` event under the ``"question"`` key.
   * If parsing fails or the key is absent the raw JSON is shown.
   */
  import { onMount } from "svelte";

  import { APPROVAL_STRINGS } from "../../config";
  import { postApproval } from "../../api/approvals";
  import type { PendingApproval } from "../../stores/conversation.svelte";

  interface Props {
    sessionId: string;
    approval: PendingApproval;
  }

  const { sessionId, approval }: Props = $props();

  let answer = $state("");
  let submitting = $state(false);
  let error = $state<string | null>(null);

  /** Extract the ``question`` field from the tool input JSON. */
  function parseQuestion(raw: string): string {
    try {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      if (typeof parsed["question"] === "string") {
        return parsed["question"];
      }
    } catch {
      // fall through
    }
    return raw;
  }

  const question = $derived(parseQuestion(approval.toolInputJson));

  let answerEl: HTMLTextAreaElement | null = $state(null);

  onMount(() => {
    answerEl?.focus();
  });

  async function submit(): Promise<void> {
    if (submitting || answer.trim() === "") return;
    submitting = true;
    error = null;
    try {
      await postApproval(sessionId, approval.requestId, true, answer.trim());
      // Modal stays visible until the approval_resolved event arrives
      // via the WebSocket and clears pendingApproval in the store.
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      submitting = false;
    }
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }
</script>

<!-- Backdrop -->
<div
  class="ask-modal__backdrop fixed inset-0 z-40 flex items-center justify-center bg-black/50"
  aria-modal="true"
  role="dialog"
  aria-label={APPROVAL_STRINGS.askDialogAriaLabel}
  data-testid="ask-user-question-modal"
>
  <div
    class="ask-modal__panel relative flex w-full max-w-lg flex-col rounded-lg bg-surface-1 shadow-xl"
  >
    <!-- Header -->
    <div class="flex items-center border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold text-fg-strong" data-testid="ask-modal-title">
        {APPROVAL_STRINGS.askDialogTitle}
      </h2>
    </div>

    <!-- Question -->
    <div class="px-4 py-3 text-sm">
      <p class="text-fg-strong" data-testid="ask-modal-question">{question}</p>
    </div>

    <!-- Answer input -->
    <div class="px-4 pb-3 text-sm">
      <label class="block font-medium text-fg-muted" for="ask-answer">
        {APPROVAL_STRINGS.answerLabel}
      </label>
      <textarea
        id="ask-answer"
        class="mt-1 w-full rounded border border-border bg-surface-2 px-3 py-2 text-sm text-fg-strong placeholder:text-fg-muted focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
        rows={3}
        placeholder={APPROVAL_STRINGS.answerPlaceholder}
        disabled={submitting}
        bind:value={answer}
        bind:this={answerEl}
        onkeydown={handleKeydown}
        data-testid="ask-modal-answer"
      ></textarea>

      {#if error !== null}
        <p class="mt-1 text-xs text-red-400" data-testid="ask-modal-error">{error}</p>
      {/if}
    </div>

    <!-- Footer -->
    <div class="flex justify-end border-t border-border px-4 py-3">
      <button
        type="button"
        class="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        disabled={submitting || answer.trim() === ""}
        data-testid="ask-modal-submit"
        onclick={submit}
      >
        {APPROVAL_STRINGS.submitLabel}
      </button>
    </div>
  </div>
</div>
