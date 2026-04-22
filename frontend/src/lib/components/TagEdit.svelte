<script lang="ts">
  import * as api from '$lib/api';
  import { tags } from '$lib/stores/tags.svelte';
  import { renderMarkdown } from '$lib/render';
  import FolderPicker from './FolderPicker.svelte';
  import ModelSelect from './ModelSelect.svelte';

  let {
    open = $bindable(false),
    tagId = null as number | null
  }: { open?: boolean; tagId?: number | null } = $props();

  let name = $state('');
  let pinned = $state(false);
  let sortOrder = $state(0);
  let defaultWorkingDir = $state('');
  let defaultModel = $state('');
  let memory = $state('');
  /** Tracks the memory content as it existed when the modal opened, so
   * save-time we can tell the difference between "user left it blank
   * because there was no memory" (do nothing) and "user cleared an
   * existing memory" (DELETE). */
  let originalMemory = $state<string | null>(null);
  let showPreview = $state(false);
  let saving = $state(false);
  let loadError = $state<string | null>(null);
  let saveError = $state<string | null>(null);
  let confirmDelete = $state(false);

  const current = $derived(
    tagId === null ? null : (tags.list.find((t) => t.id === tagId) ?? null)
  );

  async function loadMemory(id: number): Promise<void> {
    loadError = null;
    try {
      const mem = await api.getTagMemory(id);
      memory = mem.content;
      originalMemory = mem.content;
    } catch (err) {
      // 404 is expected — tag has no memory yet. Anything else is a
      // real error worth surfacing.
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('404')) {
        memory = '';
        originalMemory = null;
      } else {
        loadError = msg;
      }
    }
  }

  /** Tracks whether we've already hydrated state for the current open
   * cycle. Without this, `tags.refresh()` (which happens after save)
   * gives `current` a new object reference, retriggers the effect,
   * and wipes any in-flight user edits. Reset to null when the modal
   * closes so the next open re-hydrates cleanly. */
  let hydratedFor = $state<number | null>(null);

  $effect(() => {
    if (!open) {
      hydratedFor = null;
      return;
    }
    if (!current || hydratedFor === current.id) return;
    hydratedFor = current.id;
    name = current.name;
    pinned = current.pinned;
    sortOrder = current.sort_order;
    defaultWorkingDir = current.default_working_dir ?? '';
    defaultModel = current.default_model ?? '';
    memory = '';
    originalMemory = null;
    showPreview = false;
    saveError = null;
    confirmDelete = false;
    loadMemory(current.id);
  });

  function blankToNull(v: string): string | null {
    const trimmed = v.trim();
    return trimmed === '' ? null : trimmed;
  }

  async function onSave() {
    if (tagId === null) return;
    const trimmedName = name.trim();
    if (trimmedName === '') return;
    saving = true;
    saveError = null;
    try {
      await tags.update(tagId, {
        name: trimmedName,
        pinned,
        sort_order: sortOrder,
        default_working_dir: blankToNull(defaultWorkingDir),
        default_model: blankToNull(defaultModel),
      });
      const memoryTrimmed = memory.trim();
      if (memoryTrimmed === '' && originalMemory !== null) {
        // Had a memory, user cleared it → delete.
        await api.deleteTagMemory(tagId);
      } else if (memoryTrimmed !== '') {
        // Has content → upsert. Store the raw (untrimmed) so leading
        // whitespace in prose is preserved.
        await api.putTagMemory(tagId, memory);
      }
    } catch (err) {
      saveError = err instanceof Error ? err.message : String(err);
      saving = false;
      return;
    }
    saving = false;
    open = false;
  }

  async function onDelete() {
    if (tagId === null) return;
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    saving = true;
    await tags.remove(tagId);
    saving = false;
    open = false;
  }

  function onCancel() {
    open = false;
  }

  const previewHtml = $derived(memory.trim() === '' ? '' : renderMarkdown(memory));
</script>

