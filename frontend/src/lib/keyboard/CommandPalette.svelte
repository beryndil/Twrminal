<script lang="ts">
  /**
   * Global command palette — opened by ``Ctrl+Shift+P``.
   *
   * Behavior anchors:
   *
   * - ``docs/behavior/keyboard-shortcuts.md`` §"Command palette" —
   *   ``Ctrl+Shift+P`` toggles the palette; Escape closes it.
   * - ``docs/behavior/chat.md`` §"Slash commands in the composer" —
   *   selecting a command inserts ``/name`` into the active composer
   *   via :func:`pasteIntoComposer`.
   *
   * The command list is fetched once on first open and then cached
   * for the lifetime of the component. A fetch failure silently
   * produces an empty list — the palette degrades gracefully.
   *
   * String literals — :data:`COMMAND_PALETTE_STRINGS` in
   * ``../../config``.
   */
  import { listCommands, type CommandOut } from "../api/commands";
  import { COMMAND_PALETTE_STRINGS } from "../config";
  import { pasteIntoComposer } from "../stores/composerBridge.svelte";

  interface Props {
    open: boolean;
    onClose: () => void;
    /** Active session id — used to route the insertion via composerBridge. */
    sessionId: string | null;
  }

  const { open, onClose, sessionId }: Props = $props();

  let allCommands = $state<CommandOut[]>([]);
  let query = $state("");
  let activeIndex = $state(0);
  let inputEl = $state<HTMLInputElement | null>(null);
  let listEl = $state<HTMLUListElement | null>(null);
  let fetched = $state(false);

  // Fetch once on first open.
  $effect(() => {
    if (open && !fetched) {
      fetched = true;
      void listCommands().then((cmds) => {
        allCommands = cmds;
      });
    }
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
    if (q === "") return allCommands;
    return allCommands.filter(
      (c) => c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q),
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

  /** Insert the selected command into the active composer and close. */
  function confirmActive(): void {
    const entry = filtered[activeIndex];
    if (entry === undefined) return;
    if (sessionId !== null) {
      pasteIntoComposer({ sessionId, text: `/${entry.name} `, kind: "link" });
    }
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

  /** Source badge label — falls back to the raw source string. */
  function sourceLabel(source: string): string {
    return COMMAND_PALETTE_STRINGS.sourceLabels[source] ?? source;
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
          {#each filtered as cmd, idx (cmd.name)}
            <li
              class="flex cursor-pointer items-start gap-3 rounded px-3 py-2 text-sm"
              class:bg-surface-2={idx === activeIndex}
              role="option"
              aria-selected={idx === activeIndex}
              data-testid="command-palette-item"
              data-command-name={cmd.name}
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
              <span class="font-mono text-accent">/{cmd.name}</span>
              <span class="flex-1 text-fg-muted">{cmd.description}</span>
              <span class="shrink-0 rounded bg-surface-2 px-1 text-xs text-fg-muted">
                {sourceLabel(cmd.source)}
              </span>
            </li>
          {/each}
        {/if}
      </ul>
    </div>
  </div>
{/if}
