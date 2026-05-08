<script lang="ts">
  /**
   * Profile section — display name, avatar upload / remove, sync from system.
   *
   * Extracted from ``frontend/src/routes/settings/+page.svelte`` as part of
   * gap-cycle-07-007 (SettingsShell registry + nav rail). The section is
   * self-contained: it calls ``GET /api/preferences`` on mount to load its
   * own fields (display_name, avatar_url, updated_at) and emits
   * ``onsaveStatus`` callbacks when the user saves or an error occurs.
   *
   * gap-cycle-17-001: autosave on display-name change (debounced ~400 ms)
   * with per-row Saving / Saved / Error badges on all mutating rows.
   */
  import type { SaveStatus } from "../sections.js";
  import { PROFILE_AUTOSAVE_DEBOUNCE_MS, PROFILE_STRINGS } from "$lib/config";
  import {
    deleteAvatar,
    getPreferences,
    patchPreferences,
    syncFromSystem,
    uploadAvatar,
    type PreferencesPatch,
    type PreferencesOut,
  } from "$lib/api/preferences";
  import UserIdentityBlock from "$lib/components/identity/UserIdentityBlock.svelte";
  import { applyPreferences } from "$lib/stores/preferences.svelte";

  type RowSaveState = "idle" | "saving" | "saved" | "error";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  const { onsaveStatus }: Props = $props();

  let profileDisplayName = $state<string>("");
  let profileAvatarUrl = $state<string | null>(null);
  let profileUpdatedAt = $state<string>("");
  let loadError = $state<string | null>(null);

  // Per-row save states — display name, avatar upload, avatar remove, sync.
  let displayNameState = $state<RowSaveState>("idle");
  let displayNameError = $state<string | null>(null);
  let avatarUploadState = $state<RowSaveState>("idle");
  let avatarUploadError = $state<string | null>(null);
  let avatarRemoveState = $state<RowSaveState>("idle");
  let avatarRemoveError = $state<string | null>(null);
  let syncState = $state<RowSaveState>("idle");
  let syncError = $state<string | null>(null);

  // Debounce handle for display-name autosave — not reactive state.
  let displayNameDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    void loadPrefs();
  });

  async function loadPrefs(): Promise<void> {
    loadError = null;
    try {
      const prefs: PreferencesOut = await getPreferences();
      _applyProfilePrefs(prefs);
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
    }
  }

  function _applyProfilePrefs(prefs: PreferencesOut): void {
    profileDisplayName = prefs.display_name ?? "";
    profileAvatarUrl = prefs.avatar_url;
    profileUpdatedAt = prefs.updated_at;
    // Keep the sidebar identity block in sync without a separate GET
    // (gap-cycle-08-002).
    applyPreferences(prefs);
  }

  function handleDisplayNameInput(): void {
    if (displayNameDebounceTimer !== null) {
      clearTimeout(displayNameDebounceTimer);
    }
    displayNameDebounceTimer = setTimeout(() => {
      void saveDisplayName();
    }, PROFILE_AUTOSAVE_DEBOUNCE_MS);
  }

  async function saveDisplayName(): Promise<void> {
    displayNameState = "saving";
    displayNameError = null;
    onsaveStatus?.({ state: "saving" });
    try {
      const patch: PreferencesPatch = {
        display_name: profileDisplayName.trim() !== "" ? profileDisplayName.trim() : null,
      };
      const updated = await patchPreferences(patch);
      _applyProfilePrefs(updated);
      displayNameState = "saved";
      onsaveStatus?.({ state: "saved" });
      setTimeout(() => {
        displayNameState = "idle";
      }, 2000);
    } catch (err) {
      displayNameError = err instanceof Error ? err.message : String(err);
      displayNameState = "error";
      onsaveStatus?.({ state: "error", message: displayNameError ?? undefined });
    }
  }

  async function handleAvatarUpload(e: Event): Promise<void> {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    avatarUploadError = null;
    avatarUploadState = "saving";
    onsaveStatus?.({ state: "saving" });
    try {
      const updated = await uploadAvatar(file);
      _applyProfilePrefs(updated);
      avatarUploadState = "saved";
      onsaveStatus?.({ state: "saved" });
      setTimeout(() => {
        avatarUploadState = "idle";
      }, 2000);
    } catch (err) {
      avatarUploadError = err instanceof Error ? err.message : String(err);
      avatarUploadState = "error";
      onsaveStatus?.({ state: "error", message: avatarUploadError ?? undefined });
    }
    // Reset so re-selecting the same file fires change again.
    input.value = "";
  }

  async function handleAvatarRemove(): Promise<void> {
    avatarRemoveError = null;
    avatarRemoveState = "saving";
    onsaveStatus?.({ state: "saving" });
    try {
      const updated = await deleteAvatar();
      _applyProfilePrefs(updated);
      avatarRemoveState = "saved";
      onsaveStatus?.({ state: "saved" });
      setTimeout(() => {
        avatarRemoveState = "idle";
      }, 2000);
    } catch (err) {
      avatarRemoveError = err instanceof Error ? err.message : String(err);
      avatarRemoveState = "error";
      onsaveStatus?.({ state: "error", message: avatarRemoveError ?? undefined });
    }
  }

  async function handleSyncFromSystem(): Promise<void> {
    syncState = "saving";
    syncError = null;
    onsaveStatus?.({ state: "saving" });
    try {
      const updated = await syncFromSystem();
      _applyProfilePrefs(updated);
      syncState = "saved";
      onsaveStatus?.({ state: "saved" });
      setTimeout(() => {
        syncState = "idle";
      }, 2000);
    } catch (err) {
      syncError = err instanceof Error ? err.message : String(err);
      syncState = "error";
      onsaveStatus?.({ state: "error", message: syncError ?? undefined });
    }
  }
