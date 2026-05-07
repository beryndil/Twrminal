<script lang="ts">
  /**
   * Settings page — Profile, Appearance, Defaults, and System routing rules.
   *
   * Per ``docs/behavior/preferences.md`` §"Profile / Identity" the
   * Profile section (with avatar upload / sync + display name) renders
   * first, above Appearance.
   *
   * Per ``docs/behavior/themes.md`` §"Theme picker UI" the Appearance
   * controls live here (theme picker today; future timezone /
   * density). Per ``docs/model-routing-v1-spec.md`` §10 "Modified:
   * Routing rule editor" the system-wide rule editor lives "under
   * settings" — surfaced as a third section below Defaults.
   *
   * Item 3.2 adds the Defaults section: a form backed by
   * ``GET / PATCH /api/preferences`` that persists theme,
   * default_model, default_permission_mode, and default_working_dir.
   * The new-session form reads these on mount to pre-fill its fields.
   *
   * gap-cycle-03-011 adds the Profile section above Appearance.
   *
   * Reachable via the ``/settings`` route. The center column of
   * ``+layout.svelte`` renders this page when no session is selected
   * (i.e. the ``children`` snippet branch).
   */
  import {
    AUTH_SECTION_STRINGS,
    KNOWN_EXECUTOR_MODELS,
    KNOWN_PERMISSION_MODES,
    KNOWN_THEMES,
    NOTIFICATION_STRINGS,
    PERMISSION_MODE_LABELS,
    PREFERENCES_STRINGS,
    PROFILE_STRINGS,
    THEME_STRINGS,
    type ExecutorModel,
    type PermissionMode,
    type ThemeId,
  } from "$lib/config";
  import { clearToken, getStoredToken, saveToken } from "$lib/stores/auth.svelte";
  import {
    deleteAvatar,
    getPreferences,
    patchPreferences,
    syncFromSystem,
    uploadAvatar,
    type PreferencesPatch,
    type PreferencesOut,
  } from "$lib/api/preferences";
  import { importFromBearings, type ImportResultOut } from "$lib/api/import";
  import {
    requestNotifyPermission,
    setNotifyOnComplete,
    supportsNotifications,
  } from "$lib/utils/notify";
  import ThemePicker from "$lib/themes/ThemePicker.svelte";
  import RoutingRuleEditor from "$lib/components/routing/RoutingRuleEditor.svelte";
  import UserIdentityBlock from "$lib/components/identity/UserIdentityBlock.svelte";

  // ---- Profile section state ----

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

  // ---- Notifications section state ----

  let prefNotifyOnComplete = $state(false);
  let notifyError = $state<string | null>(null);
  // Derived: true when the browser has no Notification API.
  const notifyUnsupported = $derived(!supportsNotifications());
  // Derived: true when the user has explicitly blocked notifications.
  const notifyDenied = $derived(
    supportsNotifications() && typeof Notification !== "undefined"
      ? Notification.permission === "denied"
      : false,
  );

  // ---- Authentication section state (gap-cycle-07-002) ----

  let authTokenValue = $state(getStoredToken());

  function handleAuthTokenInput(e: Event): void {
    const value = (e.target as HTMLInputElement).value;
    authTokenValue = value;
    if (value.trim() !== "") {
      void saveToken(value);
    } else {
      clearToken();
    }
  }

  // ---- Defaults section state ----

  let loadError = $state<string | null>(null);
  let saveError = $state<string | null>(null);
  let savedFeedback = $state(false);
  let saving = $state(false);
  let importing = $state(false);
  let importResult = $state<ImportResultOut | null>(null);
  let importError = $state<string | null>(null);

  // Controlled values — undefined until the API round-trip resolves.
  let prefTheme = $state<ThemeId>("default");
  let prefModel = $state<ExecutorModel | "">("");
  let prefPermissionMode = $state<PermissionMode | "">("");
  let prefWorkingDir = $state("");

  $effect(() => {
    void loadPrefs();
  });

  async function loadPrefs(): Promise<void> {
    loadError = null;
    try {
      const prefs: PreferencesOut = await getPreferences();
      // Profile fields.
      profileDisplayName = prefs.display_name ?? "";
      profileAvatarUrl = prefs.avatar_url;
      profileUpdatedAt = prefs.updated_at;
      // Defaults fields.
      prefTheme = (KNOWN_THEMES as readonly string[]).includes(prefs.theme)
        ? (prefs.theme as ThemeId)
        : "default";
      prefModel = prefs.default_model != null ? (prefs.default_model as ExecutorModel) : "";
      prefPermissionMode =
        prefs.default_permission_mode != null
          ? (prefs.default_permission_mode as PermissionMode)
          : "";
      prefWorkingDir = prefs.default_working_dir ?? "";
      // Notifications fields — sync module-level state so agent.svelte.ts sees
      // the correct value from initial load onward.
      prefNotifyOnComplete = prefs.notify_on_complete;
      setNotifyOnComplete(prefs.notify_on_complete);
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
    }
  }

  function _applyProfilePrefs(prefs: PreferencesOut): void {
    profileDisplayName = prefs.display_name ?? "";
    profileAvatarUrl = prefs.avatar_url;
    profileUpdatedAt = prefs.updated_at;
  }

  async function saveProfile(): Promise<void> {
    profileSaving = true;
    profileSaveError = null;
    profileSavedFeedback = false;
    try {
      const patch: PreferencesPatch = {
        display_name: profileDisplayName.trim() !== "" ? profileDisplayName.trim() : null,
      };
      const updated = await patchPreferences(patch);
      _applyProfilePrefs(updated);
      profileSavedFeedback = true;
      setTimeout(() => {
        profileSavedFeedback = false;
      }, 2000);
    } catch (err) {
      profileSaveError = err instanceof Error ? err.message : String(err);
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
    // Reset the file input so re-selecting the same file fires change again.
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

  async function savePrefs(): Promise<void> {
    saving = true;
    saveError = null;
    savedFeedback = false;
    try {
      const patch: PreferencesPatch = {
        theme: prefTheme,
        default_model: prefModel !== "" ? prefModel : null,
        default_permission_mode: prefPermissionMode !== "" ? prefPermissionMode : null,
        default_working_dir: prefWorkingDir.trim() !== "" ? prefWorkingDir.trim() : null,
      };
      await patchPreferences(patch);
      savedFeedback = true;
      // Clear the "Saved." feedback after 2 s so it doesn't linger.
      setTimeout(() => {
        savedFeedback = false;
      }, 2000);
    } catch (err) {
      saveError = err instanceof Error ? err.message : String(err);
    } finally {
      saving = false;
    }
  }

  /**
   * Handle the "Notify when Claude finishes replying" toggle.
   *
   * When turning ON: request browser permission first. If the user denies,
   * roll the toggle back and surface an inline error. Otherwise persist via
   * PATCH and sync the module-level state.
   *
   * When turning OFF: persist immediately, no permission prompt needed.
   */
  /**
   * Handle the "Notify when Claude finishes replying" toggle.
   *
   * Optimistic update: flip the state immediately so the checkbox
   * transitions visually, then roll back if the browser denies permission
   * or the PATCH fails.
   *
   * When turning ON: requests browser permission after the optimistic
   * flip. On deny: rolls back to false and surfaces an inline error.
   * When turning OFF: persists immediately; no permission prompt.
   */
  async function handleNotifyToggle(enabled: boolean): Promise<void> {
    notifyError = null;
    // Optimistic: update state now so the toggle visually reflects intent.
    prefNotifyOnComplete = enabled;
    if (enabled) {
      const permission = await requestNotifyPermission();
      if (permission !== "granted") {
        // Roll back — user denied the browser prompt.
        prefNotifyOnComplete = false;
        notifyError = NOTIFICATION_STRINGS.permissionDeniedError;
        return;
      }
    }
    try {
      const updated = await patchPreferences({ notify_on_complete: enabled });
      prefNotifyOnComplete = updated.notify_on_complete;
      setNotifyOnComplete(updated.notify_on_complete);
    } catch (err) {
      // Roll back on API failure.
      prefNotifyOnComplete = !enabled;
      notifyError = err instanceof Error ? err.message : String(err);
    }
  }

  async function runImport(): Promise<void> {
    importing = true;
    importError = null;
    importResult = null;
    try {
      const result = await importFromBearings();
      importResult = result;
      if (result.errors.length > 0) {
        importError = result.errors.join("; ");
      }
    } catch (err) {
      importError = err instanceof Error ? err.message : String(err);
    } finally {
      importing = false;
    }
  }
</script>

<section class="settings-page" data-testid="settings-page" aria-label="Settings">
  <!-- Profile / Identity — gap-cycle-03-011 -->
  <section
    class="settings-page__group"
    aria-label="Profile"
    data-testid="settings-profile"
  >
    <h1 class="settings-page__heading">{PROFILE_STRINGS.heading}</h1>
    <p class="settings-page__lede">{PROFILE_STRINGS.lede}</p>

    {#if loadError !== null}
      <p class="settings-page__error" role="alert"
        >{PROFILE_STRINGS.loadError}: {loadError}</p
      >
    {:else}
      <!-- Identity preview -->
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
        <!-- Display name -->
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

        <!-- Avatar controls -->
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
            <span
              class="settings-defaults__saved"
              role="status"
              data-testid="profile-saved"
            >
              {PROFILE_STRINGS.savedFeedback}
            </span>
          {/if}
          {#if profileSaveError !== null}
            <span
              class="settings-defaults__error"
              role="alert"
              data-testid="profile-save-error"
            >
              {PROFILE_STRINGS.saveError}
            </span>
          {/if}
        </div>
      </form>

      <!-- Sync from system -->
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

  <section class="settings-page__group" aria-label="Appearance">
    <h2 class="settings-page__heading">{THEME_STRINGS.appearanceHeading}</h2>
    <ThemePicker />
  </section>

  <section class="settings-page__group" aria-label="Defaults" data-testid="settings-defaults">
    <h2 class="settings-page__heading">{PREFERENCES_STRINGS.defaultsHeading}</h2>
    <p class="settings-page__lede">{PREFERENCES_STRINGS.defaultsLede}</p>

    {#if loadError !== null}
      <p class="settings-page__error" role="alert">{PREFERENCES_STRINGS.loadError}: {loadError}</p>
    {:else}
      <form
        class="settings-defaults__form"
        onsubmit={(e) => {
          e.preventDefault();
          void savePrefs();
        }}
      >
        <label class="settings-defaults__field">
          <span class="settings-defaults__label">{PREFERENCES_STRINGS.themeLabel}</span>
          <select
            class="settings-defaults__select"
            bind:value={prefTheme}
            data-testid="prefs-theme"
          >
            {#each KNOWN_THEMES as t (t)}
              <option value={t}>{THEME_STRINGS.themeLabels[t]}</option>
            {/each}
          </select>
        </label>

        <label class="settings-defaults__field">
          <span class="settings-defaults__label">{PREFERENCES_STRINGS.modelLabel}</span>
          <select
            class="settings-defaults__select"
            bind:value={prefModel}
            data-testid="prefs-model"
          >
            <option value="">{PREFERENCES_STRINGS.modelPlaceholder}</option>
            {#each KNOWN_EXECUTOR_MODELS as m (m)}
              <option value={m}>{m}</option>
            {/each}
          </select>
        </label>

        <label class="settings-defaults__field">
          <span class="settings-defaults__label">{PREFERENCES_STRINGS.permissionModeLabel}</span>
          <select
            class="settings-defaults__select"
            bind:value={prefPermissionMode}
            data-testid="prefs-permission-mode"
          >
            <option value="">{PREFERENCES_STRINGS.permissionModePlaceholder}</option>
            {#each KNOWN_PERMISSION_MODES as pm (pm)}
              <option value={pm}>{PERMISSION_MODE_LABELS[pm]}</option>
            {/each}
          </select>
        </label>

        <label class="settings-defaults__field">
          <span class="settings-defaults__label">{PREFERENCES_STRINGS.workingDirLabel}</span>
          <input
            type="text"
            class="settings-defaults__input"
            bind:value={prefWorkingDir}
            placeholder={PREFERENCES_STRINGS.workingDirPlaceholder}
            data-testid="prefs-working-dir"
          />
        </label>

        <div class="settings-defaults__actions">
          <button
            type="submit"
            class="settings-defaults__save"
            disabled={saving}
            data-testid="prefs-save"
          >
            {PREFERENCES_STRINGS.saveButton}
          </button>
          {#if savedFeedback}
            <span class="settings-defaults__saved" role="status" data-testid="prefs-saved">
              {PREFERENCES_STRINGS.savedFeedback}
            </span>
          {/if}
          {#if saveError !== null}
            <span class="settings-defaults__error" role="alert" data-testid="prefs-save-error">
              {PREFERENCES_STRINGS.saveError}
            </span>
          {/if}
        </div>
      </form>
    {/if}
  </section>

  <!-- Notifications — gap-cycle-07-001 -->
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

  <!-- Authentication (gap-cycle-07-002) -->
  <section
    class="settings-page__group"
    aria-label="Authentication"
    data-testid="settings-auth"
  >
    <h2 class="settings-page__heading">{AUTH_SECTION_STRINGS.heading}</h2>
    <p class="settings-page__lede">{AUTH_SECTION_STRINGS.lede}</p>
    <label class="settings-defaults__field">
      <span class="settings-defaults__label">{AUTH_SECTION_STRINGS.tokenLabel}</span>
      <input
        type="password"
        class="settings-defaults__input settings-auth__token-input"
        value={authTokenValue}
        placeholder={AUTH_SECTION_STRINGS.tokenPlaceholder}
        oninput={handleAuthTokenInput}
        data-testid="auth-token-input"
        autocomplete="off"
        spellcheck={false}
      />
    </label>
  </section>

  <section class="settings-page__group" aria-label="System routing rules">
    <h2 class="settings-page__heading">System routing rules</h2>
    <p class="settings-page__lede">
      The system-wide rule set evaluated when no per-tag rule matches the routing-preview input. Per
      spec §3 priorities are sparse — drag rows to reorder, or duplicate-and-edit a row to slot a
      new rule between the seeded ones.
    </p>
    <RoutingRuleEditor kind="system" />
  </section>

  <section class="settings-page__group" aria-label="Data import">
    <h2 class="settings-page__heading">Import from Bearings</h2>
    <p class="settings-page__lede">
      Copy all sessions, messages, and tags from the main Bearings database into this instance.
      Existing records are preserved — duplicates are skipped.
    </p>
    <div class="settings-import__actions">
      <button
        class="settings-defaults__save"
        onclick={runImport}
        disabled={importing}
        data-testid="import-button"
      >
        {importing ? "Importing…" : "Import now"}
      </button>
      {#if importResult}
        <span class="settings-import__result" role="status" data-testid="import-result">
          {importResult.sessions_imported} sessions, {importResult.messages_imported} messages,
          {importResult.tags_imported} tags imported.
          {#if importResult.sessions_skipped > 0}({importResult.sessions_skipped} skipped){/if}
        </span>
      {/if}
      {#if importError}
        <span class="settings-page__error" role="alert" data-testid="import-error">
          {importError}
        </span>
      {/if}
    </div>
  </section>
</section>

<style>
  .settings-page {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    padding: 1rem;
    max-width: 56rem;
    margin: 0 auto;
  }
  .settings-page__group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .settings-page__heading {
    font-size: 1.125rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-strong));
    margin: 0;
  }
  .settings-page__lede {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  .settings-page__error {
    font-size: 0.8125rem;
    color: #f87171;
    margin: 0;
  }

  /* Defaults form */
  .settings-defaults__form {
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
  }
  .settings-defaults__field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .settings-defaults__label {
    font-size: 0.75rem;
    font-weight: 500;
    color: rgb(var(--bearings-fg-muted));
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .settings-defaults__select,
  .settings-defaults__input {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-strong));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.3rem 0.5rem;
    font: inherit;
    font-size: 0.8125rem;
    max-width: 24rem;
  }
  .settings-defaults__actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.25rem;
  }
  .settings-defaults__save {
    background: rgb(var(--bearings-accent));
    color: white;
    border: none;
    border-radius: 0.25rem;
    padding: 0.3rem 0.875rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .settings-defaults__save:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .settings-defaults__saved {
    font-size: 0.8125rem;
    color: #4ade80;
  }
  .settings-defaults__error {
    font-size: 0.8125rem;
    color: #f87171;
  }

  /* Import section */
  .settings-import__actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.25rem;
  }
  .settings-import__result {
    font-size: 0.8125rem;
    color: #4ade80;
  }

  /* Notifications section (gap-cycle-07-001) */
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

  /* Profile section (gap-cycle-03-011) */
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

  /* Authentication section (gap-cycle-07-002) */
  .settings-auth__token-input {
    font-family: monospace;
  }
</style>
