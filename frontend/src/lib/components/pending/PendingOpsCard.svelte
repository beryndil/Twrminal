<script lang="ts">
  /**
   * Floating pending-operations card — anchored bottom-right of the
   * viewport, toggled by ``Ctrl+Shift+O``.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/keyboard-shortcuts.md`` §"Help" — ``Ctrl+Shift+O``
   *   toggles this card globally (fires even with focus in an input).
   * - Esc closes this card at priority 3 in the cascade (after context
   *   menu and command palette; before other overlays).
   * - Outside-click and the dedicated close button also dismiss.
   * - Each row shows name, description, live-ticking age and exposes a
   *   ``MENU_TARGET_PENDING_OPERATION`` context menu on right-click.
   *
   * The card does NOT fetch its own data — the caller passes the
   * ``workingDir`` of the active session and this component calls
   * :func:`refreshOps` on mount and whenever ``workingDir`` changes.
   * The pending store owns the server round-trip and the ``ops`` list.
   */
  import { onMount } from "svelte";

  import { PENDING_OPS_CARD_STRINGS } from "../../config";
  import {
    ESC_PRIORITY_PENDING_OPS_CARD,
    registerEscEntry,
  } from "../../keyboard/escCascade";
  import {
    closeCard,
    pendingOpsStore,
    refreshOps,
  } from "../../stores/pending.svelte";
  import PendingOpRow from "./PendingOpRow.svelte";

  interface Props {
    /** Working directory of the currently-selected session, or null. */
    workingDir: string | null;
  }

  const { workingDir }: Props = $props();

  // ---- Refresh on working-dir change -----------------------------------------

  $effect(() => {
    if (pendingOpsStore.open) {
      void refreshOps(workingDir);
    }
  });

  // ---- Esc cascade + outside-click -------------------------------------------

  onMount(() => {
    const unregister = registerEscEntry({
      priority: ESC_PRIORITY_PENDING_OPS_CARD,
      isOpen: () => pendingOpsStore.open,
      close: closeCard,
    });
    return unregister;
  });

  function handleBackdropClick(event: MouseEvent): void {
    // Only close when the click lands directly on the backdrop, not
    // bubbled from a child (the panel itself stops propagation).
    if (event.target === event.currentTarget) {
      closeCard();
    }
  }

  function handleBackdropKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      closeCard();
    }
  }

  // ---- Row actions -----------------------------------------------------------

  function handleResolve(name: string): void {
    // Optimistically remove from list; a real implementation would call
    // the backend CLI surface (POST /api/shell/exec with
    // "bearings pending resolve <name>") and re-refresh. For now the
    // store is updated client-side.
    pendingOpsStore.ops = pendingOpsStore.ops.filter((op) => op.name !== name);
  }

  function handleDismiss(name: string): void {
    pendingOpsStore.ops = pendingOpsStore.ops.filter((op) => op.name !== name);
  }
</script>

{#if pendingOpsStore.open}
  <!--
    Transparent full-viewport capture — handles outside-click dismiss.
    Not a backdrop (no dimming) per the spec: the card is floating, not
    a modal, so the user can still see and interact with the content
    behind it.
  -->
  <div
    class="fixed inset-0 z-40"
    data-testid="pending-ops-backdrop"
    role="presentation"
    onclick={handleBackdropClick}
    onkeydown={handleBackdropKeydown}
  ></div>

  <!-- Floating card -->
  <div
    class="fixed bottom-4 right-4 z-50 flex w-80 flex-col rounded-lg border border-border bg-surface-1 shadow-2xl"
    data-testid="pending-ops-card"
    role="dialog"
    aria-modal="false"
    aria-label={PENDING_OPS_CARD_STRINGS.cardAriaLabel}
  >
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-border px-3 py-2">
      <span class="text-xs font-semibold uppercase tracking-wide text-fg-muted">
        {PENDING_OPS_CARD_STRINGS.cardHeading}
      </span>
      <button
        type="button"
        class="rounded p-0.5 text-fg-muted hover:bg-surface-2 hover:text-fg"
        aria-label={PENDING_OPS_CARD_STRINGS.closeAriaLabel}
        data-testid="pending-ops-close-btn"
        onclick={closeCard}
      >
        <svg
          viewBox="0 0 24 24"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          aria-hidden="true"
        >
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>

    <!-- Body -->
    <div class="max-h-96 overflow-y-auto" data-testid="pending-ops-body">
      {#if pendingOpsStore.loading}
        <p class="px-3 py-3 text-xs text-fg-muted" data-testid="pending-ops-loading">
          {PENDING_OPS_CARD_STRINGS.loadingLabel}
        </p>
      {:else if pendingOpsStore.error !== null}
        <p class="px-3 py-3 text-xs text-red-400" data-testid="pending-ops-error">
          {PENDING_OPS_CARD_STRINGS.loadErrorLabel}
        </p>
      {:else if pendingOpsStore.ops.length === 0}
        <p class="px-3 py-3 text-xs text-fg-muted" data-testid="pending-ops-empty">
          {PENDING_OPS_CARD_STRINGS.emptyLabel}
        </p>
      {:else}
        <ul class="py-1" data-testid="pending-ops-list">
          {#each pendingOpsStore.ops as op (op.name)}
            <PendingOpRow
              {op}
              onResolve={handleResolve}
              onDismiss={handleDismiss}
            />
          {/each}
        </ul>
      {/if}
    </div>
  </div>
{/if}
