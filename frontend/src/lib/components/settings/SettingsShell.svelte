<script lang="ts">
  /**
   * SettingsShell — two-column settings layout (gap-cycle-07-007).
   *
   * Left rail: ``role="tablist"`` ``aria-orientation="vertical"`` — one
   * ``<button role="tab">`` per registered section, roving tabindex,
   * ↑/↓/Home/End keyboard nav, ``aria-selected`` + ``aria-controls``
   * wiring.
   *
   * Right pane: one ``role="tabpanel"`` per section, rendered in the DOM
   * at all times (CSS ``display:none`` hides inactive panels). Keeping
   * every panel mounted means the existing per-section test suites —
   * which render the whole page and query arbitrary section testids —
   * continue to pass without modification.
   *
   * URL: active section id is mirrored into ``?settings=<id>`` via
   * ``history.replaceState``; the initial value is read from
   * ``window.location.search`` on mount (no ``$app/state`` import, so the
   * shell can be tested without mocking SvelteKit internals).
   *
   * Footer: shows aggregated save status for the active section —
   * "Saving…" / "All changes saved" / "Failed to save: …". Resets when
   * the user switches sections.
   */
  import { SETTINGS_SECTIONS, type SaveStatus, type SettingsSectionDef } from "./sections.js";
  import { SETTINGS_SHELL_STRINGS } from "$lib/config";

  interface Props {
    /**
     * Override the section registry — used by unit tests to inject stub
     * sections without importing the real section components.
     */
    sections?: readonly SettingsSectionDef[];
    /**
     * Override the initial active section id — used by unit tests to
     * control the starting state without manipulating ``window.location``.
     */
    initialSectionId?: string;
  }

  const { sections = SETTINGS_SECTIONS, initialSectionId }: Props = $props();

  /** Registry sorted by weight ascending (already ordered, but defensive). */
  const sortedSections = $derived(
    [...sections].sort((a, b) => a.weight - b.weight),
  );

  /** Resolve initial section: prop override (validated) > URL param > first section. */
  function resolveInitialId(): string {
    if (initialSectionId !== undefined && sections.some((s) => s.id === initialSectionId)) {
      return initialSectionId;
    }
    const fromUrl = new URLSearchParams(window.location.search).get("settings");
    if (fromUrl !== null && sections.some((s) => s.id === fromUrl)) return fromUrl;
    return sections[0]?.id ?? "";
  }

  let activeSectionId = $state(resolveInitialId());

  /** Save status emitted by the active section's last write. */
  let saveStatus = $state<SaveStatus>({ state: "idle" });

  function selectSection(id: string): void {
    if (id === activeSectionId) return;
    activeSectionId = id;
    saveStatus = { state: "idle" };
    // Mirror into URL without pushing a history entry.
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("settings", id);
      history.replaceState({}, "", url.toString());
    } catch {
      // Silently ignore in environments where replaceState is unavailable.
    }
  }

  function handleSaveStatus(status: SaveStatus): void {
    saveStatus = status;
  }

  /** Roving tabindex: the active rail button gets 0, all others get -1. */
  function tabIndex(id: string): 0 | -1 {
    return id === activeSectionId ? 0 : -1;
  }

  /** Keyboard nav on the tablist: ↑/↓ cycle, Home/End jump to ends. */
  function handleRailKeydown(e: KeyboardEvent): void {
    const ids = sortedSections.map((s) => s.id);
    const idx = ids.indexOf(activeSectionId);
    if (idx === -1) return;

    let next: number | null = null;
    if (e.key === "ArrowDown") next = (idx + 1) % ids.length;
    else if (e.key === "ArrowUp") next = (idx - 1 + ids.length) % ids.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = ids.length - 1;

    if (next !== null) {
      e.preventDefault();
      selectSection(ids[next]);
    }
  }

  /** Derived footer label — empty string means nothing is shown. */
  const footerText = $derived((): string => {
    switch (saveStatus.state) {
      case "saving":
        return SETTINGS_SHELL_STRINGS.statusSaving;
      case "saved":
        return SETTINGS_SHELL_STRINGS.statusSaved;
      case "error":
        return saveStatus.message != null
          ? `${SETTINGS_SHELL_STRINGS.statusErrorPrefix}${saveStatus.message}`
          : SETTINGS_SHELL_STRINGS.statusErrorGeneric;
      default:
        return "";
    }
  });
</script>