{#if open && current}
  <div class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/80 p-4">
    <form
      class="w-full max-w-2xl rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-2xl
        flex flex-col gap-4 max-h-[90vh] overflow-y-auto"
      onsubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <header class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-medium">Edit tag</h2>
          <p class="text-[10px] text-slate-600 font-mono mt-1">
            <!-- Mirror the sidebar split so the edit modal's headline
                 count matches the row Daisy just clicked on. -->
            <span class={current.open_session_count > 0 ? 'text-emerald-400' : ''}>
              {current.open_session_count}
            </span>
            {current.session_count} session{current.session_count === 1 ? '' : 's'}
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

      <div class="grid grid-cols-[1fr_auto_auto] gap-3 items-end">
        <label class="flex flex-col gap-1 text-xs">
          <span class="text-slate-400">Name *</span>
          <input
            type="text"
            required
            class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm
              focus:outline-none focus:border-slate-600"
            bind:value={name}
          />
        </label>
        <label class="flex flex-col gap-1 text-xs">
          <span class="text-slate-400">Order</span>
          <input
            type="number"
            class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm font-mono w-16
              focus:outline-none focus:border-slate-600"
            title="Lower number = higher in sidebar. Breaks ties in prompt assembly (later wins)."
            bind:value={sortOrder}
          />
        </label>
        <label class="inline-flex items-center gap-1.5 text-xs text-slate-300 pb-2">
          <input type="checkbox" bind:checked={pinned} class="accent-emerald-500" />
          <span>Pinned</span>
        </label>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div class="flex flex-col gap-1 text-xs">
          <span class="text-slate-400">Default working dir</span>
          <FolderPicker bind:value={defaultWorkingDir} />
        </div>
        <div class="flex flex-col gap-1 text-xs">
          <span class="text-slate-400">Default model</span>
          <ModelSelect bind:value={defaultModel} />
        </div>
      </div>

      <section class="flex flex-col gap-1">
        <div class="flex items-baseline justify-between gap-2">
          <span class="text-slate-400 text-xs">
            Memory <span class="text-slate-600">(markdown — injected into every session with this tag)</span>
          </span>
          <button
            type="button"
            class="text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5
              bg-slate-800 hover:bg-slate-700 text-slate-300"
            onclick={() => (showPreview = !showPreview)}
          >
            {showPreview ? 'Edit' : 'Preview'}
          </button>
        </div>
        {#if showPreview}
          <div
            class="rounded bg-slate-950 border border-slate-800 px-3 py-2 text-sm
              prose prose-invert prose-sm max-w-none min-h-[10rem]"
          >
            {#if previewHtml}
              {@html previewHtml}
            {:else}
              <span class="text-slate-600">(empty — nothing to preview)</span>
            {/if}
          </div>
        {:else}
          <textarea
            class="rounded bg-slate-950 border border-slate-800 px-2 py-2 text-sm
              focus:outline-none focus:border-slate-600 resize-y min-h-[10rem] font-mono"
            rows="10"
            placeholder="# Context&#10;&#10;Directory pointers, conventions, constraints. Markdown."
            bind:value={memory}
          ></textarea>
        {/if}
        <p class="text-[10px] text-slate-500">
          If multiple tags have conflicting rules, later tags (lower in the
          sidebar sort order) override earlier ones.
        </p>
      </section>

      {#if loadError}
        <p class="text-rose-400 text-xs">memory: {loadError}</p>
      {/if}
      {#if saveError}
        <p class="text-rose-400 text-xs">{saveError}</p>
      {/if}
      {#if tags.error && !saveError}
        <p class="text-rose-400 text-xs">{tags.error}</p>
      {/if}

      <div class="flex items-center justify-between gap-2 pt-2">
        <button
          type="button"
          class="rounded px-3 py-2 text-sm {confirmDelete
            ? 'bg-rose-600 hover:bg-rose-500 text-white'
            : 'bg-slate-800 hover:bg-slate-700 text-rose-300'}"
          onclick={onDelete}
          disabled={saving}
        >
          {confirmDelete ? 'Confirm delete?' : 'Delete'}
        </button>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="rounded bg-slate-800 hover:bg-slate-700 px-3 py-2 text-sm"
            onclick={onCancel}
          >
            Cancel
          </button>
          <button
            type="submit"
            class="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-2 text-sm disabled:opacity-50"
            disabled={saving || name.trim() === ''}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </form>
  </div>
{/if}
