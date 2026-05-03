<script lang="ts">
  /**
   * FolderPicker.svelte — directory browser widget (item 3.1).
   *
   * Renders as a compact field showing the current working-directory
   * value with a "Browse…" button.  Activating the button (click,
   * Enter, or Space) opens a full-screen overlay with an interactive
   * filesystem tree.
   *
   * Overlay keyboard contract (done-when §3.1):
   *   ArrowDown / ArrowUp  — move the highlighted entry.
   *   Enter on highlighted dir  — navigate into it.
   *   Enter with no highlight   — select the currently displayed path.
   *   Tab                  — auto-complete the filter to the first match.
   *   Backspace on empty filter — navigate up one level.
   *   Esc                  — close without changing the value.
   *   "Select" button      — confirm the currently displayed directory.
   *
   * Navigation uses ``POST /api/fs/pick`` for every step so each call
   * validates the path server-side.  The component shows directories
   * only by default (working-dir picker) and filters via a typed
   * prefix input.
   */

  import { pickDir, type FsEntry } from "../../api/fs";
  import { ApiError } from "../../api/client";

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  interface Props {
    /** Currently selected directory path (controlled by the parent). */
    value: string;
    /** Called when the user confirms a new path. */
    onchange: (path: string) => void;
  }

  const { value, onchange }: Props = $props();

  // ---------------------------------------------------------------------------
  // Overlay open / closed state
  // ---------------------------------------------------------------------------

  let open = $state(false);

  function openPicker(): void {
    open = true;
    // Defer so the overlay is rendered before we try to focus the filter.
    setTimeout(() => filterEl?.focus(), 0);
    void navigate(value || "");
  }

  function closePicker(): void {
    open = false;
  }

  function confirmSelection(): void {
    onchange(currentPath);
    closePicker();
  }

  // ---------------------------------------------------------------------------
  // Picker internal state
  // ---------------------------------------------------------------------------

  let currentPath = $state("");
  let allEntries = $state<FsEntry[]>([]);
  let loading = $state(false);
  let navError = $state<string | null>(null);
  let filterText = $state("");
  let selectedIdx = $state(-1);

  /** Ref to the filter input so we can focus it on open. */
  let filterEl = $state<HTMLInputElement | null>(null);
  /** Ref to the list so we can scroll highlighted entries into view. */
  let listEl = $state<HTMLUListElement | null>(null);

  // ---------------------------------------------------------------------------
  // Derived: filtered + sorted directory listing
  // ---------------------------------------------------------------------------

  /**
   * Directories only (working-dir picker), sorted alphabetically,
   * narrowed by the current filter text (case-insensitive prefix match
   * then substring fallback).
   */
  const filteredDirs = $derived.by((): FsEntry[] => {
    const dirs = allEntries.filter((e) => e.kind === "dir" && e.is_readable);
    const q = filterText.toLowerCase();
    if (q === "") return dirs;
    const prefix = dirs.filter((e) => e.name.toLowerCase().startsWith(q));
    const rest = dirs.filter(
      (e) => !e.name.toLowerCase().startsWith(q) && e.name.toLowerCase().includes(q),
    );
    return [...prefix, ...rest];
  });

  /** Breadcrumb segments derived from ``currentPath``. */
  const breadcrumbs = $derived.by((): { label: string; path: string }[] => {
    if (!currentPath) return [];
    const parts = currentPath.split("/").filter(Boolean);
    return [
      { label: "/", path: "/" },
      ...parts.map((part, i) => ({
        label: part,
        path: "/" + parts.slice(0, i + 1).join("/"),
      })),
    ];
  });

  // ---------------------------------------------------------------------------
  // Navigation helpers
  // ---------------------------------------------------------------------------

  async function navigate(path: string): Promise<void> {
    loading = true;
    navError = null;
    filterText = "";
    selectedIdx = -1;
    try {
      const result = await pickDir(path);
      currentPath = result.path;
      allEntries = result.entries;
    } catch (err) {
      navError =
        err instanceof ApiError
          ? String((err.body as { detail?: unknown })?.detail ?? err.message)
          : String(err);
    } finally {
      loading = false;
    }
  }

  function navigateUp(): void {
    if (!currentPath || currentPath === "/") return;
    const parent = currentPath.split("/").slice(0, -1).join("/") || "/";
    void navigate(parent);
  }

  // ---------------------------------------------------------------------------
  // Keyboard handler for the overlay
  // ---------------------------------------------------------------------------

  function handleOverlayKeydown(event: KeyboardEvent): void {
    // Esc: close without selecting.
    if (event.key === "Escape") {
      event.preventDefault();
      closePicker();
      return;
    }
    // Arrow navigation within the directory list.
    if (event.key === "ArrowDown") {
      event.preventDefault();
      selectedIdx = Math.min(selectedIdx + 1, filteredDirs.length - 1);
      scrollSelectedIntoView();
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      selectedIdx = Math.max(selectedIdx - 1, -1);
      scrollSelectedIntoView();
      return;
    }
    // Tab: auto-complete filter to first match.
    if (event.key === "Tab") {
      event.preventDefault();
      if (filteredDirs.length > 0) {
        filterText = filteredDirs[0]!.name;
        selectedIdx = 0;
      }
      return;
    }
    // Enter: navigate into highlighted dir, or select current path.
    if (event.key === "Enter") {
      event.preventDefault();
      if (selectedIdx >= 0 && filteredDirs[selectedIdx]) {
        const entry = filteredDirs[selectedIdx]!;
        void navigate(`${currentPath === "/" ? "" : currentPath}/${entry.name}`);
      } else {
        confirmSelection();
      }
      return;
    }
  }

  /** Handle Backspace on the filter input: go up when filter is empty. */
  function handleFilterKeydown(event: KeyboardEvent): void {
    if (event.key === "Backspace" && filterText === "") {
      event.preventDefault();
      navigateUp();
    }
  }

  function scrollSelectedIntoView(): void {
    if (!listEl || selectedIdx < 0) return;
    const child = listEl.children[selectedIdx] as HTMLElement | undefined;
    child?.scrollIntoView({ block: "nearest" });
  }

  // Reset selectedIdx when the filter changes so arrow-nav starts fresh.
  $effect(() => {
    void filterText;
    selectedIdx = -1;
  });
