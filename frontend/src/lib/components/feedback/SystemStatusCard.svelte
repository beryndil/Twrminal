<script lang="ts">
  /**
   * Sidebar system-status card (gap-cycle-08-006).
   *
   * Observable behavior: ``docs/behavior/chat.md`` §"Sidebar
   * system-status card":
   *
   * - Card-shaped container pinned at the sidebar bottom, above the
   *   identity block (``UserIdentityBlock``).
   * - Two always-visible health rows:
   *   1. **Connection** — derived from ``wsConnectionStatus.state``.
   *      ``'open'`` → accent-green dot + "Connected".
   *      ``'closed'`` or ``'error'`` → rose dot + "Disconnected".
   *   2. **Claude** — reachability proxy derived from the same store.
   *      ``'open'`` → accent-green dot + "Reachable".
   *      ``'closed'`` or ``'error'`` → rose dot + "Unreachable".
   * - Intentionally redundant with the bottom ``StatusBar`` — the card
   *   answers "system OK?" within the sidebar viewport without requiring
   *   the user to scan the full-width status strip.
   *
   * Note on v17 parity: v17 exposed a "connecting" (amber) state from
   * ``agent.state``.  v18's ``wsConnectionStatus`` has no "connecting"
   * variant — the socket transitions directly from ``'closed'`` to
   * ``'open'``.  Amber is therefore unused in v18; the two-state
   * (green / rose) mapping is complete within the v18 model.
   *
   * Mounted once in ``+layout.svelte`` inside the sidebar ``<aside>``,
   * above the identity-block wrapper, with ``shrink-0`` so the session
   * list consumes remaining height.
   */
  import { SYSTEM_STATUS_CARD_STRINGS } from "../../config";
  import { wsConnectionStatus } from "../../stores/sessions.svelte";

  /** ``true`` while the sessions-broadcast WebSocket is ``'open'``. */
  const wsOpen: boolean = $derived(wsConnectionStatus.state === "open");
</script>

<div
  class="mx-2 mb-2 shrink-0 rounded-md border border-border bg-surface-2 px-3 py-2"
  role="status"
  aria-label={SYSTEM_STATUS_CARD_STRINGS.cardAriaLabel}
  data-testid="system-status-card"
>
  <!-- Connection row -->
  <div
    class="flex items-center justify-between gap-2 py-0.5"
    data-testid="system-status-connection-row"
  >
    <span class="text-xs text-fg-muted">{SYSTEM_STATUS_CARD_STRINGS.connectionRowLabel}</span>
    <span class="flex items-center gap-1.5">
      <span
        class="inline-block h-2 w-2 rounded-full"
        class:bg-accent={wsOpen}
        class:bg-rose-500={!wsOpen}
        aria-hidden="true"
        data-testid="system-status-connection-dot"
      ></span>
      <span class="text-xs font-medium" data-testid="system-status-connection-label">
        {wsOpen
          ? SYSTEM_STATUS_CARD_STRINGS.connectionConnected
          : SYSTEM_STATUS_CARD_STRINGS.connectionDisconnected}
      </span>
    </span>
  </div>

  <!-- Claude reachability row -->
  <div
    class="flex items-center justify-between gap-2 py-0.5"
    data-testid="system-status-claude-row"
  >
    <span class="text-xs text-fg-muted">{SYSTEM_STATUS_CARD_STRINGS.claudeRowLabel}</span>
    <span class="flex items-center gap-1.5">
      <span
        class="inline-block h-2 w-2 rounded-full"
        class:bg-accent={wsOpen}
        class:bg-rose-500={!wsOpen}
        aria-hidden="true"
        data-testid="system-status-claude-dot"
      ></span>
      <span class="text-xs font-medium" data-testid="system-status-claude-label">
        {wsOpen
          ? SYSTEM_STATUS_CARD_STRINGS.claudeReachable
          : SYSTEM_STATUS_CARD_STRINGS.claudeUnreachable}
      </span>
    </span>
  </div>
</div>