</script>

<section class="settings-page__group" aria-label="Profile" data-testid="settings-profile">
  <h2 class="settings-page__heading">{PROFILE_STRINGS.heading}</h2>
  <p class="settings-page__lede">{PROFILE_STRINGS.lede}</p>

  {#if loadError !== null}
    <p class="settings-page__error" role="alert">{PROFILE_STRINGS.loadError}: {loadError}</p>
  {:else}
    <div class="settings-profile__preview">
      <UserIdentityBlock
        displayName={profileDisplayName || null}
        avatarUrl={profileAvatarUrl}
        cacheBust={profileUpdatedAt}
      />
    </div>

    <div class="settings-defaults__form" data-testid="settings-profile-form">
      <div class="settings-defaults__field">
        <span class="settings-defaults__label">{PROFILE_STRINGS.displayNameLabel}</span>
        <div class="settings-profile__field-row">
          <input
            type="text"
            class="settings-defaults__input"
            bind:value={profileDisplayName}
            oninput={handleDisplayNameInput}
            placeholder={PROFILE_STRINGS.displayNamePlaceholder}
            data-testid="profile-display-name"
          />
          {#if displayNameState === "saving"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--saving"
              role="status"
              data-testid="profile-display-name-badge">{PROFILE_STRINGS.savingBadge}</span
            >
          {:else if displayNameState === "saved"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--saved"
              role="status"
              data-testid="profile-display-name-badge">{PROFILE_STRINGS.savedBadge}</span
            >
          {:else if displayNameState === "error"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--error"
              role="alert"
              data-testid="profile-display-name-badge"
              >{PROFILE_STRINGS.saveFailedPrefix} {displayNameError}</span
            >
          {/if}
        </div>
      </div>

      <div class="settings-defaults__field">
        <span class="settings-defaults__label">{PROFILE_STRINGS.avatarLabel}</span>
        <div class="settings-profile__avatar-actions">
          <label class="settings-defaults__save settings-profile__upload-label">
            {PROFILE_STRINGS.uploadButton}
            <input
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              class="settings-profile__file-input"
              onchange={handleAvatarUpload}
              data-testid="profile-avatar-upload"
            />
          </label>
          {#if profileAvatarUrl !== null}
            <button
              type="button"
              class="settings-profile__remove-btn"
              onclick={handleAvatarRemove}
              data-testid="profile-avatar-remove"
            >
              {PROFILE_STRINGS.removeButton}
            </button>
          {/if}
          {#if avatarUploadState === "saving"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--saving"
              role="status"
              data-testid="profile-avatar-upload-badge">{PROFILE_STRINGS.savingBadge}</span
            >
          {:else if avatarUploadState === "saved"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--saved"
              role="status"
              data-testid="profile-avatar-upload-badge">{PROFILE_STRINGS.savedBadge}</span
            >
          {:else if avatarUploadState === "error"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--error"
              role="alert"
              data-testid="profile-avatar-upload-badge"
              >{PROFILE_STRINGS.saveFailedPrefix} {avatarUploadError}</span
            >
          {/if}
          {#if avatarRemoveState === "saving"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--saving"
              role="status"
              data-testid="profile-avatar-remove-badge">{PROFILE_STRINGS.savingBadge}</span
            >
          {:else if avatarRemoveState === "saved"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--saved"
              role="status"
              data-testid="profile-avatar-remove-badge">{PROFILE_STRINGS.savedBadge}</span
            >
          {:else if avatarRemoveState === "error"}
            <span
              class="settings-profile__row-badge settings-profile__row-badge--error"
              role="alert"
              data-testid="profile-avatar-remove-badge"
              >{PROFILE_STRINGS.saveFailedPrefix} {avatarRemoveError}</span
            >
          {/if}
        </div>
      </div>
    </div>

    <div class="settings-profile__sync">
      <p class="settings-page__lede">{PROFILE_STRINGS.syncLede}</p>
      <div class="settings-profile__sync-row">
        <button
          type="button"
          class="settings-defaults__save"
          disabled={syncState === "saving"}
          onclick={handleSyncFromSystem}
          data-testid="profile-sync"
        >
          {PROFILE_STRINGS.syncButton}
        </button>
        {#if syncState === "saving"}
          <span
            class="settings-profile__row-badge settings-profile__row-badge--saving"
            role="status"
            data-testid="profile-sync-badge">{PROFILE_STRINGS.savingBadge}</span
          >
        {:else if syncState === "saved"}
          <span
            class="settings-profile__row-badge settings-profile__row-badge--saved"
            role="status"
            data-testid="profile-sync-badge">{PROFILE_STRINGS.savedBadge}</span
          >
        {:else if syncState === "error"}
          <span
            class="settings-profile__row-badge settings-profile__row-badge--error"
            role="alert"
            data-testid="profile-sync-badge">{PROFILE_STRINGS.saveFailedPrefix} {syncError}</span
          >
        {/if}
      </div>
    </div>
  {/if}
</section>

<style>
  .settings-profile__preview {
    margin-bottom: 0.75rem;
    padding: 0.625rem;
    background: rgb(var(--bearings-surface-2));
    border-radius: 0.375rem;
    display: inline-flex;
  }
  .settings-profile__field-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .settings-profile__avatar-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .settings-profile__upload-label {
    cursor: pointer;
    display: inline-flex;
    align-items: center;
  }
  .settings-profile__file-input {
    display: none;
  }
  .settings-profile__remove-btn {
    background: transparent;
    color: rgb(var(--bearings-fg-muted));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.3rem 0.875rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .settings-profile__remove-btn:hover {
    color: rgb(var(--bearings-fg-strong));
    border-color: rgb(var(--bearings-fg-muted));
  }
  .settings-profile__sync {
    display: flex;
    align-items: flex-start;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 0.25rem;
    padding-top: 0.75rem;
    border-top: 1px solid rgb(var(--bearings-border));
  }
  .settings-profile__sync-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .settings-profile__row-badge {
    font-size: 0.75rem;
    font-style: italic;
    white-space: nowrap;
  }
  .settings-profile__row-badge--saving {
    color: rgb(var(--bearings-fg-muted));
  }
  .settings-profile__row-badge--saved {
    color: rgb(var(--bearings-accent));
  }
  .settings-profile__row-badge--error {
    color: rgb(var(--bearings-error, 220 38 38));
  }
</style>
