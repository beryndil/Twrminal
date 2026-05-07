<script lang="ts">
  /**
   * Defaults section — theme, executor model, permission mode, working dir.
   * Backed by ``GET / PATCH /api/preferences``.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
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

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  const { onsaveStatus }: Props = $props();

  let loadError = $state<string | null>(null);
  let saveError = $state<string | null>(null);
  let savedFeedback = $state(false);
  let saving = $state(false);

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
    onsaveStatus?.({ state: "saving" });
    try {
      const patch: PreferencesPatch = {
        theme: prefTheme,
        default_model: prefModel !== "" ? prefModel : null,
        default_permission_mode: prefPermissionMode !== "" ? prefPermissionMode : null,
        default_working_dir: prefWorkingDir.trim() !== "" ? prefWorkingDir.trim() : null,
      };
      await patchPreferences(patch);
      savedFeedback = true;
      onsaveStatus?.({ state: "saved" });
      setTimeout(() => {
        savedFeedback = false;
      }, 2000);
    } catch (err) {
      saveError = err instanceof Error ? err.message : String(err);
      onsaveStatus?.({ state: "error", message: saveError ?? undefined });
    } finally {
      saving = false;
    }
  }
</script>

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
        <select class="settings-defaults__select" bind:value={prefTheme} data-testid="prefs-theme">
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
