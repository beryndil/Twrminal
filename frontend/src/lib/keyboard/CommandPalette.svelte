<script lang="ts">
  /**
   * Global command palette — opened by ``Ctrl+Shift+P``.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/keyboard-shortcuts.md`` §"Command palette" —
   *   ``Ctrl+Shift+P`` toggles the palette; Escape closes it.
   * - The action list is sourced from the context-menu registry
   *   (:func:`allPaletteActions`) so every right-click-reachable action
   *   id is reachable from the palette by label.
   * - Activating a row calls the handler registered via
   *   :func:`registerPaletteHandler` / :func:`getPaletteHandler`.
   *   Rows with no registered handler are shown but do nothing on
   *   activation — they remain visible for discoverability.
   *
   * String literals — :data:`COMMAND_PALETTE_STRINGS` in
   * ``../../config``.
   */
  import { COMMAND_PALETTE_STRINGS } from "../config";
  import { allPaletteActions, getPaletteHandler, type PaletteEntry } from "../context-menu/palette";

  interface Props {
    open: boolean;
    onClose: () => void;
  }

  const { open, onClose }: Props = $props();

  const allActions: readonly PaletteEntry[] = allPaletteActions();

  let query = $state("");
  let activeIndex = $state(0);
  let inputEl = $state<HTMLInputElement | null>(null);
  let listEl = $state<HTMLUListElement | null>(null);

  $effect(() => {
    if (open) {
      query = "";
      activeIndex = 0;
      // Focus the search input after Svelte renders.
      requestAnimationFrame(() => {
        inputEl?.focus();
      });
    }
  });

  const filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (q === "") return allActions;
    return allActions.filter(
      (entry) => entry.label.toLowerCase().includes(q) || entry.id.toLowerCase().includes(q),
    );
  });

  $effect(() => {
    if (activeIndex >= filtered.length) {
      activeIndex = Math.max(0, filtered.length - 1);
    }
  });

  $effect(() => {
    if (listEl === null) return;
    const row = listEl.children[activeIndex] as HTMLElement | undefined;
    row?.scrollIntoView?.({ block: "nearest" });
  });

  /** Fire the highlighted action and close the palette. */
  function confirmActive(): void {
    const entry = filtered[activeIndex];
    if (entry === undefined) return;
    getPaletteHandler(entry.id)?.();
    onClose();
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      confirmActive();
      return;
    }
  }
</script>

{#if open}
  <!-- Backdrop — uses <dialog> semantics via tabindex+role per svelte a11y -->
  <div
    class="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-24"
    data-testid="command-palette-backdrop"
    role="dialog"
    aria-modal="true"
    aria-label={COMMAND_PALETTE_STRINGS.ariaLabel}
    tabindex="-1"
    onclick={() => onClose()}
    onkeydown={(e) => {
      if (e.key === "Escape") onClose();
    }}
  >
    <!-- Panel — stop propagation so clicks inside don't close -->
    <div
      class="flex w-full max-w-lg flex-col rounded-lg border border-border bg-surface-1 shadow-2xl"
      data-testid="command-palette-panel"
      role="presentation"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <!-- Header -->
      <div class="flex items-center gap-2 border-b border-border px-3 py-2">
        <span class="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          {COMMAND_PALETTE_STRINGS.title}
        </span>
      </div>

      <!-- Search input -->
      <div class="border-b border-border px-3 py-2">
        <input
          bind:this={inputEl}
          type="search"
          class="w-full bg-transparent text-sm text-fg-strong outline-none placeholder:text-fg-muted"
          placeholder={COMMAND_PALETTE_STRINGS.searchPlaceholder}
          bind:value={query}
          onkeydown={handleKeydown}
          data-testid="command-palette-search"
          autocomplete="off"
          spellcheck="false"
        />
      </div>

      <!-- Results list -->
      <ul
        bind:this={listEl}
        class="max-h-64 overflow-y-auto py-1"
        data-testid="command-palette-list"
        role="listbox"
        aria-label={COMMAND_PALETTE_STRINGS.ariaLabel}
      >
        {#if filtered.length === 0}
          <li class="px-3 py-2 text-sm text-fg-muted" data-testid="command-palette-no-results">
            {COMMAND_PALETTE_STRINGS.noResults}
          </li>
        {:else}
          {#each filtered as entry, idx (entry.id)}
            <li
              class="flex cursor-pointer items-center gap-3 rounded px-3 py-2 text-sm"
              class:bg-surface-2={idx === activeIndex}
              role="option"
              aria-selected={idx === activeIndex}
              data-testid="command-palette-item"
              data-action-id={entry.id}
              onclick={() => {
                activeIndex = idx;
                confirmActive();
              }}
              onkeydown={(e) => {
                if (e.key === "Enter") {
                  activeIndex = idx;
                  confirmActive();
                }
              }}
              onmouseenter={() => {
                activeIndex = idx;
              }}
            >
              <span class="flex-1 text-fg-strong">{entry.label}</span>
              <span class="shrink-0 font-mono text-xs text-fg-muted">{entry.id}</span>
            </li>
          {/each}
        {/if}
      </ul>
    </div>
  </div>
{/if}
