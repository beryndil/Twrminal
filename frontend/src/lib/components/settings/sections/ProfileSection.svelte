<script lang="ts">
  /**
   * Profile section — display name, avatar upload / remove, sync from system.
   *
   * Extracted from ``frontend/src/routes/settings/+page.svelte`` as part of
   * gap-cycle-07-007 (SettingsShell registry + nav rail). The section is
   * self-contained: it calls ``GET /api/preferences`` on mount to load its
   * own fields (display_name, avatar_url, updated_at) and emits
   * ``onsaveStatus`` callbacks when the user saves or an error occurs.
   */
  import type { SaveStatus } from "../sections.js";
  import { PROFILE_STRINGS } from "$lib/config";
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

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  const { onsaveStatus }: Props = $props();

  let profileDisplayName = $state<string>("");
  let profileAvatarUrl = $state<string | null>(null);
  let profileUpdatedAt = $state<string>("");
  let profileSaving = $state(false);
  let profileSavedFeedback = $state(false);
  let profileSaveError = $state<string | null>(null);
  let profileSyncing = $state(false);
  let profileSyncError = $state<string | null>(null);
  let profileUploadError = $state<string | null>(null);
  let profileRemoveError = $state<string | null>(null);
  let loadError = $state<string | null>(null);

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

  async function saveProfile(): Promise<void> {
    profileSaving = true;
    profileSaveError = null;
    profileSavedFeedback = false;
    onsaveStatus?.({ state: "saving" });
    try {
      const patch: PreferencesPatch = {
        display_name: profileDisplayName.trim() !== "" ? profileDisplayName.trim() : null,
      };
      const updated = await patchPreferences(patch);
      _applyProfilePrefs(updated);
      profileSavedFeedback = true;
      onsaveStatus?.({ state: "saved" });
      setTimeout(() => {
        profileSavedFeedback = false;
      }, 2000);
    } catch (err) {
      profileSaveError = err instanceof Error ? err.message : String(err);
      onsaveStatus?.({ state: "error", message: profileSaveError ?? undefined });
    } finally {
      profileSaving = false;
    }
  }

  async function handleAvatarUpload(e: Event): Promise<void> {
    profileUploadError = null;
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    try {
      const updated = await uploadAvatar(file);
      _applyProfilePrefs(updated);
    } catch (err) {
      profileUploadError = err instanceof Error ? err.message : String(err);
    }
    // Reset so re-selecting the same file fires change again.
    input.value = "";
  }

  async function handleAvatarRemove(): Promise<void> {
    profileRemoveError = null;
    try {
      const updated = await deleteAvatar();
      _applyProfilePrefs(updated);
    } catch (err) {
      profileRemoveError = err instanceof Error ? err.message : String(err);
    }
  }

  async function handleSyncFromSystem(): Promise<void> {
    profileSyncing = true;
    profileSyncError = null;
    try {
      const updated = await syncFromSystem();
      _applyProfilePrefs(updated);
    } catch (err) {
      profileSyncError = err instanceof Error ? err.message : String(err);
    } finally {
      profileSyncing = false;
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

    <form
      class="settings-defaults__form"
      onsubmit={(e) => {
        e.preventDefault();
        void saveProfile();
      }}
      data-testid="settings-profile-form"
    >
      <label class="settings-defaults__field">
        <span class="settings-defaults__label">{PROFILE_STRINGS.displayNameLabel}</span>
        <input
          type="text"
          class="settings-defaults__input"
          bind:value={profileDisplayName}
          placeholder={PROFILE_STRINGS.displayNamePlaceholder}
          data-testid="profile-display-name"
        />
      </label>

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
        </div>
        {#if profileUploadError !== null}
          <span class="settings-page__error" role="alert" data-testid="profile-upload-error">
            {PROFILE_STRINGS.uploadError}
          </span>
        {/if}
        {#if profileRemoveError !== null}
          <span class="settings-page__error" role="alert" data-testid="profile-remove-error">
            {PROFILE_STRINGS.removeError}
          </span>
        {/if}
      </div>

      <div class="settings-defaults__actions">
        <button
          type="submit"
          class="settings-defaults__save"
          disabled={profileSaving}
          data-testid="profile-save"
        >
          {PROFILE_STRINGS.saveButton}
        </button>
        {#if profileSavedFeedback}
          <span class="settings-defaults__saved" role="status" data-testid="profile-saved">
            {PROFILE_STRINGS.savedFeedback}
          </span>
        {/if}
        {#if profileSaveError !== null}
          <span class="settings-defaults__error" role="alert" data-testid="profile-save-error">
            {PROFILE_STRINGS.saveError}
          </span>
        {/if}
      </div>
    </form>

    <div class="settings-profile__sync">
      <p class="settings-page__lede">{PROFILE_STRINGS.syncLede}</p>
      <button
        type="button"
        class="settings-defaults__save"
        disabled={profileSyncing}
        onclick={handleSyncFromSystem}
        data-testid="profile-sync"
      >
        {PROFILE_STRINGS.syncButton}
      </button>
      {#if profileSyncError !== null}
        <span class="settings-page__error" role="alert" data-testid="profile-sync-error">
          {PROFILE_STRINGS.syncError}
        </span>
      {/if}
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
</style>
