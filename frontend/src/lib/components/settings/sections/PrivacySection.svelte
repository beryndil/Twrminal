<script lang="ts">
  /**
   * Privacy section — telemetry promise + data-dir opener.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import { PRIVACY_STRINGS } from "$lib/config";
  import { getHealth } from "$lib/api/health";
  import { shellOpenInTerminal } from "$lib/api/shell";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // Privacy section is read-only — no user-initiated saves.
  const { onsaveStatus: _onsaveStatus }: Props = $props();

  let privacyDataDir = $state<string | null>(null);
  let privacyDataDirLoading = $state(true);
  let privacyDataDirError = $state<string | null>(null);
  let privacyOpenState = $state<"opened" | "copied" | "error" | null>(null);

  $effect(() => {
    void loadDataDir();
  });

  async function loadDataDir(): Promise<void> {
    privacyDataDirLoading = true;
    privacyDataDirError = null;
    try {
      const health = await getHealth();
      privacyDataDir = health.data_dir;
    } catch (err) {
      privacyDataDirError = err instanceof Error ? err.message : String(err);
    } finally {
      privacyDataDirLoading = false;
    }
  }

  async function handleOpenDataDir(): Promise<void> {
    if (privacyDataDir === null) return;
    privacyOpenState = null;
    try {
      await shellOpenInTerminal(privacyDataDir);
      privacyOpenState = "opened";
      setTimeout(() => {
        privacyOpenState = null;
      }, 2000);
    } catch {
      try {
        await navigator.clipboard.writeText(privacyDataDir);
        privacyOpenState = "copied";
      } catch {
        privacyOpenState = "error";
      }
    }
  }
</script>

<section class="settings-page__group" aria-label="Privacy" data-testid="settings-privacy">
  <h2 class="settings-page__heading">{PRIVACY_STRINGS.heading}</h2>

  <div class="settings-privacy__row" data-testid="privacy-telemetry-row">
    <span class="settings-defaults__label settings-privacy__row-label">
      {PRIVACY_STRINGS.telemetryLine}
    </span>
    <a
      class="settings-privacy__link"
      href={PRIVACY_STRINGS.telemetryLinkHref}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="privacy-telemetry-link"
    >
      {PRIVACY_STRINGS.telemetryLinkLabel}
    </a>
  </div>

  <div class="settings-privacy__row" data-testid="privacy-data-dir-row">
    <span class="settings-defaults__label settings-privacy__row-label">
      {PRIVACY_STRINGS.dataDirLabel}
    </span>
    {#if privacyDataDirLoading}
      <span class="settings-page__lede" data-testid="privacy-data-dir-loading">
        {PRIVACY_STRINGS.dataDirLoading}
      </span>
    {:else if privacyDataDirError !== null}
      <span class="settings-page__error" role="alert" data-testid="privacy-data-dir-error">
        {PRIVACY_STRINGS.dataDirError}
      </span>
    {:else}
      <code class="settings-privacy__data-dir" data-testid="privacy-data-dir-path">
        {privacyDataDir}
      </code>
      <div class="settings-privacy__open-actions">
        <button
          type="button"
          class="settings-defaults__save"
          onclick={handleOpenDataDir}
          data-testid="privacy-open-dir-btn"
        >
          {privacyOpenState === "opened"
            ? PRIVACY_STRINGS.openDirOpened
            : privacyOpenState === "copied"
              ? PRIVACY_STRINGS.openDirCopied
              : PRIVACY_STRINGS.openDirButton}
        </button>
        {#if privacyOpenState === "copied"}
          <p
            class="settings-page__lede settings-privacy__footnote"
            data-testid="privacy-clipboard-note"
          >
            {PRIVACY_STRINGS.clipboardFallbackNote}
          </p>
        {:else if privacyOpenState === "error"}
          <p class="settings-page__error" role="alert" data-testid="privacy-open-error">
            {PRIVACY_STRINGS.openDirError}
          </p>
        {/if}
      </div>
    {/if}
  </div>
</section>

<style>
  .settings-privacy__row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  .settings-privacy__row-label {
    text-transform: none;
    letter-spacing: normal;
    font-size: 0.8125rem;
    font-weight: 400;
    color: rgb(var(--bearings-fg-strong));
  }
  .settings-privacy__link {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-accent));
    text-decoration: underline;
  }
  .settings-privacy__link:hover {
    opacity: 0.85;
  }
  .settings-privacy__data-dir {
    font-family: monospace;
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-strong));
    background: rgb(var(--bearings-surface-2));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.15rem 0.4rem;
  }
  .settings-privacy__open-actions {
    display: flex;
    align-items: flex-start;
    flex-direction: column;
    gap: 0.375rem;
  }
  .settings-privacy__footnote {
    font-size: 0.75rem;
  }
</style>