</script>

<!-- -------------------------------------------------------------------------
  Field row: current value + Browse button
-------------------------------------------------------------------------- -->
<div class="fp-field">
  <button
    type="button"
    class="fp-field__input"
    onclick={openPicker}
    aria-label="Working directory: {value || 'not set'}"
    data-testid="folder-picker-value"
  >
    {value || ""}
    {#if !value}
      <span class="fp-field__placeholder">/home/you/Projects/example</span>
    {/if}
  </button>
  <button
    type="button"
    class="fp-field__browse"
    onclick={openPicker}
    aria-label="Browse filesystem"
    data-testid="folder-picker-browse"
  >
    Browse…
  </button>
</div>

<!-- -------------------------------------------------------------------------
  Overlay (rendered in-flow; position:fixed covers the viewport)
-------------------------------------------------------------------------- -->
{#if open}
  <div
    class="fp-overlay"
    role="dialog"
    aria-modal="true"
    aria-label="Choose a working directory"
    tabindex="-1"
    onkeydown={handleOverlayKeydown}
  >
    <div class="fp-dialog">
      <!-- Header -->
      <div class="fp-dialog__header">
        <span class="fp-dialog__title">Choose working directory</span>
        <button
          type="button"
          class="fp-dialog__close"
          onclick={closePicker}
          aria-label="Close picker"
        >
          ✕
        </button>
      </div>

      <!-- Breadcrumb -->
      <nav class="fp-breadcrumb" aria-label="Directory path">
        {#each breadcrumbs as crumb, i (crumb.path)}
          {#if i > 0}
            <span class="fp-breadcrumb__sep" aria-hidden="true">/</span>
          {/if}
          <button
            type="button"
            class="fp-breadcrumb__seg"
            onclick={() => void navigate(crumb.path)}
          >
            {crumb.label}
          </button>
        {/each}
        {#if !currentPath}
          <span class="fp-breadcrumb__seg fp-breadcrumb__seg--empty">—</span>
        {/if}
      </nav>

      <!-- Filter input -->
      <input
        bind:this={filterEl}
        bind:value={filterText}
        type="text"
        class="fp-filter"
        placeholder="Filter directories… (Backspace goes up, Tab completes)"
        aria-label="Filter directory entries"
        onkeydown={handleFilterKeydown}
        data-testid="folder-picker-filter"
      />

      <!-- Directory listing -->
      <ul
        bind:this={listEl}
        class="fp-list"
        role="listbox"
        aria-label="Directories"
        data-testid="folder-picker-list"
      >
        {#if loading}
          <li class="fp-list__hint">Loading…</li>
        {:else if navError !== null}
          <li class="fp-list__error" role="alert">{navError}</li>
        {:else if filteredDirs.length === 0}
          <li class="fp-list__hint">No subdirectories{filterText ? " matching filter" : ""}.</li>
        {:else}
          {#each filteredDirs as entry, i (entry.name)}
            <li
              role="option"
              aria-selected={i === selectedIdx}
              data-testid={`fp-entry-${entry.name}`}
            >
              <button
                type="button"
                class="fp-list__item"
                class:fp-list__item--active={i === selectedIdx}
                onclick={() =>
                  void navigate(`${currentPath === "/" ? "" : currentPath}/${entry.name}`)}
              >
                <span class="fp-list__icon" aria-hidden="true">📁</span>
                <span class="fp-list__name">{entry.name}</span>
              </button>
            </li>
          {/each}
        {/if}
      </ul>

      <!-- Footer: current path + action buttons -->
      <div class="fp-dialog__footer">
        <span class="fp-dialog__current" title={currentPath}>{currentPath || "—"}</span>
        <div class="fp-dialog__actions">
          <button type="button" class="fp-btn fp-btn--ghost" onclick={closePicker}> Cancel </button>
          <button
            type="button"
            class="fp-btn fp-btn--primary"
            onclick={confirmSelection}
            disabled={!currentPath}
            data-testid="folder-picker-select"
          >
            Select
          </button>
        </div>
      </div>
    </div>

    <!-- Backdrop click closes the overlay -->
    <button
      type="button"
      class="fp-backdrop"
      onclick={closePicker}
      aria-label="Close picker"
      tabindex="-1"
    ></button>
  </div>
{/if}

<style>
  /* ── Field row ─────────────────────────────────────────────────────────── */
  .fp-field {
    display: flex;
    gap: 0.375rem;
    align-items: center;
  }
  .fp-field__input {
    flex: 1;
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.375rem 0.5rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fp-field__placeholder {
    color: rgb(var(--bearings-fg-muted));
  }
  .fp-field__browse {
    flex-shrink: 0;
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.375rem 0.625rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .fp-field__browse:hover {
    background: rgb(var(--bearings-surface-3, var(--bearings-surface-2)));
  }

  /* ── Backdrop ──────────────────────────────────────────────────────────── */
  .fp-overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .fp-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    border: none;
    padding: 0;
    cursor: default;
  }

  /* ── Dialog ────────────────────────────────────────────────────────────── */
  .fp-dialog {
    position: relative;
    z-index: 101;
    display: flex;
    flex-direction: column;
    background: rgb(var(--bearings-surface-1, var(--bearings-surface-2)));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.5rem;
    width: min(640px, 95vw);
    max-height: min(520px, 90vh);
    overflow: hidden;
  }
  .fp-dialog__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.625rem 0.875rem;
    border-bottom: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }
  .fp-dialog__title {
    font-size: 0.875rem;
    font-weight: 600;
  }
  .fp-dialog__close {
    background: none;
    border: none;
    cursor: pointer;
    color: rgb(var(--bearings-fg-muted));
    padding: 0.125rem 0.25rem;
    font-size: 0.875rem;
    line-height: 1;
  }

  /* ── Breadcrumb ────────────────────────────────────────────────────────── */
  .fp-breadcrumb {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0;
    padding: 0.375rem 0.875rem;
    border-bottom: 1px solid rgb(var(--bearings-border));
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    flex-shrink: 0;
    min-height: 2rem;
  }
  .fp-breadcrumb__sep {
    padding: 0 0.125rem;
    color: rgb(var(--bearings-border));
  }
  .fp-breadcrumb__seg {
    background: none;
    border: none;
    color: rgb(var(--bearings-fg-muted));
    cursor: pointer;
    padding: 0.125rem 0.25rem;
    border-radius: 0.2rem;
    font: inherit;
    font-size: 0.75rem;
  }
  .fp-breadcrumb__seg:hover {
    color: inherit;
    background: rgb(var(--bearings-surface-2));
  }
  .fp-breadcrumb__seg--empty {
    cursor: default;
  }

  /* ── Filter ────────────────────────────────────────────────────────────── */
  .fp-filter {
    background: rgb(var(--bearings-surface-2));
    color: inherit;
    border: none;
    border-bottom: 1px solid rgb(var(--bearings-border));
    padding: 0.5rem 0.875rem;
    font: inherit;
    font-size: 0.8125rem;
    outline: none;
    flex-shrink: 0;
  }
  .fp-filter::placeholder {
    color: rgb(var(--bearings-fg-muted));
    font-size: 0.75rem;
  }

  /* ── List ──────────────────────────────────────────────────────────────── */
  .fp-list {
    flex: 1;
    overflow-y: auto;
    list-style: none;
    margin: 0;
    padding: 0.25rem 0;
    min-height: 8rem;
  }
  .fp-list__item {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.3125rem 0.875rem;
    cursor: pointer;
    font-size: 0.8125rem;
    width: 100%;
    background: none;
    border: none;
    color: inherit;
    text-align: left;
    font: inherit;
    font-size: 0.8125rem;
  }
  .fp-list__item:hover,
  .fp-list__item--active {
    background: rgb(var(--bearings-accent) / 0.15);
  }
  .fp-list__item--active {
    outline: 1px solid rgb(var(--bearings-accent));
    outline-offset: -1px;
  }
  .fp-list__icon {
    font-size: 0.75rem;
    flex-shrink: 0;
  }
  .fp-list__name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .fp-list__hint,
  .fp-list__error {
    padding: 0.5rem 0.875rem;
    font-size: 0.8125rem;
    color: rgb(var(--bearings-fg-muted));
  }
  .fp-list__error {
    color: #f87171;
  }

  /* ── Footer ────────────────────────────────────────────────────────────── */
  .fp-dialog__footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.5rem 0.875rem;
    border-top: 1px solid rgb(var(--bearings-border));
    flex-shrink: 0;
  }
  .fp-dialog__current {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 55%;
  }
  .fp-dialog__actions {
    display: flex;
    gap: 0.375rem;
    flex-shrink: 0;
  }

  /* ── Buttons ───────────────────────────────────────────────────────────── */
  .fp-btn {
    padding: 0.3125rem 0.75rem;
    border-radius: 0.25rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
  }
  .fp-btn--ghost {
    background: none;
    color: inherit;
    border: 1px solid rgb(var(--bearings-border));
  }
  .fp-btn--ghost:hover {
    background: rgb(var(--bearings-surface-2));
  }
  .fp-btn--primary {
    background: rgb(var(--bearings-accent));
    color: white;
    border: 1px solid transparent;
  }
  .fp-btn--primary:hover {
    opacity: 0.9;
  }
  .fp-btn--primary:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
