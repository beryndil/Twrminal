<script lang="ts">
  /**
   * ReorgProposalEditor — LLM-assisted analyzer panel that proposes
   * conversation split boundaries before a manual reorg commit.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §"Message bubble"
   * — "ReorgProposalEditor is the LLM-assisted analyzer view that
   * suggests a multi-message reorg before commit."
   *
   * Opening: rendered by the conversation header or sidebar via the
   * ``open`` prop.  Calls ``analyzeReorg()`` from the reorg store to
   * produce heuristic proposals.  The user can accept (opens
   * ReorgPicker pre-filled at the proposed boundary) or dismiss
   * individual proposals.
   *
   * Note: ``analyzeReorg`` runs a client-side heuristic (time-gap +
   * chunk-boundary rules) rather than calling an LLM endpoint, as no
   * backend analyze endpoint is present in the OpenAPI spec.  The
   * component shape leaves room for a future backend endpoint without
   * requiring a component rewrite.
   */
  import { analyzeReorg, reorgStore, type ReorgProposal } from "../../stores/reorg.svelte";
  import { listMessages } from "../../api/messages";

  interface Props {
    /** Session to analyse. */
    sessionId: string;
    /** Whether the panel is visible. */
    open: boolean;
    /** Called when the user closes / dismisses the panel. */
    onclose: () => void;
  }

  const { sessionId, open, onclose }: Props = $props();

  // ---- Local state --------------------------------------------------------

  let proposals = $state<ReorgProposal[]>([]);
  let dismissed = $state<Set<string>>(new Set());
  let loading = $state(false);
  let analyzeError = $state<string | null>(null);

  // ---- Run analysis when panel opens -------------------------------------

  $effect(() => {
    if (!open) {
      // Reset when closed.
      proposals = [];
      dismissed = new Set();
      analyzeError = null;
      return;
    }
    loading = true;
    analyzeError = null;
    void analyzeReorg(sessionId)
      .then((results) => {
        proposals = results;
        loading = false;
      })
      .catch((err: unknown) => {
        analyzeError = err instanceof Error ? err.message : String(err);
        loading = false;
      });
  });

  // ---- Derived: active (non-dismissed) proposals -------------------------

  const activeProposals = $derived(proposals.filter((p) => !dismissed.has(p.messageId)));

  // ---- Helpers ------------------------------------------------------------

  /**
   * Accepting a proposal fetches the message's ``seq`` then opens the
   * ReorgPicker in split mode at that boundary.
   */
  async function handleAccept(proposal: ReorgProposal): Promise<void> {
    // Find the seq for this message from the full list.
    const page = await listMessages(sessionId);
    const msg = page.items.find((m) => m.id === proposal.messageId);
    if (!msg) return;

    reorgStore.openPicker({
      mode: "split",
      messageId: proposal.messageId,
      sourceSessionId: sessionId,
      seq: msg.seq,
    });
    onclose();
  }

  function handleDismiss(proposal: ReorgProposal): void {
    dismissed = new Set([...dismissed, proposal.messageId]);
  }

  function handleDismissAll(): void {
    dismissed = new Set(proposals.map((p) => p.messageId));
  }
</script>

