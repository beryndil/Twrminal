<script lang="ts">
  import { sessions } from '$lib/stores/sessions.svelte';
  import { conversation } from '$lib/stores/conversation.svelte';
  import { agent } from '$lib/agent.svelte';
  import * as api from '$lib/api';
  import { highlightText } from '$lib/utils/highlight';

  const SEARCH_DEBOUNCE_MS = 200;

  let { query = $bindable('') }: { query?: string } = $props();

  let results = $state<api.SearchHit[]>([]);
  let error = $state<string | null>(null);
  let inputEl: HTMLInputElement | undefined = $state();
  let timer: ReturnType<typeof setTimeout> | null = null;

  // ⌘/Ctrl+K — focus + select the search input. Document-level so it
  // fires regardless of where the user's focus is (except inputs that
  // might intercept; the shortcut-hijack test in practice has been
  // fine).
  $effect(() => {
    function onDocKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputEl?.focus();
        inputEl?.select();
      }
    }
    document.addEventListener('keydown', onDocKey);
    return () => document.removeEventListener('keydown', onDocKey);
  });

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      query = '';
      results = [];
      inputEl?.blur();
    }
  }

  function run(q: string) {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(async () => {
      if (!q.trim()) {
        results = [];
        error = null;
        return;
      }
      try {
        results = await api.searchHistory(q.trim());
        error = null;
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      }
    }, SEARCH_DEBOUNCE_MS);
  }

  $effect(() => {
    run(query);
  });

  async function onPick(sid: string) {
    const q = query.trim();
    query = '';
    results = [];
    sessions.select(sid);
    await agent.connect(sid);
    // agent.connect → conversation.load clears highlightQuery via
    // reset(); set it *after* the load so rendered messages pick it up.
    conversation.highlightQuery = q;
  }
</script>

<input
  type="search"
  placeholder="Search messages (⌘/Ctrl+K)"
  class="rounded bg-slate-950 border border-slate-800 px-2 py-1.5 text-sm
    focus:outline-none focus:border-slate-600"
  bind:value={query}
  bind:this={inputEl}
  onkeydown={onKey}
/>

{#if query.trim()}
  {#if error}
    <p class="text-xs text-rose-400">{error}</p>
  {:else if results.length === 0}
    <p class="text-slate-500 text-sm">No matches.</p>
  {:else}
    <ul class="flex flex-col gap-1">
      {#each results as hit (hit.message_id)}
        <li>
          <button
            type="button"
            class="w-full text-left rounded bg-slate-800/40 hover:bg-slate-800 px-2 py-2"
            onclick={() => onPick(hit.session_id)}
          >
            <div class="flex items-baseline justify-between gap-2">
              <span class="text-sm truncate">
                {hit.session_title ?? hit.model}
              </span>
              <span class="text-[10px] uppercase text-slate-500">{hit.role}</span>
            </div>
            <div class="text-[11px] text-slate-300 mt-0.5 line-clamp-2 snippet">
              {@html highlightText(hit.snippet, query.trim())}
            </div>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
{/if}

<style>
  .snippet :global(mark) {
    background-color: rgb(234 179 8 / 0.35);
    color: rgb(253 224 71);
    border-radius: 0.125rem;
    padding: 0 0.125rem;
  }
</style>
