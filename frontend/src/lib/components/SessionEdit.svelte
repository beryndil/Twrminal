<script lang="ts">
  import * as api from '$lib/api';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { tags } from '$lib/stores/tags.svelte';

  let {
    open = $bindable(false),
    sessionId
  }: { open?: boolean; sessionId: string | null } = $props();

  let title = $state('');
  let description = $state('');
  let budget = $state('');
  let saving = $state(false);

  // Tags state. Scoped to the modal session so chips reflect what's
  // actually attached — `tags.list` is the global pool.
  let sessionTags = $state<api.Tag[]>([]);
  let tagDraft = $state('');
  let tagError = $state<string | null>(null);

  const current = $derived(
    sessionId ? (sessions.list.find((s) => s.id === sessionId) ?? null) : null
  );

  const attachedIds = $derived(new Set(sessionTags.map((t) => t.id)));

  const draftLower = $derived(tagDraft.trim().toLowerCase());

  const attachSuggestions = $derived(
    draftLower === ''
      ? []
      : tags.list.filter(
          (t) => !attachedIds.has(t.id) && t.name.toLowerCase().includes(draftLower)
        )
  );

  const exactMatch = $derived(
    tags.list.find((t) => t.name.toLowerCase() === draftLower) ?? null
  );

  $effect(() => {
    if (open && current) {
      title = current.title ?? '';
      description = current.description ?? '';
      budget = current.max_budget_usd != null ? String(current.max_budget_usd) : '';
      tagDraft = '';
      tagError = null;
      loadTags(current.id);
    }
  });

  async function loadTags(id: string) {
    try {
      sessionTags = await api.listSessionTags(id);
    } catch (e) {
      tagError = e instanceof Error ? e.message : String(e);
    }
  }

  function parseBudget(raw: string): number | null {
    const trimmed = raw.trim();
    if (trimmed === '') return null;
    const n = Number(trimmed);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  async function onAttach(tag: api.Tag) {
    if (!current) return;
    tagError = null;
    try {
      sessionTags = await api.attachSessionTag(current.id, tag.id);
      tags.bumpCount(tag.id, +1);
      tagDraft = '';
    } catch (e) {
      tagError = e instanceof Error ? e.message : String(e);
    }
  }

  async function onCreateAndAttach() {
    if (!current) return;
    const name = tagDraft.trim();
    if (name === '') return;
    tagError = null;
    const created = await tags.create({ name });
    if (!created) {
      // tags.create records the detail into tags.error; surface it here too.
      tagError = tags.error;
      return;
    }
    await onAttach(created);
  }

  async function onDetach(tag: api.Tag) {
    if (!current) return;
    tagError = null;
    try {
      sessionTags = await api.detachSessionTag(current.id, tag.id);
      tags.bumpCount(tag.id, -1);
    } catch (e) {
      tagError = e instanceof Error ? e.message : String(e);
    }
  }

  function onTagKey(e: KeyboardEvent) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    // Match an existing tag first (case-insensitive); otherwise
    // create a new one. This matches how the suggestion list renders
    // — no "create" path when an exact match is already offered.
    if (exactMatch) {
      if (!attachedIds.has(exactMatch.id)) onAttach(exactMatch);
      else tagDraft = '';
      return;
    }
    onCreateAndAttach();
  }

  async function onSave() {
    if (!sessionId) return;
    saving = true;
    await sessions.update(sessionId, {
      title: title.trim() === '' ? null : title.trim(),
      description: description.trim() === '' ? null : description.trim(),
      max_budget_usd: parseBudget(budget)
    });
    saving = false;
    open = false;
  }

  function onCancel() {
    open = false;
  }
</script>

{#if open && current}
  <div class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4">
    <form
      class="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-2xl
        flex flex-col gap-4"
      onsubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <header class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-medium">Edit session</h2>
          <p class="text-[10px] text-slate-600 font-mono mt-1 truncate">
            {current.model} · {current.working_dir}
          </p>
        </div>
        <button
          type="button"
          class="text-slate-500 hover:text-slate-300 text-sm"
          aria-label="Close edit"
          onclick={onCancel}
        >
          ✕
        </button>
      </header>

      <label class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Title</span>
        <input
          type="text"
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm
            focus:outline-none focus:border-slate-600"
          placeholder="(leave empty to clear)"
          bind:value={title}
        />
      </label>

      <label class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Description</span>
        <textarea
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm
            focus:outline-none focus:border-slate-600 resize-y min-h-[4.5rem]"
          placeholder="context notes for this session (optional)"
          rows="3"
          bind:value={description}
        ></textarea>
      </label>

      <label class="flex flex-col gap-1 text-xs">
        <span class="text-slate-400">Budget USD</span>
        <input
          type="number"
          inputmode="decimal"
          step="0.01"
          min="0"
          placeholder="no cap"
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm font-mono
            focus:outline-none focus:border-slate-600"
          bind:value={budget}
        />
      </label>

      <section class="flex flex-col gap-2 text-xs">
        <span class="text-slate-400">Tags</span>
        {#if sessionTags.length > 0}
          <ul class="flex flex-wrap gap-1" aria-label="Attached tags">
            {#each sessionTags as tag (tag.id)}
              <li
                class="flex items-center gap-1 rounded bg-slate-800 px-2 py-0.5 text-xs"
              >
                {#if tag.pinned}
                  <span class="text-amber-400" aria-label="pinned">★</span>
                {/if}
                <span>{tag.name}</span>
                <button
                  type="button"
                  class="text-slate-500 hover:text-rose-400"
                  aria-label={`Detach ${tag.name}`}
                  onclick={() => onDetach(tag)}
                >
                  ✕
                </button>
              </li>
            {/each}
          </ul>
        {/if}
        <input
          type="text"
          class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm
            focus:outline-none focus:border-slate-600"
          placeholder="Add a tag (Enter to attach or create)"
          aria-label="Tag name"
          bind:value={tagDraft}
          onkeydown={onTagKey}
        />
        {#if attachSuggestions.length > 0}
          <ul class="flex flex-wrap gap-1" aria-label="Tag suggestions">
            {#each attachSuggestions as tag (tag.id)}
              <li>
                <button
                  type="button"
                  class="rounded bg-slate-800 hover:bg-slate-700 px-2 py-0.5 text-xs"
                  onclick={() => onAttach(tag)}
                >
                  + {tag.name}
                </button>
              </li>
            {/each}
          </ul>
        {:else if tagDraft.trim() !== '' && !exactMatch}
          <button
            type="button"
            class="self-start rounded bg-emerald-700 hover:bg-emerald-600 px-2 py-0.5 text-xs"
            onclick={onCreateAndAttach}
          >
            + Create "{tagDraft.trim()}"
          </button>
        {/if}
        {#if tagError}
          <p class="text-rose-400">{tagError}</p>
        {/if}
      </section>

      <div class="flex items-center justify-end gap-2 pt-2">
        <button
          type="button"
          class="rounded bg-slate-800 hover:bg-slate-700 px-3 py-2 text-sm"
          onclick={onCancel}
        >
          Cancel
        </button>
        <button
          type="submit"
          class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm
            disabled:opacity-50"
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  </div>
{/if}
