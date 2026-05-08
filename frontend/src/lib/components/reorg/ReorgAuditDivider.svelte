<script lang="ts">
  /**
   * ReorgAuditDivider — persistent inline boundary marker rendered in
   * the conversation after a successful move, split, or merge operation.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §"Message bubble"
   * — "After commit, the source conversation gains an inline
   * ReorgAuditDivider marking the boundary ('N messages moved/split/
   * merged to <target>') with the timestamp."
   *
   * For ``kind === "merge"`` entries loaded from the server the divider
   * also renders an inline **Undo** button.  The parent passes an
   * ``onUndo`` callback; when absent the button is hidden.
   *
   * The divider is rendered by Conversation.svelte after the turn
   * whose ``id`` matches ``entry.anchorMessageId``.
   */
  import type { ReorgAuditEntry } from "../../stores/reorg.svelte";
  import { formatAbsolute } from "../../utils/datetime";

  interface Props {
    entry: ReorgAuditEntry;
    /** Called when the user clicks Undo on a merge divider. */
    onUndo?: () => void;
  }

  const { entry, onUndo }: Props = $props();

  const isMerge = $derived(entry.kind === "merge");

  const verbLabel = $derived(
    entry.kind === "split" ? "split" : entry.kind === "merge" ? "merged from" : "moved",
  );

  // For merge entries the count field is 0 (unknown from audit row alone);
  // suppress the count label in that case.
  const countLabel = $derived(
    isMerge ? "" : entry.count === 1 ? "1 message" : `${entry.count} messages`,
  );

  const formattedTime = $derived(
    formatAbsolute(entry.timestamp, {
      hour: "2-digit",
      minute: "2-digit",
    }),
  );

  const label = $derived(
    isMerge
      ? `Merged from "${entry.targetSessionTitle}" at ${formattedTime}`
      : `${countLabel} ${verbLabel} to "${entry.targetSessionTitle}" at ${formattedTime}`,
  );
</script>

<div
  class="rad"
  data-testid="reorg-audit-divider"
  data-anchor-id={entry.anchorMessageId}
  data-kind={entry.kind}
  role="separator"
  aria-label={label}
>
  <span class="rad__line" aria-hidden="true"></span>
  <span class="rad__label">
    {#if !isMerge}
      <span class="rad__count">{countLabel}</span>
    {/if}
    <span class="rad__verb">{verbLabel}</span>
    <a
      href={`/sessions/${encodeURIComponent(entry.targetSessionId)}`}
      class="rad__target"
      data-testid="reorg-audit-divider-target-link"
    >
      {entry.targetSessionTitle}
    </a>
    <span class="rad__time" data-testid="reorg-audit-divider-time">{formattedTime}</span>
    {#if onUndo !== undefined}
      <button
        class="rad__undo"
        data-testid="reorg-audit-divider-undo"
        onclick={onUndo}
        type="button">Undo</button
      >
    {/if}
  </span>
  <span class="rad__line" aria-hidden="true"></span>
</div>

<style>
  .rad {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.375rem 1rem;
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.6875rem;
    user-select: none;
  }

  .rad__line {
    flex: 1;
    height: 1px;
    background: rgb(var(--bearings-border));
    opacity: 0.6;
  }

  .rad__label {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
    white-space: nowrap;
  }

  .rad__count {
    font-weight: 500;
    color: rgb(var(--bearings-fg));
  }

  /* .rad__verb inherits muted color from parent .rad */

  .rad__target {
    color: rgb(var(--bearings-accent));
    text-decoration: none;
    font-weight: 500;
  }
  .rad__target:hover {
    text-decoration: underline;
  }

  .rad__time {
    opacity: 0.7;
    margin-left: 0.125rem;
  }

  .rad__undo {
    margin-left: 0.375rem;
    padding: 0 0.375rem;
    height: 1.25rem;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 3px;
    background: transparent;
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.625rem;
    font-weight: 500;
    cursor: pointer;
    line-height: 1;
    user-select: none;
  }
  .rad__undo:hover {
    background: rgb(var(--bearings-bg-hover, var(--bearings-border)));
    color: rgb(var(--bearings-fg));
  }
</style>
