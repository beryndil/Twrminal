<script lang="ts">
  /**
   * Transient error toast for shell-operation failures.
   *
   * Rendered as a ``position: fixed`` banner when
   * :data:`shellOpNotificationStore.message` is non-null.  The user
   * dismisses it by clicking the × button; it auto-dismisses after
   * :data:`SHELL_OP_NOTIFICATION_DURATION_MS`.
   *
   * Mounted once in ``+layout.svelte`` alongside
   * ``BackendStatusBanner``.
   *
   * Behavior anchor:
   * ``docs/behavior/context-menus.md`` §"Shell-open integration" —
   * failure modes.
   */
  import { SHELL_OP_NOTIFICATION_STRINGS } from "../../config";
  import {
    clearShellOpNotification,
    shellOpNotificationStore,
  } from "../../stores/shellOpNotification.svelte";

  const DISMISS_DELAY_MS = 6_000;

  let timer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    if (shellOpNotificationStore.message !== null) {
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(() => {
        clearShellOpNotification();
        timer = null;
      }, DISMISS_DELAY_MS);
    }
    return () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };
  });
</script>

{#if shellOpNotificationStore.message !== null}
  <div
    class="fixed bottom-16 left-1/2 z-[9999] flex -translate-x-1/2 items-center gap-2 rounded border border-red-500/40 bg-surface-1 px-3 py-2 shadow-lg"
    role="alert"
    data-testid="shell-op-notification"
  >
    <span class="text-sm text-red-400"
      >{SHELL_OP_NOTIFICATION_STRINGS.errorPrefix}{shellOpNotificationStore.message}</span
    >
    <button
      type="button"
      class="ml-1 rounded p-0.5 text-fg-muted hover:bg-surface-2 hover:text-fg"
      aria-label={SHELL_OP_NOTIFICATION_STRINGS.dismissAriaLabel}
      data-testid="shell-op-notification-dismiss"
      onclick={clearShellOpNotification}
    >
      ×
    </button>
  </div>
{/if}
