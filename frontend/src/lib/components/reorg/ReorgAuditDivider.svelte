<script lang="ts">
  /**
   * ReorgAuditDivider — persistent inline boundary marker rendered in
   * the conversation after a successful move or split operation.
   *
   * Behavior anchor: ``docs/behavior/context-menus.md`` §"Message bubble"
   * — "After commit, the source conversation gains an inline
   * ReorgAuditDivider marking the boundary ('N messages moved/split/
   * merged to <target>') with the timestamp."
   *
   * The divider is rendered by Conversation.svelte after the turn
   * whose ``id`` matches ``entry.anchorMessageId``.
   */
  import type { ReorgAuditEntry } from "../../stores/reorg.svelte";

  interface Props {
    entry: ReorgAuditEntry;
  }

  const { entry }: Props = $props();

  const verbLabel = $derived(entry.kind === "split" ? "split" : "moved");

  const countLabel = $derived(
    entry.count === 1 ? "1 message" : `${entry.count} messages`,
  );

  const formattedTime = $derived(
    new Date(entry.timestamp).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    }),
  );

  const label = $derived(
    `${countLabel} ${verbLabel} to "${entry.targetSessionTitle}" at ${formattedTime}`,
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
    <span class="rad__count">{countLabel}</span>
    <span class="rad__verb">{verbLabel} to</span>
    <a
      href={`/sessions/${encodeURIComponent(entry.targetSessionId)}`}
      class="rad__target"
      data-testid="reorg-audit-divider-target-link"
    >
      {entry.targetSessionTitle}
    </a>
    <span class="rad__time" data-testid="reorg-audit-divider-time">{formattedTime}</span>
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
</style>
