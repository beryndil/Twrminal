<script lang="ts">
  /**
   * Bottom status strip (gap-cycle-01-018).
   *
   * Observable behavior: ``docs/behavior/chat.md`` §"App chrome"
   * "Status strip":
   *
   * - Spans the full app-shell width (sidebar + main + inspector).
   * - Always visible — persists when no session is selected.
   * - Shows: Bearings version (live from :mod:`stores/versionWatcher`),
   *   the active session's working directory (hidden when no session is
   *   selected), a recovery-armed dot, an auto-save dot, and a
   *   connection label.
   * - Recovery and auto-save dots are lit (accent) while the
   *   sessions-broadcast WebSocket is ``'open'``. They dim to slate
   *   when the socket is ``'closed'`` or ``'error'`` to signal
   *   "not currently armed".
   * - The working-dir slot is suppressed (hidden) when
   *   ``sessionId`` is ``null``.
   *
   * Mounted once in the root app-shell layout (``+layout.svelte``).
   * The layout positions this component in ``grid-row: 2`` spanning
   * all three columns via ``.app-shell__statusbar``.
   */
  import { STATUS_BAR_STRINGS } from "../../config";
  import { wsConnectionStatus } from "../../stores/sessions.svelte";
  import { versionWatcherStore } from "../../stores/versionWatcher.svelte";

  interface Props {
    /** Working directory of the currently active session, or ``null``. */
    workingDir: string | null;
    /**
     * ID of the currently active session, or ``null`` when no session
     * is selected. Controls whether the working-dir slot renders.
     */
    sessionId: string | null;
  }

  const { workingDir, sessionId }: Props = $props();

  /**
   * ``true`` while the sessions-broadcast WebSocket is ``'open'``.
   * Used to toggle between accent (armed) and slate (disarmed) for
   * the recovery and auto-save dots.
   */
  const wsOpen: boolean = $derived(wsConnectionStatus.state === "open");

  /** Human-readable connection label. */
  const connectionLabel: string = $derived(
    wsOpen ? STATUS_BAR_STRINGS.connectionConnected : STATUS_BAR_STRINGS.connectionDisconnected,
  );
</script>

<div
  class="flex h-full items-center gap-3 text-fg-muted"
  data-testid="status-bar-content"
  role="status"
  aria-label={STATUS_BAR_STRINGS.ariaLabel}
>
  <!-- Version -->
  <span data-testid="status-bar-version">{versionWatcherStore.version}</span>

  <!-- Working-dir slot — suppressed when no session is active -->
  {#if sessionId !== null && workingDir !== null}
    <span class="text-border" aria-hidden="true">·</span>
    <span class="max-w-64 truncate font-mono text-xs" data-testid="status-bar-workdir"
      >{workingDir}</span
    >
  {/if}

  <!-- Spacer -->
  <span class="flex-1" aria-hidden="true"></span>

  <!-- Recovery dot -->
  <span
    class="flex items-center gap-1"
    aria-label={STATUS_BAR_STRINGS.recoveryAriaLabel}
    data-testid="status-bar-recovery-dot"
  >
    <span
      class="inline-block h-1.5 w-1.5 rounded-full"
      class:bg-accent={wsOpen}
      class:bg-slate-500={!wsOpen}
      aria-hidden="true"
    ></span>
    <span class="sr-only">{STATUS_BAR_STRINGS.recoveryAriaLabel}</span>
  </span>

  <!-- Auto-save dot -->
  <span
    class="flex items-center gap-1"
    aria-label={STATUS_BAR_STRINGS.autoSaveAriaLabel}
    data-testid="status-bar-autosave-dot"
  >
    <span
      class="inline-block h-1.5 w-1.5 rounded-full"
      class:bg-accent={wsOpen}
      class:bg-slate-500={!wsOpen}
      aria-hidden="true"
    ></span>
    <span class="sr-only">{STATUS_BAR_STRINGS.autoSaveAriaLabel}</span>
  </span>

  <!-- Connection label -->
  <span data-testid="status-bar-connection">{connectionLabel}</span>
</div>
