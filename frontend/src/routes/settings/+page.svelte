<script lang="ts">
  /**
   * Settings page — Appearance, Defaults, and System routing rules.
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
   * Reachable via the ``/settings`` route. The center column of
   * ``+layout.svelte`` renders this page when no session is selected
   * (i.e. the ``children`` snippet branch).
   */
  import {
    KNOWN_EXECUTOR_MODELS,
    KNOWN_PERMISSION_MODES,
    KNOWN_THEMES,
    PERMISSION_MODE_LABELS,
    PREFERENCES_STRINGS,
    THEME_STRINGS,
    type ExecutorModel,
    type PermissionMode,
    type ThemeId,
  } from "$lib/config";
  import {
    getPreferences,
    patchPreferences,
    type PreferencesPatch,
    type PreferencesOut,
  } from "$lib/api/preferences";
  import ThemePicker from "$lib/themes/ThemePicker.svelte";
  import RoutingRuleEditor from "$lib/components/routing/RoutingRuleEditor.svelte";

  // ---- Defaults section state ----

  let loadError = $state<string | null>(null);
  let saveError = $state<string | null>(null);
  let savedFeedback = $state(false);
  let saving = $state(false);

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
      prefTheme = (KNOWN_THEMES as readonly string[]).includes(prefs.theme)
        ? (prefs.theme as ThemeId)
        : "default";
      prefModel = prefs.default_model != null ? (prefs.default_model as ExecutorModel) : "";
      prefPermissionMode =
        prefs.default_permission_mode != null
          ? (prefs.default_permission_mode as PermissionMode)
          : "";
      prefWorkingDir = prefs.default_working_dir ?? "";
    } catch (err) {
      loadError = err instanceof Error ? err.message : String(err);
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
</script>

<section class="settings-page" data-testid="settings-page" aria-label="Settings">
  <section class="settings-page__group" aria-label="Appearance">
    <h1 class="settings-page__heading">{THEME_STRINGS.appearanceHeading}</h1>
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

  <section class="settings-page__group" aria-label="System routing rules">
    <h2 class="settings-page__heading">System routing rules</h2>
    <p class="settings-page__lede">
      The system-wide rule set evaluated when no per-tag rule matches the routing-preview input. Per
      spec §3 priorities are sparse — drag rows to reorder, or duplicate-and-edit a row to slot a
      new rule between the seeded ones.
    </p>
    <RoutingRuleEditor kind="system" />
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
</style>