<div class="shell" data-testid="settings-shell">
  <!-- Left nav rail -->
  <div
    class="shell__rail"
    role="tablist"
    aria-label="Settings sections"
    aria-orientation="vertical"
    tabindex="-1"
    onkeydown={handleRailKeydown}
    data-testid="settings-rail"
  >
    {#each sortedSections as section (section.id)}
      <button
        role="tab"
        class="shell__rail-item"
        class:shell__rail-item--active={section.id === activeSectionId}
        tabindex={tabIndex(section.id)}
        aria-selected={section.id === activeSectionId}
        aria-controls={`panel-${section.id}`}
        id={`tab-${section.id}`}
        onclick={() => selectSection(section.id)}
        data-testid={`rail-item-${section.id}`}
      >
        {section.label}
      </button>
    {/each}
  </div>

  <!-- Right content pane -->
  <div class="shell__content">
    {#each sortedSections as section (section.id)}
      {@const SectionComponent = section.component}
      <div
        role="tabpanel"
        id={`panel-${section.id}`}
        aria-labelledby={`tab-${section.id}`}
        class="shell__panel"
        class:shell__panel--hidden={section.id !== activeSectionId}
        data-testid={`panel-${section.id}`}
      >
        <SectionComponent onsaveStatus={handleSaveStatus} />
      </div>
    {/each}

    <!-- Save-status footer -->
    {#if saveStatus.state !== "idle"}
      <div
        class="shell__footer"
        class:shell__footer--error={saveStatus.state === "error"}
        role="status"
        aria-live="polite"
        data-testid="settings-save-status"
      >
        {footerText()}
      </div>
    {/if}
  </div>
</div>

<style>
  /* ---- Two-column shell layout ---- */
  .shell {
    display: grid;
    grid-template-columns: 12rem 1fr;
    min-height: 0;
    height: 100%;
  }

  /* ---- Left rail ---- */
  .shell__rail {
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
    padding: 1rem 0.5rem;
    border-right: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-1));
    overflow-y: auto;
  }
  .shell__rail-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.4rem 0.75rem;
    border-radius: 0.25rem;
    border: none;
    background: transparent;
    color: rgb(var(--bearings-fg-muted));
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
  }
  .shell__rail-item:hover {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-strong));
  }
  .shell__rail-item--active {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-strong));
    font-weight: 500;
  }

  /* ---- Right content area ---- */
  .shell__content {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    position: relative;
  }
  .shell__panel {
    padding: 1rem 1.5rem;
    max-width: 56rem;
  }
  .shell__panel--hidden {
    display: none;
  }

  /* ---- Save-status footer ---- */
  .shell__footer {
    padding: 0.5rem 1.5rem;
    font-size: 0.8125rem;
    color: #4ade80;
    border-top: 1px solid rgb(var(--bearings-border));
    background: rgb(var(--bearings-surface-1));
    position: sticky;
    bottom: 0;
  }
  .shell__footer--error {
    color: #f87171;
  }

  /* ---- Shared settings design tokens (global so child sections inherit) ---- */
  :global(.settings-page__group) {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  :global(.settings-page__heading) {
    font-size: 1.125rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-strong));
    margin: 0;
  }
  :global(.settings-page__lede) {
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
    margin: 0;
  }
  :global(.settings-page__error) {
    font-size: 0.8125rem;
    color: #f87171;
    margin: 0;
  }
  :global(.settings-defaults__form) {
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
  }
  :global(.settings-defaults__field) {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  :global(.settings-defaults__label) {
    font-size: 0.75rem;
    font-weight: 500;
    color: rgb(var(--bearings-fg-muted));
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  :global(.settings-defaults__select),
  :global(.settings-defaults__input) {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-strong));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.3rem 0.5rem;
    font: inherit;
    font-size: 0.8125rem;
    max-width: 24rem;
  }
  :global(.settings-defaults__actions) {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.25rem;
  }
  :global(.settings-defaults__save) {
    background: rgb(var(--bearings-accent));
    color: white;
    border: none;
    border-radius: 0.25rem;
    padding: 0.3rem 0.875rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
  }
  :global(.settings-defaults__save:disabled) {
    opacity: 0.5;
    cursor: not-allowed;
  }
  :global(.settings-defaults__saved) {
    font-size: 0.8125rem;
    color: #4ade80;
  }
  :global(.settings-defaults__error) {
    font-size: 0.8125rem;
    color: #f87171;
  }
</style>
