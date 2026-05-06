<script lang="ts">
  /**
   * Pending-operations badge — shown in the sidebar header when the
   * active project has at least one pending operation.
   *
   * Behavior anchors:
   *
   * - Badge is hidden when ``pendingOpsStore.ops.length === 0``.
   * - Clicking toggles the floating :mod:`PendingOpsCard`.
   * - The count reflects ``pendingOpsStore.ops.length`` reactively.
   *
   * The badge is a small pill rendered next to the sidebar heading.
   * It is NOT an ARIA live region — the count change is a visual
   * affordance, not an announcement (pending ops are background
   * state, not urgent notifications).
   */
  import { PENDING_OPS_CARD_STRINGS } from "../../config";
  import { pendingOpsStore, toggleCard } from "../../stores/pending.svelte";

  const count = $derived(pendingOpsStore.ops.length);
</script>

{#if count > 0}
  <button
    type="button"
    class="pending-ops-badge ml-auto flex items-center rounded-full bg-accent/20 px-1.5 py-0.5 font-mono text-xs font-medium text-accent hover:bg-accent/30"
    aria-label={PENDING_OPS_CARD_STRINGS.badgeAriaLabel(count)}
    data-testid="pending-ops-badge"
    onclick={toggleCard}
  >
    {count}
  </button>
{/if}
