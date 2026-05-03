<script lang="ts">
  /**
   * Sidebar search overlay (item 2.4).
   *
   * Behavior:
   *
   * - ``Ctrl+K`` opens the overlay (wired via :func:`bindHandler` on
   *   :data:`KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH`).
   * - Typing debounces at
   *   :data:`HISTORY_SEARCH_DEBOUNCE_MS` before fetching.
   * - Clicking a result navigates to the session; message hits append
   *   a ``#msg-<id>`` hash so the conversation pane can scroll to the
   *   relevant message.
   * - ``Esc`` closes the overlay.
   * - Clicking the backdrop closes.
   *
   * String literals live in :data:`SIDEBAR_SEARCH_STRINGS`.
   */
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { searchHistory, type HistorySearchResult } from "../../api/history";
  import {
    HISTORY_SEARCH_DEBOUNCE_MS,
    KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH,
    SIDEBAR_SEARCH_STRINGS,
  } from "../../config";
  import { bindHandler } from "../../keyboard/store.svelte";

  interface Props {
    /** Called when the overlay closes so the parent can sync open state. */
    onclose?: () => void;
  }

  const { onclose }: Props = $props();

  let open = $state(false);
  let query = $state("");
  let results = $state<HistorySearchResult[]>([]);
  let loading = $state(false);
  let activeIndex = $state(0);
  let inputEl = $state<HTMLInputElement | null>(null);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  // Focus the input whenever the overlay opens.
  $effect(() => {
    if (open && inputEl !== null) {
      inputEl.focus();
    }
  });

  // Effective active index: clamped via derived so no state-write-in-effect.
  const safeActiveIndex = $derived(
    results.length === 0 ? 0 : Math.min(activeIndex, results.length - 1),
  );

  function openOverlay(): void {
    open = true;
    query = "";
    results = [];
    activeIndex = 0;
  }

  function closeOverlay(): void {
    open = false;
    onclose?.();
  }

  function scheduleSearch(q: string): void {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    if (!q.trim()) {
      results = [];
      loading = false;
      return;
    }
    loading = true;
    debounceTimer = setTimeout(async () => {
      results = await searchHistory(q);
      loading = false;
      activeIndex = 0;
    }, HISTORY_SEARCH_DEBOUNCE_MS);
  }

  function handleInput(event: Event): void {
    const value = (event.currentTarget as HTMLInputElement).value;
    query = value;
    scheduleSearch(value);
  }

  function navigateToResult(result: HistorySearchResult): void {
    closeOverlay();
    const path = `/sessions/${encodeURIComponent(result.session_id)}`;
    const hash = result.message_id !== null ? `#msg-${result.message_id}` : "";
    void goto(`${path}${hash}`);
  }

  function handleKeyDown(event: KeyboardEvent): void {
    switch (event.key) {
      case "Escape":
        event.preventDefault();
        closeOverlay();
        break;
      case "ArrowDown":
        event.preventDefault();
        activeIndex = Math.min(activeIndex + 1, results.length - 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        break;
      case "Enter": {
        event.preventDefault();
        const hit = results[safeActiveIndex];
        if (hit !== undefined) navigateToResult(hit);
        break;
      }
      default:
        break;
    }
  }

  onMount(() => {
    const release = bindHandler(KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH, openOverlay);
    return () => {
      release();
      if (debounceTimer !== null) clearTimeout(debounceTimer);
    };
  });
</script>

{#if open}
  <!--
    Full-screen backdrop — clicking outside the dialog closes the overlay.
    ``role="dialog"`` + ``aria-modal`` tells assistive technology the rest
    of the page is inert while the overlay is open.
  -->
  <div
    class="sidebar-search-backdrop"
    data-testid="sidebar-search-backdrop"
    onclick={closeOverlay}
    aria-hidden="true"
  ></div>

  <div
    class="sidebar-search-dialog"
    role="dialog"
    aria-modal="true"
    aria-label={SIDEBAR_SEARCH_STRINGS.ariaLabel}
    data-testid="sidebar-search-dialog"
  >
    <!-- Input row -->
    <div class="sidebar-search-input-row">
      <input
        bind:this={inputEl}
        class="sidebar-search-input"
        type="search"
        placeholder={SIDEBAR_SEARCH_STRINGS.placeholder}
        aria-label={SIDEBAR_SEARCH_STRINGS.ariaLabel}
        value={query}
        oninput={handleInput}
        onkeydown={handleKeyDown}
        autocomplete="off"
        spellcheck={false}
        data-testid="sidebar-search-input"
      />
      <button
        class="sidebar-search-close"
        type="button"
        aria-label={SIDEBAR_SEARCH_STRINGS.closeLabel}
        onclick={closeOverlay}
        data-testid="sidebar-search-close"
      >
        <span aria-hidden="true">✕</span>
      </button>
    </div>

    <!-- Results list -->
    {#if loading}
      <p class="sidebar-search-status" data-testid="sidebar-search-loading">
        {SIDEBAR_SEARCH_STRINGS.loadingLabel}
      </p>
    {:else if query.trim() && results.length === 0}
      <p class="sidebar-search-status" data-testid="sidebar-search-empty">
        {SIDEBAR_SEARCH_STRINGS.emptyResults}
      </p>
    {:else if results.length > 0}
      <ul
        class="sidebar-search-results"
        role="listbox"
        aria-label={SIDEBAR_SEARCH_STRINGS.ariaLabel}
        data-testid="sidebar-search-results"
      >
        {#each results as result, i (result.session_id + (result.message_id ?? ""))}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <li
            class="sidebar-search-result"
            class:sidebar-search-result--active={i === safeActiveIndex}
            role="option"
            aria-selected={i === safeActiveIndex}
            onclick={() => navigateToResult(result)}
            data-testid="sidebar-search-result"
          >
            <span class="sidebar-search-result__kind" data-testid="sidebar-search-result-kind">
              {result.kind === "session"
                ? SIDEBAR_SEARCH_STRINGS.sessionKindLabel
                : SIDEBAR_SEARCH_STRINGS.messageKindLabel}
            </span>
            <span class="sidebar-search-result__title" data-testid="sidebar-search-result-title">
              {result.session_title}
            </span>
            <span
              class="sidebar-search-result__snippet"
              data-testid="sidebar-search-result-snippet"
            >
              {result.snippet}
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .sidebar-search-backdrop {
    position: fixed;
    inset: 0;
    z-index: 40;
    background: rgba(0, 0, 0, 0.45);
  }

  .sidebar-search-dialog {
    position: fixed;
    top: 10vh;
    left: 50%;
    transform: translateX(-50%);
    z-index: 50;
    width: min(560px, 92vw);
    max-height: 70vh;
    display: flex;
    flex-direction: column;
    background: var(--color-surface-1, #1e1e2e);
    border: 1px solid var(--color-border, #313244);
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
    overflow: hidden;
  }

  .sidebar-search-input-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--color-border, #313244);
  }

  .sidebar-search-input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--color-text-primary, #cdd6f4);
    font-size: 1rem;
    line-height: 1.5;
  }

  .sidebar-search-input::placeholder {
    color: var(--color-text-muted, #6c7086);
  }

  /* Remove default browser search-cancel button */
  .sidebar-search-input::-webkit-search-cancel-button {
    display: none;
  }

  .sidebar-search-close {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--color-text-muted, #6c7086);
    padding: 0.25rem 0.5rem;
    font-size: 0.875rem;
    border-radius: 4px;
    line-height: 1;
  }

  .sidebar-search-close:hover {
    color: var(--color-text-primary, #cdd6f4);
    background: var(--color-surface-2, #313244);
  }

  .sidebar-search-status {
    padding: 1rem;
    color: var(--color-text-muted, #6c7086);
    font-size: 0.875rem;
    text-align: center;
    margin: 0;
  }

  .sidebar-search-results {
    list-style: none;
    margin: 0;
    padding: 0.25rem 0;
    overflow-y: auto;
    flex: 1;
  }

  .sidebar-search-result {
    display: grid;
    grid-template-columns: 4.5rem 1fr;
    grid-template-rows: auto auto;
    column-gap: 0.5rem;
    padding: 0.5rem 1rem;
    cursor: pointer;
    border-left: 2px solid transparent;
  }

  .sidebar-search-result:hover,
  .sidebar-search-result--active {
    background: var(--color-surface-2, #313244);
    border-left-color: var(--color-accent, #89b4fa);
  }

  .sidebar-search-result__kind {
    grid-row: 1;
    grid-column: 1;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--color-accent, #89b4fa);
    align-self: baseline;
    padding-top: 0.1rem;
  }

  .sidebar-search-result__title {
    grid-row: 1;
    grid-column: 2;
    font-size: 0.9rem;
    font-weight: 500;
    color: var(--color-text-primary, #cdd6f4);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .sidebar-search-result__snippet {
    grid-row: 2;
    grid-column: 2;
    font-size: 0.8rem;
    color: var(--color-text-muted, #6c7086);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
