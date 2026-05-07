<script lang="ts">
  /**
   * Slash-command typeahead palette (item 2.3).
   *
   * Behavior anchors:
   *
   * - Displayed when the user types ``/`` in the composer textarea.
   * - Filters the full command list by the text typed after ``/``
   *   (case-insensitive prefix + substring match on name and description).
   * - Arrow-Up / Arrow-Down navigate the list; Tab / Enter confirm the
   *   selected item; Escape dismisses without inserting.
   * - Selection emits ``select`` with the full ``/<name>`` string so the
   *   parent can splice it into the textarea value at the right position.
   *
   * The command list is fetched once on first mount (lazy) and then cached
   * for the component's lifetime.  A fetch failure silently produces an
   * empty list — the palette is a convenience feature, not a blocker.
   *
   * String literals — ``COMMAND_MENU_STRINGS`` in ``../../config``.
   */
  import { listCommands, type CommandOut } from "../../api/commands";
  import { COMMAND_MENU_STRINGS } from "../../config";

  interface Props {
    /**
     * Text typed after the leading ``/`` — used to filter the list.
     * An empty string shows all commands.
     */
    query: string;
    /**
     * Working directory of the active session. When provided it is
     * forwarded to ``GET /api/commands?cwd=<path>`` so project-level
     * commands are scoped to this session rather than the server's
     * launch directory (gap-cycle-13-005).
     *
     * Changing this prop (e.g. the user switches sessions while the
     * menu is open) triggers an immediate re-fetch so the list always
     * reflects the current session's project commands.
     */
    workingDir?: string | null;
    /** Called when the user confirms a selection.  Argument is the
     *  full ``/<name>`` insertion string. */
    onselect: (insertion: string) => void;
    /** Called when the user presses Escape — parent should close the
     *  menu and leave the textarea draft unchanged. */
    onclose: () => void;
  }

  const { query, workingDir = null, onselect, onclose }: Props = $props();

  // Full command list — fetched on mount and whenever workingDir changes.
  let allCommands = $state<CommandOut[]>([]);
  // Index of the highlighted row (-1 = none highlighted).
  let activeIndex = $state(0);
  // Ref to the scrollable list container for scroll-into-view.
  let listEl = $state<HTMLUListElement | null>(null);

  // Re-fetch whenever the working directory changes so the project-commands
  // section reflects the correct session scope. A cancellation flag prevents
  // a slow response from a previous cwd from overwriting a faster one.
  $effect(() => {
    const dir = workingDir;
    let cancelled = false;
    void listCommands(dir).then((cmds) => {
      if (!cancelled) allCommands = cmds;
    });
    return () => {
      cancelled = true;
    };
  });

  // Filtered list derived from query.
  const filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (q === "") return allCommands;
    return allCommands.filter(
      (c) => c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q),
    );
  });

  // Clamp activeIndex whenever the filtered list changes.
  $effect(() => {
    if (activeIndex >= filtered.length) {
      activeIndex = Math.max(0, filtered.length - 1);
    }
  });

  // Scroll the active row into view when it changes.
  $effect(() => {
    if (listEl === null) return;
    const row = listEl.children[activeIndex] as HTMLElement | undefined;
    row?.scrollIntoView({ block: "nearest" });
  });

  /** Confirm the currently highlighted entry. */
  function confirmActive(): void {
    const entry = filtered[activeIndex];
    if (entry === undefined) return;
    onselect(`/${entry.name}`);
  }

  /** Public keyboard handler — called by Composer for every keydown while
   *  the menu is open. Returns ``true`` when the key was consumed. */
  export function handleKey(event: KeyboardEvent): boolean {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
        return true;
      case "ArrowUp":
        event.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        return true;
      case "Tab":
      case "Enter":
        event.preventDefault();
        confirmActive();
        return true;
      case "Escape":
        event.preventDefault();
        onclose();
        return true;
      default:
        return false;
    }
  }

  function sourceLabel(source: string): string {
    return COMMAND_MENU_STRINGS.sourceLabels[source] ?? source;
  }
</script>

<!--
  The menu floats above the textarea — positioned by the parent via CSS.
  ``role="listbox"`` matches the ``combobox`` pattern; each option has
  ``role="option"`` and ``aria-selected`` reflecting the active state.
-->
<div
  class="command-menu absolute bottom-full left-0 z-50 mb-1 w-full rounded border border-border bg-surface-1 shadow-lg"
  aria-label={COMMAND_MENU_STRINGS.ariaLabel}
  role="listbox"
  data-testid="command-menu"
>
  {#if filtered.length === 0}
    <p class="px-3 py-2 text-xs text-fg-muted" data-testid="command-menu-empty">
      {COMMAND_MENU_STRINGS.noResults}
    </p>
  {:else}
    <ul bind:this={listEl} class="max-h-56 overflow-y-auto" data-testid="command-menu-list">
      {#each filtered as cmd, i (cmd.name + cmd.source)}
        <li
          class="flex cursor-pointer items-start gap-2 px-3 py-2 text-sm transition-colors {i ===
          activeIndex
            ? 'bg-accent/20 text-fg-strong'
            : 'text-fg-base hover:bg-surface-2'}"
          role="option"
          aria-selected={i === activeIndex}
          data-testid="command-menu-item"
          onmouseenter={() => {
            activeIndex = i;
          }}
          onclick={() => {
            activeIndex = i;
            confirmActive();
          }}
          onkeydown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              activeIndex = i;
              confirmActive();
            }
          }}
        >
          <span class="min-w-0 flex-1">
            <span class="block font-mono font-medium">/{cmd.name}</span>
            {#if cmd.description}
              <span class="block truncate text-xs text-fg-muted">{cmd.description}</span>
            {/if}
          </span>
          <span class="mt-0.5 shrink-0 rounded bg-surface-2 px-1 py-0.5 text-[10px] text-fg-muted">
            {sourceLabel(cmd.source)}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</div>
