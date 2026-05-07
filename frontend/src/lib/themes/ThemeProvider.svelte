<script lang="ts">
  /**
   * Theme provider — wires the runtime store to the DOM:
   *
   * - Applies the boot-resolved theme on mount (corrects any drift the
   *   no-flash boot script in :file:`src/app.html` left behind, per
   *   ``docs/behavior/themes.md`` §"What gets re-themed live").
   * - Listens to the browser-native ``storage`` event so a theme
   *   change in another tab re-tints this tab on the next render.
   * - Surfaces a toast when a persistence write fails per the doc's
   *   §"Failure modes".
   *
   * The provider renders its ``children`` slot unchanged — it is a
   * cross-cutting concern that wraps the app shell, like a context
   * provider in React parlance.
   */
  import type { Snippet } from "svelte";
  import { onMount } from "svelte";

  import { THEME_COLOR_HEX, THEME_META_NAME, THEME_STORAGE_KEY, THEME_STRINGS } from "../config";
  import { applyThemeToDom } from "./dom";
  import { acknowledgeSaveStatus, syncFromStorage, themeStore } from "./store.svelte";

  interface Props {
    children?: Snippet;
  }

  const { children }: Props = $props();

  /**
   * Cross-tab sync — the browser fires a ``storage`` event on every
   * tab *except* the writing one when localStorage changes. We
   * listen for our key and re-read the persisted value so two open
   * tabs stay in lockstep per the doc §"Persistence boundary".
   */
  onMount(() => {
    // Drift detector: console.warn if the boot script's meta-color
    // disagrees with the runtime's value for this theme.
    // docs/behavior/themes.md §"Failure modes" — "Drift between boot
    // script and runtime": the runtime is authoritative; correction
    // follows immediately via applyThemeToDom below.
    const expectedHex = THEME_COLOR_HEX[themeStore.theme];
    const metaEl = document.querySelector<HTMLMetaElement>(`meta[name="${THEME_META_NAME}"]`);
    if (metaEl !== null && metaEl.content !== expectedHex) {
      console.warn(
        `[bearings/themes] boot-script drift on cold load: ` +
          `meta[name="${THEME_META_NAME}"] is "${metaEl.content}" but runtime expects ` +
          `"${expectedHex}" for theme "${themeStore.theme}". Correcting.`,
      );
    }
    // Re-apply on mount — corrects any drift left by the boot script.
    applyThemeToDom(themeStore.theme);

    function onStorage(event: StorageEvent): void {
      if (event.key === THEME_STORAGE_KEY) {
        syncFromStorage();
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  });

  /**
   * Save-failed toast — surfaces when :func:`setTheme` reports a
   * localStorage write failure. The toast is a transient ``role=alert``
   * banner; clicking dismiss acknowledges (resets the flag so a
   * subsequent failure re-fires the effect).
   */
  const saveFailed = $derived(themeStore.lastSaveOk === false);
</script>

{#if children}
  {@render children()}
{/if}

{#if saveFailed}
  <div class="theme-provider__toast" role="alert" data-testid="theme-provider-save-failed-toast">
    <span>{THEME_STRINGS.saveFailedToast}</span>
    <button
      type="button"
      class="theme-provider__toast-dismiss"
      data-testid="theme-provider-save-failed-toast-dismiss"
      onclick={() => acknowledgeSaveStatus()}
    >
      ×
    </button>
  </div>
{/if}

<style>
  .theme-provider__toast {
    position: fixed;
    bottom: 1rem;
    right: 1rem;
    display: flex;
    gap: 0.5rem;
    align-items: center;
    padding: 0.5rem 0.75rem;
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-strong));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.375rem;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    z-index: 100;
    font-size: 0.875rem;
  }
  .theme-provider__toast-dismiss {
    background: transparent;
    border: none;
    color: inherit;
    cursor: pointer;
    font-size: 1.25rem;
    line-height: 1;
    padding: 0;
  }
</style>
