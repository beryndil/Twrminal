<script lang="ts">
  /**
   * Notifications section — notify-on-complete toggle.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import { NOTIFICATION_STRINGS } from "$lib/config";
  import { getPreferences, patchPreferences } from "$lib/api/preferences";
  import {
    requestNotifyPermission,
    setNotifyOnComplete,
    supportsNotifications,
  } from "$lib/utils/notify";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  const { onsaveStatus }: Props = $props();

  let prefNotifyOnComplete = $state(false);
  let notifyError = $state<string | null>(null);

  const notifyUnsupported = $derived(!supportsNotifications());
  const notifyDenied = $derived(
    supportsNotifications() && typeof Notification !== "undefined"
      ? Notification.permission === "denied"
      : false,
  );

  $effect(() => {
    void loadPrefs();
  });

  async function loadPrefs(): Promise<void> {
    try {
      const prefs = await getPreferences();
      prefNotifyOnComplete = prefs.notify_on_complete;
      setNotifyOnComplete(prefs.notify_on_complete);
    } catch {
      // Non-fatal — leave toggle in default-off state.
    }
  }

  async function handleNotifyToggle(enabled: boolean): Promise<void> {
    notifyError = null;
    prefNotifyOnComplete = enabled;
    if (enabled) {
      const permission = await requestNotifyPermission();
      if (permission !== "granted") {
        prefNotifyOnComplete = false;
        notifyError = NOTIFICATION_STRINGS.permissionDeniedError;
        return;
      }
    }
    onsaveStatus?.({ state: "saving" });
    try {
      const updated = await patchPreferences({ notify_on_complete: enabled });
      prefNotifyOnComplete = updated.notify_on_complete;
      setNotifyOnComplete(updated.notify_on_complete);
      onsaveStatus?.({ state: "saved" });
    } catch (err) {
      prefNotifyOnComplete = !enabled;
      notifyError = err instanceof Error ? err.message : String(err);
      onsaveStatus?.({ state: "error", message: notifyError ?? undefined });
    }
  }
</script>

<section
  class="settings-page__group"
  aria-label="Notifications"
  data-testid="settings-notifications"
>
  <h2 class="settings-page__heading">{NOTIFICATION_STRINGS.heading}</h2>

  <label class="settings-notifications__row">
    <input
      type="checkbox"
      class="settings-notifications__checkbox"
      checked={prefNotifyOnComplete}
      disabled={notifyUnsupported || notifyDenied}
      onchange={(e) => {
        void handleNotifyToggle((e.target as HTMLInputElement).checked);
      }}
      data-testid="notify-toggle"
    />
    <span class="settings-defaults__label settings-notifications__label">
      {NOTIFICATION_STRINGS.toggleLabel}
    </span>
  </label>

  <p class="settings-notifications__description" data-testid="notify-description">
    {NOTIFICATION_STRINGS.toggleDescription}
  </p>

  {#if notifyUnsupported}
    <p class="settings-page__lede" data-testid="notify-unsupported">
      {NOTIFICATION_STRINGS.footnoteUnsupported}
    </p>
  {:else if notifyDenied}
    <p class="settings-page__lede" data-testid="notify-denied">
      {NOTIFICATION_STRINGS.footnoteDenied}
    </p>
  {/if}

  {#if notifyError !== null}
    <p class="settings-page__error" role="alert" data-testid="notify-error">
      {notifyError}
    </p>
  {/if}
</section>

<style>
  .settings-notifications__row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
  }
  .settings-notifications__checkbox {
    width: 1rem;
    height: 1rem;
    cursor: pointer;
  }
  .settings-notifications__checkbox:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .settings-notifications__label {
    cursor: pointer;
    text-transform: none;
    letter-spacing: normal;
    font-size: 0.8125rem;
    font-weight: 400;
    color: rgb(var(--bearings-fg-strong));
  }
  .settings-notifications__description {
    margin: 0.375rem 0 0;
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    line-height: 1.4;
  }
</style>
