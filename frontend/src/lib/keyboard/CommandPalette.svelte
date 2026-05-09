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
  import { onMount } from "svelte";

  import { COMMAND_PALETTE_STRINGS } from "../config";
  import { allPaletteActions, getPaletteHandler, type PaletteEntry } from "../context-menu/palette";
  import { ESC_PRIORITY_COMMAND_PALETTE, registerEscEntry } from "./escCascade";
  import { listCommands, type CommandOut } from "../api/commands";
  import { pasteIntoComposer } from "../stores/composerBridge.svelte";
  import { inspectorStore } from "../stores/inspector.svelte";

  interface Props {
    open: boolean;
    onClose: () => void;
    /**
     * Working directory of the active session. When provided it is
     * forwarded to ``GET /api/commands?cwd=<path>`` so the
     * project-commands section lists commands scoped to this session.
     * Changing this prop (e.g. the user switches sessions) triggers a
     * re-fetch so the list stays current (gap-cycle-13-005).
     */
    workingDir?: string | null;
  }

  const { open, onClose, workingDir = null }: Props = $props();

  const allActions: readonly PaletteEntry[] = allPaletteActions();

  // ---------------------------------------------------------------------------
  // Slash commands — fetched from /api/commands with per-session cwd scope.
  // Re-fetches whenever workingDir changes (session switch) or on first open.
  // ---------------------------------------------------------------------------

  /** Commands fetched from the API, scoped to the current session's cwd. */
  let slashCommands = $state<CommandOut[]>([]);

  $effect(() => {
    const dir = workingDir;
    let cancelled = false;
    void listCommands(dir).then((cmds) => {
      if (!cancelled) slashCommands = cmds;
    });
    return () => {
      cancelled = true;
    };
  });

  // Register with the global Esc cascade (priority 2) so pressing Esc
  // closes the palette even when focus has moved off the search input.
  // The local onkeydown handler on the input remains as defence-in-depth.
  onMount(() => {
    return registerEscEntry({
      priority: ESC_PRIORITY_COMMAND_PALETTE,
      isOpen: () => open,
      close: onClose,
    });
  });

  let query = $state("");
  let activeIndex = $state(0);
  let inputEl = $state<HTMLInputElement | null>(null);
  let listEl = $state<HTMLUListElement | null>(null);
  let panelEl = $state<HTMLElement | null>(null);

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

  // ---------------------------------------------------------------------------
  // Unified item list — palette actions + slash commands merged for display.
  // ---------------------------------------------------------------------------

  /** Discriminated union covering both action entries and slash commands. */
  type PaletteItem =
    | { kind: "action"; id: string; label: string }
    | { kind: "command"; id: string; label: string; source: string };

  /**
   * Flat merged list of all available items — action entries from the
   * context-menu registry followed by slash commands from the API.
   */
  const allItems = $derived.by((): PaletteItem[] => {
    const actions: PaletteItem[] = allActions.map((a) => ({
      kind: "action",
      id: a.id,
      label: a.label,
    }));
    const commands: PaletteItem[] = slashCommands.map((c) => ({
      kind: "command",
      id: `cmd:${c.name}`,
      label: `/${c.name}`,
      source: c.source,
    }));
    return [...actions, ...commands];
  });

  const filtered = $derived.by((): PaletteItem[] => {
    const q = query.trim().toLowerCase();
    if (q === "") return allItems;
    return allItems.filter(
      (item) => item.label.toLowerCase().includes(q) || item.id.toLowerCase().includes(q),
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

  /** Fire the highlighted item and close the palette. */
  function confirmActive(): void {
    const item = filtered[activeIndex];
    if (item === undefined) return;
    if (item.kind === "action") {
      getPaletteHandler(item.id)?.();
    } else {
      // Slash command: paste into the active session's composer so the
      // user can supply arguments before sending.  The consumption side
      // in Composer reads composerBridgeStore.pending (gap pending full
      // wire-up — see composerBridge.svelte.ts).
      const sessionId = inspectorStore.activeSessionId;
      if (sessionId !== null) {
        pasteIntoComposer({ sessionId, text: item.label + " ", kind: "link" });
      }
    }
    onClose();
  }

  /**
   * Panel-level keydown handler. Traps Tab/Shift+Tab within the panel
   * for WCAG 2.4.3 focus management (KBD-15). Does NOT call
   * ``stopPropagation`` for non-Tab keys so that global chords like
   * ``Ctrl+Shift+P`` can reach the window-level ``KeybindingsProvider``
   * listener — the missing propagation was KBD-53's root cause.
   */
  function handlePanelKeyDown(event: KeyboardEvent): void {
    if (event.key !== "Tab") return;
    const focusable =
      panelEl !== null
        ? Array.from(
            panelEl.querySelectorAll<HTMLElement>(
              'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
            ),
          ).filter((el) => !el.hasAttribute("disabled"))
        : [];
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    if (event.shiftKey) {
      if (document.activeElement === first) {
        event.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
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
    if (event.key === "Home") {
      event.preventDefault();
      if (filtered.length > 0) activeIndex = 0;
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      if (filtered.length > 0) activeIndex = filtered.length - 1;
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
    <!-- Panel — stop click propagation so backdrop-click doesn't close;
         keydown is handled by handlePanelKeyDown (Tab trap only). -->
    <div
      class="flex w-full max-w-lg flex-col rounded-lg border border-border bg-surface-1 shadow-2xl"
      data-testid="command-palette-panel"
      role="presentation"
      bind:this={panelEl}
      onclick={(e) => e.stopPropagation()}
      onkeydown={handlePanelKeyDown}
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
          {#each filtered as item, idx (item.id)}
            <li
              class="flex cursor-pointer items-center gap-3 rounded px-3 py-2 text-sm"
              class:bg-surface-2={idx === activeIndex}
              role="option"
              aria-selected={idx === activeIndex}
              data-testid="command-palette-item"
              data-action-id={item.id}
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
              <span class="flex-1 text-fg-strong">{item.label}</span>
              {#if item.kind === "action"}
                <span class="shrink-0 font-mono text-xs text-fg-muted">{item.id}</span>
              {:else}
                <span class="shrink-0 rounded bg-surface-2 px-1 py-0.5 text-[10px] text-fg-muted">
                  {item.source}
                </span>
              {/if}
            </li>
          {/each}
        {/if}
      </ul>
    </div>
  </div>
{/if}
