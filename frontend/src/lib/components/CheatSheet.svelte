<script lang="ts">
  import { collectMenuShortcuts } from '$lib/context-menu/shortcuts';
  import {
    chordSegments,
    groupedBindings,
    type BindingDef
  } from '$lib/keyboard/bindings';
  import { uiActions } from '$lib/stores/ui_actions.svelte';

  /**
   * Cheat-sheet rendered from the central keyboard registry
   * (`$lib/keyboard/bindings`). The registry is the single source of
   * truth — any binding added there shows up here, any binding removed
   * disappears here, and the chord text the user sees matches the
   * chord the dispatcher actually compares against. The legacy
   * "Conversation" / "Sessions" / "Context menu" sections that aren't
   * in the registry yet stay below the registry-driven groups; they
   * document mouse + composer-only chords that don't go through the
   * dispatcher.
   *
   * `open` state lives on the shared `uiActions` store so the
   * keyboard registry's `?` and `Esc` actions can flip it without a
   * prop-drill round trip through the page layout. `bind:` doesn't
   * accept class-field accessors cleanly under Svelte 5 runes, so
   * the component reads and writes the store directly.
   */

  type StaticShortcut = { keys: string[]; description: string };
  type StaticGroup = { group: string; items: StaticShortcut[] };

  // Mouse + composer-only chords stay hand-listed because they don't
  // route through the keyboard registry (no document-level keydown
  // dispatch covers them). When/if a click handler graduates to a
  // registry binding, move the row up to the registry-driven section.
  const staticGroups: StaticGroup[] = [
    {
      group: 'Context menu',
      items: [
        { keys: ['Right-click'], description: 'Open the target’s menu' },
        {
          keys: ['Shift', 'Right-click'],
          description: 'Open with advanced actions revealed'
        },
        {
          keys: ['Ctrl', 'Shift', 'Right-click'],
          description: 'Passthrough to the browser’s native menu'
        },
        {
          keys: ['Long-press'],
          description: '500ms touch-hold on coarse pointers'
        },
        { keys: ['↑', '↓'], description: 'Move focus between menu items' },
        { keys: ['→', '←'], description: 'Open / close submenus' },
        { keys: ['Enter'], description: 'Activate the focused item' }
      ]
    },
    {
      group: 'Conversation',
      items: [
        { keys: ['Enter'], description: 'Send the prompt' },
        { keys: ['Shift', 'Enter'], description: 'Newline inside the prompt' },
        { keys: ['/plan'], description: 'Toggle plan mode (append "off" to exit)' }
      ]
    },
    {
      group: 'Sessions (mouse)',
      items: [
        { keys: ['Double-click', 'title'], description: 'Rename a session' },
        { keys: ['✎'], description: 'Edit title or budget in the header' },
        { keys: ['⚙'], description: 'Open Settings (token + defaults)' },
        { keys: ['✕'], description: 'Delete a session (click twice to confirm)' }
      ]
    }
  ];

  const registryGroups = $derived.by(() => groupedBindings());

  // User-bound chords from `menus.toml` (Phase 13 of the context-menu
  // plan). Renders nothing when empty so users who haven't touched the
  // TOML don't see a dead "Your shortcuts" header.
  const userShortcuts = $derived.by(() => collectMenuShortcuts());

  function legacySplitChord(chord: string): string[] {
    return chord
      .split('+')
      .map((p) => p.trim())
      .filter((p) => p.length > 0)
      .map((p) => (p === 'ctrl' ? '⌘/Ctrl' : p.charAt(0).toUpperCase() + p.slice(1)));
  }

  function bindingKeys(b: BindingDef): string[] {
    // Normalise `Ctrl` to `⌘/Ctrl` for the renderer so Mac visitors
    // recognise the binding works under Cmd as well. The dispatcher
    // already accepts both modifiers; this is purely cosmetic.
    return chordSegments(b.chord).map((seg) =>
      seg === 'Ctrl' ? '⌘/Ctrl' : seg
    );
  }

  function onCancel() {
    uiActions.cheatSheetOpen = false;
  }
</script>

{#if uiActions.cheatSheetOpen}
  <div class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4">
    <div
      class="w-full max-w-md rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-2xl
        flex flex-col gap-4 max-h-[90vh] overflow-y-auto"
    >
      <header class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-medium">Shortcuts</h2>
          <p class="text-xs text-slate-400 mt-1">
            Esc or <kbd class="kbd">?</kbd> to close.
          </p>
        </div>
        <button
          type="button"
          class="text-slate-500 hover:text-slate-300 text-sm"
          aria-label="Close cheat sheet"
          onclick={onCancel}
        >
          ✕
        </button>
      </header>

      <div class="flex flex-col gap-4 text-sm">
        {#each registryGroups as group (group.group)}
          <section>
            <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
              {group.group}
            </h3>
            <ul class="flex flex-col gap-1">
              {#each group.items as b (b.id)}
                <li class="flex items-baseline justify-between gap-3">
                  <span class="text-slate-300">{b.label}</span>
                  <span class="flex gap-1 shrink-0">
                    {#each bindingKeys(b) as k}
                      <kbd class="kbd">{k}</kbd>
                    {/each}
                  </span>
                </li>
              {/each}
            </ul>
          </section>
        {/each}

        {#each staticGroups as group (group.group)}
          <section>
            <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
              {group.group}
            </h3>
            <ul class="flex flex-col gap-1">
              {#each group.items as sc}
                <li class="flex items-baseline justify-between gap-3">
                  <span class="text-slate-300">{sc.description}</span>
                  <span class="flex gap-1 shrink-0">
                    {#each sc.keys as k}
                      <kbd class="kbd">{k}</kbd>
                    {/each}
                  </span>
                </li>
              {/each}
            </ul>
          </section>
        {/each}

        {#if userShortcuts.length > 0}
          <section>
            <h3 class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
              Your shortcuts (menus.toml)
            </h3>
            <ul class="flex flex-col gap-1">
              {#each userShortcuts as entry (entry.target + ':' + entry.id)}
                <li class="flex items-baseline justify-between gap-3">
                  <span class="text-slate-300">
                    {entry.label}
                    <span class="text-slate-500 text-xs">· {entry.target}</span>
                  </span>
                  <span class="flex gap-1 shrink-0">
                    {#each legacySplitChord(entry.chord) as seg}
                      <kbd class="kbd">{seg}</kbd>
                    {/each}
                  </span>
                </li>
              {/each}
            </ul>
          </section>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .kbd {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.6875rem;
    background-color: rgb(15 23 42);
    color: rgb(226 232 240);
    border: 1px solid rgb(51 65 85);
    border-radius: 0.25rem;
    padding: 0.05rem 0.35rem;
  }
</style>
