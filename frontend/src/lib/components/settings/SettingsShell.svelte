<script lang="ts">
  /** The two-column shell that hosts the Settings dialog: a left nav
   * rail listing every section in the registry, and a content pane
   * that renders the active section's component. The dialog frame
   * (modal backdrop, header, close button, footer) is the consumer's
   * responsibility — this shell is just the inner layout.
   *
   * Active-section state lives in this component (not in a store):
   * the dialog only has one instance live at a time, and component
   * state is the smallest scope that does the job. URL-based
   * routing (?settings=<id>) is a follow-up.
   *
   * The left rail is keyboard-navigable: ↑/↓ moves the active row,
   * Home/End jump to the ends. Each rail item is a `<button>` so
   * the native focus model and Tab order Just Work.
   */
  import { SETTINGS_SECTIONS } from './sections';

  /** Default to the first section in the registry. URL routing
   * (`?settings=<id>`) is a follow-up; for now consumers always
   * land on the first pane. */
  let activeId = $state(SETTINGS_SECTIONS[0].id);
  const active = $derived(
    SETTINGS_SECTIONS.find((s) => s.id === activeId) ?? SETTINGS_SECTIONS[0]
  );
  // Lifted out of the template because Svelte 5 only allows
  // `{@const}` immediately inside a few specific block parents (none
  // of which are a plain `<section>`). `$derived` here gives us the
  // same per-render assignment without the placement constraint.
  const ActiveComponent = $derived(active.component);

  /** Move the active row by ±1 (clamped). Used by the keyboard
   * handler on the rail to map ↑/↓ to section navigation. */
  function move(delta: number): void {
    const idx = SETTINGS_SECTIONS.findIndex((s) => s.id === activeId);
    const next = Math.max(0, Math.min(SETTINGS_SECTIONS.length - 1, idx + delta));
    activeId = SETTINGS_SECTIONS[next].id;
  }

  function onRailKey(e: KeyboardEvent): void {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        move(1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        move(-1);
        break;
      case 'Home':
        e.preventDefault();
        activeId = SETTINGS_SECTIONS[0].id;
        break;
      case 'End':
        e.preventDefault();
        activeId = SETTINGS_SECTIONS[SETTINGS_SECTIONS.length - 1].id;
        break;
    }
  }
</script>

<div
  class="flex flex-row min-h-[28rem] max-h-[36rem]"
  data-testid="settings-shell"
>
  <!-- Left nav rail. role="tablist" + role="tab" gives screen
       readers the right model: each rail item is a tab; the content
       pane is the corresponding tabpanel. We use a plain <div>
       rather than <nav> because the tablist role overrides the
       landmark role <nav> implies, and Svelte's a11y linter rightly
       refuses the conflict. -->
  <div
    class="w-48 shrink-0 border-r border-slate-800 bg-slate-950/40 py-2"
    role="tablist"
    aria-label="Settings sections"
    aria-orientation="vertical"
    tabindex="-1"
    onkeydown={onRailKey}
  >
    {#each SETTINGS_SECTIONS as section (section.id)}
      <button
        type="button"
        role="tab"
        aria-selected={activeId === section.id}
        aria-controls="settings-pane-{section.id}"
        tabindex={activeId === section.id ? 0 : -1}
        class="w-full text-left px-4 py-2 text-sm transition-colors
          focus:outline-none focus:bg-slate-800/60
          {activeId === section.id
            ? 'bg-slate-800/80 text-slate-100 border-l-2 border-sky-400'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border-l-2 border-transparent'}"
        onclick={() => (activeId = section.id)}
        data-testid="settings-rail-{section.id}"
      >
        {section.label}
      </button>
    {/each}
  </div>

  <!-- Content pane. role="tabpanel" matches the tablist role above.
       Plain <div> rather than <section> because the tabpanel role
       overrides the section landmark and Svelte's a11y linter
       refuses the conflict. Scrolls independently of the rail so
       long sections don't push the rail off-screen. -->
  <div
    id="settings-pane-{active.id}"
    role="tabpanel"
    aria-labelledby="settings-rail-{active.id}"
    tabindex="0"
    class="flex-1 overflow-y-auto p-6"
    data-testid="settings-pane"
  >
    <header class="mb-4">
      <h2 class="text-base font-semibold text-slate-100">{active.label}</h2>
      {#if active.description}
        <p class="text-xs text-slate-400 mt-1">{active.description}</p>
      {/if}
    </header>

    <ActiveComponent />
  </div>
</div>
