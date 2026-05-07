<script lang="ts">
  /**
   * Cheat-sheet modal — renders the full v1 binding table grouped by
   * section per ``docs/behavior/keyboard-shortcuts.md`` §"What the
   * user sees". The modal opens on ``?``; ``Esc`` closes via the
   * cascade.
   *
   * Two source tables are rendered:
   *
   * 1. :data:`KEYBINDINGS` — the global registry that wires the
   *    dispatcher (registry sections).
   * 2. :data:`NON_REGISTRY_SECTIONS` — context-local chords wired by
   *    individual components (composer, checklist, context menu) that
   *    are not in the global registry.  Colocated here so adding a
   *    row only requires editing this folder.
   */
  import { onMount } from "svelte";

  import { KEYBOARD_SHORTCUT_STRINGS } from "../config";
  import { KEYBINDINGS, KEYBINDING_SECTION_ORDER } from "./bindings";
  import { ESC_PRIORITY_OVERLAY, registerEscEntry } from "./escCascade";
  import { NON_REGISTRY_SECTIONS } from "./nonRegistryBindings";

  interface Props {
    /** Open / closed flag. Driven by the keybindings provider. */
    open: boolean;
    /** Close callback — invoked from the cascade + the close button. */
    onClose: () => void;
  }

  const { open, onClose }: Props = $props();

  // Group bindings by section, preserving the doc's section order.
  const sectionedBindings = $derived(
    KEYBINDING_SECTION_ORDER.map((section) => ({
      section,
      label:
        KEYBOARD_SHORTCUT_STRINGS.sectionLabels[
          section as keyof typeof KEYBOARD_SHORTCUT_STRINGS.sectionLabels
        ],
      bindings: KEYBINDINGS.filter((b) => b.section === section),
    })),
  );

  function actionLabel(actionId: string): string {
    const map = KEYBOARD_SHORTCUT_STRINGS.actionLabels as Record<string, string>;
    return (
      map[actionId] ??
      KEYBOARD_SHORTCUT_STRINGS.jumpToSlotLabelTemplate.replace(
        "{n}",
        actionId.replace(/^.*_(\d+)$/, "$1"),
      )
    );
  }

  onMount(() => {
    return registerEscEntry({
      priority: ESC_PRIORITY_OVERLAY,
      isOpen: () => open,
      close: onClose,
    });
  });
</script>

{#if open}
  <div
    class="cheat-sheet-backdrop"
    role="presentation"
    data-testid="cheat-sheet-backdrop"
    onclick={onClose}
    onkeydown={(event) => {
      if (event.key === "Enter" || event.key === " ") onClose();
    }}
  >
    <div
      class="cheat-sheet"
      role="dialog"
      tabindex="-1"
      aria-label={KEYBOARD_SHORTCUT_STRINGS.cheatSheetAriaLabel}
      data-testid="cheat-sheet"
      onclick={(event) => event.stopPropagation()}
      onkeydown={(event) => event.stopPropagation()}
    >
      <header class="cheat-sheet__header">
        <h2 class="cheat-sheet__title">{KEYBOARD_SHORTCUT_STRINGS.cheatSheetTitle}</h2>
        <button
          type="button"
          class="cheat-sheet__close"
          data-testid="cheat-sheet-close"
          aria-label={KEYBOARD_SHORTCUT_STRINGS.cheatSheetCloseLabel}
          onclick={onClose}
        >
          ×
        </button>
      </header>
      <div class="cheat-sheet__body">
        {#each sectionedBindings as group (group.section)}
          {#if group.bindings.length > 0}
            <section
              class="cheat-sheet__section"
              data-testid="cheat-sheet-section"
              data-section={group.section}
            >
              <h3 class="cheat-sheet__section-heading">{group.label}</h3>
              <ul class="cheat-sheet__list">
                {#each group.bindings as binding (binding.id)}
                  <li
                    class="cheat-sheet__row"
                    data-testid="cheat-sheet-row"
                    data-action={binding.id}
                  >
                    <span class="cheat-sheet__chord" data-testid="cheat-sheet-chord">
                      {#each binding.chord.display as cap, i (i)}
                        <kbd>{cap}</kbd>
                      {/each}
                    </span>
                    <span class="cheat-sheet__label">{actionLabel(binding.id)}</span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}
        {/each}
        {#each NON_REGISTRY_SECTIONS as group (group.id)}
          {#if group.bindings.length > 0}
            <section
              class="cheat-sheet__section"
              data-testid="cheat-sheet-section"
              data-section={group.id}
            >
              <h3 class="cheat-sheet__section-heading">{group.heading}</h3>
              <ul class="cheat-sheet__list">
                {#each group.bindings as binding, i (i)}
                  <li
                    class="cheat-sheet__row"
                    data-testid="cheat-sheet-row"
                  >
                    <span class="cheat-sheet__chord" data-testid="cheat-sheet-chord">
                      {#each binding.keys as cap, j (j)}
                        <kbd>{cap}</kbd>
                      {/each}
                    </span>
                    <span class="cheat-sheet__label">{binding.label}</span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .cheat-sheet-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 90;
  }
  .cheat-sheet {
    background: rgb(var(--bearings-surface-1));
    color: rgb(var(--bearings-fg));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    width: min(36rem, calc(100vw - 2rem));
    max-height: calc(100vh - 4rem);
    overflow-y: auto;
    padding: 1rem;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
  }
  .cheat-sheet__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgb(var(--bearings-border));
    padding-bottom: 0.5rem;
    margin-bottom: 0.5rem;
  }
  .cheat-sheet__title {
    font-size: 1rem;
    font-weight: 600;
    color: rgb(var(--bearings-fg-strong));
  }
  .cheat-sheet__close {
    background: transparent;
    border: none;
    color: inherit;
    font-size: 1.25rem;
    cursor: pointer;
  }
  .cheat-sheet__section {
    margin-top: 0.75rem;
  }
  .cheat-sheet__section-heading {
    font-size: 0.875rem;
    font-weight: 600;
    margin-bottom: 0.25rem;
    color: rgb(var(--bearings-fg-strong));
  }
  .cheat-sheet__list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .cheat-sheet__row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.25rem 0;
    font-size: 0.875rem;
  }
  .cheat-sheet__chord {
    display: flex;
    gap: 0.25rem;
    flex-shrink: 0;
    min-width: 7rem;
  }
  .cheat-sheet__chord kbd {
    background: rgb(var(--bearings-surface-2));
    color: rgb(var(--bearings-fg-strong));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.125rem 0.375rem;
    font-family: inherit;
    font-size: 0.75rem;
  }
  .cheat-sheet__label {
    color: rgb(var(--bearings-fg-muted));
  }
</style>