{#if open}
  <div
    class="rpe"
    role="complementary"
    aria-label="Reorg proposal editor"
    data-testid="reorg-proposal-editor"
  >
    <!-- Header -->
    <div class="rpe__header">
      <span class="rpe__title">Suggested split boundaries</span>
      <button
        type="button"
        class="rpe__close"
        onclick={onclose}
        aria-label="Close proposal editor"
        data-testid="rpe-close"
      >
        ✕
      </button>
    </div>

    <!-- Body -->
    <div class="rpe__body">
      {#if loading}
        <p class="rpe__hint" data-testid="rpe-loading">Analysing conversation…</p>
      {:else if analyzeError !== null}
        <p class="rpe__error" role="alert" data-testid="rpe-error">{analyzeError}</p>
      {:else if activeProposals.length === 0}
        <p class="rpe__hint" data-testid="rpe-empty">
          {proposals.length === 0
            ? "No split boundaries detected."
            : "All proposals dismissed."}
        </p>
      {:else}
        <ul class="rpe__list" data-testid="rpe-proposal-list">
          {#each activeProposals as proposal (proposal.messageId)}
            <li class="rpe__row" data-testid={`rpe-proposal-${proposal.messageId}`}>
              <div class="rpe__reason">{proposal.reason}</div>
              <div class="rpe__actions">
                <button
                  type="button"
                  class="rpe__btn rpe__btn--accept"
                  onclick={() => void handleAccept(proposal)}
                  data-testid={`rpe-accept-${proposal.messageId}`}
                >
                  Split here
                </button>
                <button
                  type="button"
                  class="rpe__btn rpe__btn--dismiss"
                  onclick={() => handleDismiss(proposal)}
                  data-testid={`rpe-dismiss-${proposal.messageId}`}
                >
                  Dismiss
                </button>
              </div>
            </li>
          {/each}
        </ul>

        {#if activeProposals.length > 1}
          <button
            type="button"
            class="rpe__dismiss-all"
            onclick={handleDismissAll}
            data-testid="rpe-dismiss-all"
          >
            Dismiss all
          </button>
        {/if}
      {/if}
    </div>
  </div>
{/if}

<style>
  .rpe {
    display: flex;
    flex-direction: column;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    background: rgb(var(--bearings-surface-1, var(--bearings-surface-2)));
    font-size: 0.8125rem;
    overflow: hidden;
  }

  .rpe__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }

  .rpe__title {
    font-size: 0.8125rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg));
  }

  .rpe__close {
    background: none;
    border: none;
    cursor: pointer;
    color: rgb(var(--bearings-fg-muted));
    padding: 0.125rem 0.25rem;
    font-size: 0.8125rem;
    line-height: 1;
    border-radius: 0.2rem;
  }
  .rpe__close:hover {
    color: rgb(var(--bearings-fg));
    background: rgb(var(--bearings-surface-2));
  }

  .rpe__body {
    flex: 1;
    overflow-y: auto;
  }

  .rpe__hint {
    margin: 0;
    padding: 0.625rem 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.8125rem;
  }

  .rpe__error {
    margin: 0;
    padding: 0.625rem 0.75rem;
    color: #f87171;
    font-size: 0.8125rem;
  }

  .rpe__list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .rpe__row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid rgb(var(--bearings-border) / 0.5);
  }
  .rpe__row:last-child {
    border-bottom: none;
  }

  .rpe__reason {
    flex: 1;
    color: rgb(var(--bearings-fg));
    font-size: 0.75rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rpe__actions {
    display: flex;
    gap: 0.25rem;
    flex-shrink: 0;
  }

  .rpe__btn {
    background: none;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    cursor: pointer;
    font: inherit;
    font-size: 0.6875rem;
    padding: 0.1875rem 0.5rem;
    color: inherit;
  }

  .rpe__btn--accept {
    color: rgb(var(--bearings-accent));
    border-color: rgb(var(--bearings-accent) / 0.5);
    font-weight: 500;
  }
  .rpe__btn--accept:hover {
    background: rgb(var(--bearings-accent) / 0.1);
  }

  .rpe__btn--dismiss {
    color: rgb(var(--bearings-fg-muted));
  }
  .rpe__btn--dismiss:hover {
    background: rgb(var(--bearings-surface-2));
  }

  .rpe__dismiss-all {
    display: block;
    width: 100%;
    background: none;
    border: none;
    border-top: 1px solid rgb(var(--bearings-border) / 0.5);
    padding: 0.375rem 0.75rem;
    font: inherit;
    font-size: 0.6875rem;
    color: rgb(var(--bearings-fg-muted));
    cursor: pointer;
    text-align: center;
  }
  .rpe__dismiss-all:hover {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg));
  }
</style>
