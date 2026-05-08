<script lang="ts">
  /**
   * Defaults section — theme, executor model, permission mode, working dir.
   * Backed by ``GET / PATCH /api/preferences``.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   *
   * gap-cycle-17-002: per-field autosave — selects PATCH immediately on
   * change, the working-dir text input debounces ~400 ms before PATCHing.
   * Save button removed. Each row carries a Saving… / Saved / Failed badge.
   * Theme select reads from ``themeStore`` so it stays in sync with the
   * Appearance ThemePicker without a page reload.
   */
  import type { SaveStatus } from "../sections.js";
  import {
    DEFAULTS_AUTOSAVE_DEBOUNCE_MS,
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
  import { setTheme, themeStore } from "$lib/themes/store.svelte";

  type RowSaveState = "idle" | "saving" | "saved" | "error";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  const { onsaveStatus }: Props = $props();

  let loadError = $state<string | null>(null);

  // Theme is not stored locally — themeStore.theme is the canonical
  // in-memory value shared with the ThemePicker in Appearance.
  let themeState = $state<RowSaveState>("idle");
  let themeError = $state<string | null>(null);

  let prefModel = $state<ExecutorModel | "">("");
  let modelState = $state<RowSaveState>("idle");
  let modelError = $state<string | null>(null);

  let prefPermissionMode = $state<PermissionMode | "">("");
  let permissionModeState = $state<RowSaveState>("idle");
  let permissionModeError = $state<string | null>(null);

  let prefWorkingDir = $state("");
  let workingDirState = $state<RowSaveState>("idle");
  let workingDirError = $state<string | null>(null);

  // Debounce handle for working-dir autosave — not reactive state.
  let workingDirDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    void loadPrefs();
  });

  async function loadPrefs(): Promise<void> {
    loadError = null;
    try {
      const prefs: PreferencesOut = await getPreferences();
      // Theme is not loaded from DB here; themeStore.theme already reflects
      // the persisted localStorage value and stays in sync with ThemePicker.
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

  async function patchField(
    patch: PreferencesPatch,
    setRowState: (s: RowSaveState) => void,
    setRowError: (msg: string | null) => void,
  ): Promise<void> {
    setRowState("saving");
    setRowError(null);
    onsaveStatus?.({ state: "saving" });
    try {
      await patchPreferences(patch);
      setRowState("saved");
      onsaveStatus?.({ state: "saved" });
      setTimeout(() => {
        setRowState("idle");
      }, 2000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setRowError(msg);
      setRowState("error");
      onsaveStatus?.({ state: "error", message: msg });
    }
  }

  function handleThemeChange(event: Event): void {
    const next = (event.currentTarget as HTMLSelectElement).value as ThemeId;
    if (!(KNOWN_THEMES as readonly string[]).includes(next)) return;
    // Apply immediately to DOM + localStorage + themeStore (mirrors ThemePicker).
    setTheme(next);
    void patchField(
      { theme: next },
      (s) => {
        themeState = s;
      },
      (msg) => {
        themeError = msg;
      },
    );
  }

  function handleModelChange(event: Event): void {
    const next = (event.currentTarget as HTMLSelectElement).value as ExecutorModel | "";
    prefModel = next;
    void patchField(
      { default_model: next !== "" ? next : null },
      (s) => {
        modelState = s;
      },
      (msg) => {
        modelError = msg;
      },
    );
  }

  function handlePermissionModeChange(event: Event): void {
    const next = (event.currentTarget as HTMLSelectElement).value as PermissionMode | "";
    prefPermissionMode = next;
    void patchField(
      { default_permission_mode: next !== "" ? next : null },
      (s) => {
        permissionModeState = s;
      },
      (msg) => {
        permissionModeError = msg;
      },
    );
  }

  function handleWorkingDirInput(): void {
    if (workingDirDebounceTimer !== null) {
      clearTimeout(workingDirDebounceTimer);
    }
    workingDirDebounceTimer = setTimeout(() => {
      void patchField(
        { default_working_dir: prefWorkingDir.trim() !== "" ? prefWorkingDir.trim() : null },
        (s) => {
          workingDirState = s;
        },
        (msg) => {
          workingDirError = msg;
        },
      );
    }, DEFAULTS_AUTOSAVE_DEBOUNCE_MS);
  }
</script>

<section class="settings-page__group" aria-label="Defaults" data-testid="settings-defaults">
  <h2 class="settings-page__heading">{PREFERENCES_STRINGS.defaultsHeading}</h2>
  <p class="settings-page__lede">{PREFERENCES_STRINGS.defaultsLede}</p>

  {#if loadError !== null}
    <p class="settings-page__error" role="alert">{PREFERENCES_STRINGS.loadError}: {loadError}</p>
  {:else}
    <div class="settings-defaults__form">
      <div class="settings-defaults__field">
        <span class="settings-defaults__label">{PREFERENCES_STRINGS.themeLabel}</span>
        <div class="settings-defaults__field-row">
          <select
            class="settings-defaults__select"
            value={themeStore.theme}
            onchange={handleThemeChange}
            data-testid="prefs-theme"
          >
            {#each KNOWN_THEMES as t (t)}
              <option value={t}>{THEME_STRINGS.themeLabels[t]}</option>
            {/each}
          </select>
          {#if themeState === "saving"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saving"
              role="status"
              data-testid="prefs-theme-badge">{PREFERENCES_STRINGS.savingBadge}</span
            >
          {:else if themeState === "saved"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saved"
              role="status"
              data-testid="prefs-theme-badge">{PREFERENCES_STRINGS.savedBadge}</span
            >
          {:else if themeState === "error"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--error"
              role="alert"
              data-testid="prefs-theme-badge"
              >{PREFERENCES_STRINGS.saveFailedPrefix} {themeError}</span
            >
          {/if}
        </div>
      </div>

      <div class="settings-defaults__field">
        <span class="settings-defaults__label">{PREFERENCES_STRINGS.modelLabel}</span>
        <div class="settings-defaults__field-row">
          <select
            class="settings-defaults__select"
            value={prefModel}
            onchange={handleModelChange}
            data-testid="prefs-model"
          >
            <option value="">{PREFERENCES_STRINGS.modelPlaceholder}</option>
            {#each KNOWN_EXECUTOR_MODELS as m (m)}
              <option value={m}>{m}</option>
            {/each}
          </select>
          {#if modelState === "saving"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saving"
              role="status"
              data-testid="prefs-model-badge">{PREFERENCES_STRINGS.savingBadge}</span
            >
          {:else if modelState === "saved"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saved"
              role="status"
              data-testid="prefs-model-badge">{PREFERENCES_STRINGS.savedBadge}</span
            >
          {:else if modelState === "error"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--error"
              role="alert"
              data-testid="prefs-model-badge"
              >{PREFERENCES_STRINGS.saveFailedPrefix} {modelError}</span
            >
          {/if}
        </div>
      </div>

      <div class="settings-defaults__field">
        <span class="settings-defaults__label">{PREFERENCES_STRINGS.permissionModeLabel}</span>
        <div class="settings-defaults__field-row">
          <select
            class="settings-defaults__select"
            value={prefPermissionMode}
            onchange={handlePermissionModeChange}
            data-testid="prefs-permission-mode"
          >
            <option value="">{PREFERENCES_STRINGS.permissionModePlaceholder}</option>
            {#each KNOWN_PERMISSION_MODES as pm (pm)}
              <option value={pm}>{PERMISSION_MODE_LABELS[pm]}</option>
            {/each}
          </select>
          {#if permissionModeState === "saving"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saving"
              role="status"
              data-testid="prefs-permission-mode-badge">{PREFERENCES_STRINGS.savingBadge}</span
            >
          {:else if permissionModeState === "saved"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saved"
              role="status"
              data-testid="prefs-permission-mode-badge">{PREFERENCES_STRINGS.savedBadge}</span
            >
          {:else if permissionModeState === "error"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--error"
              role="alert"
              data-testid="prefs-permission-mode-badge"
              >{PREFERENCES_STRINGS.saveFailedPrefix} {permissionModeError}</span
            >
          {/if}
        </div>
      </div>

      <div class="settings-defaults__field">
        <span class="settings-defaults__label">{PREFERENCES_STRINGS.workingDirLabel}</span>
        <div class="settings-defaults__field-row">
          <input
            type="text"
            class="settings-defaults__input"
            bind:value={prefWorkingDir}
            oninput={handleWorkingDirInput}
            placeholder={PREFERENCES_STRINGS.workingDirPlaceholder}
            data-testid="prefs-working-dir"
          />
          {#if workingDirState === "saving"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saving"
              role="status"
              data-testid="prefs-working-dir-badge">{PREFERENCES_STRINGS.savingBadge}</span
            >
          {:else if workingDirState === "saved"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--saved"
              role="status"
              data-testid="prefs-working-dir-badge">{PREFERENCES_STRINGS.savedBadge}</span
            >
          {:else if workingDirState === "error"}
            <span
              class="settings-defaults__row-badge settings-defaults__row-badge--error"
              role="alert"
              data-testid="prefs-working-dir-badge"
              >{PREFERENCES_STRINGS.saveFailedPrefix} {workingDirError}</span
            >
          {/if}
        </div>
      </div>
    </div>
  {/if}
</section>

<style>
  .settings-defaults__field-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .settings-defaults__row-badge {
    font-size: 0.75rem;
    font-style: italic;
    white-space: nowrap;
  }
  .settings-defaults__row-badge--saving {
    color: rgb(var(--bearings-fg-muted));
  }
  .settings-defaults__row-badge--saved {
    color: rgb(var(--bearings-accent));
  }
  .settings-defaults__row-badge--error {
    color: rgb(var(--bearings-error, 220 38 38));
  }
</style>
