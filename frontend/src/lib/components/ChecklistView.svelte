<script lang="ts">
  /**
   * Structured checkable list rendered in the right pane when the
   * selected session has `kind === 'checklist'`. Loads / syncs via
   * the `checklists` store which owns the optimistic-update policy.
   *
   * Keyboard:
   *  - Enter in the "Add item" input creates and re-focuses the
   *    field so the user can keep typing the next item.
   *  - Enter in an item-edit input commits; Esc cancels.
   *
   * Layout mirrors Conversation.svelte's header+body split so the
   * right pane has a consistent chrome regardless of session kind.
   */

  import { onDestroy } from 'svelte';
  import { checklists } from '$lib/stores/checklists.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';

  const selected = $derived(sessions.selected);

  // Autofocus spec (Q1-A, plan v1): land the cursor on the Add-item
  // input whenever a fresh checklist session opens. `addInput` is
  // the raw DOM node; we focus it inside an effect that fires after
  // mount and again on selection changes.
  let addInput: HTMLInputElement | undefined = $state();
  let newLabel = $state('');
  let notesDraft = $state('');
  let editingId = $state<number | null>(null);
  let editDraft = $state('');

  // Load the checklist whenever the selected session id changes.
  $effect(() => {
    const sid = selected?.id ?? null;
    if (sid === null || selected?.kind !== 'checklist') {
      checklists.reset();
      return;
    }
    if (checklists.sessionId !== sid) {
      void checklists.load(sid);
    }
  });

  // Sync the notes draft with the server-confirmed value whenever it
  // changes so a blur-commit starts from the latest text.
  $effect(() => {
    notesDraft = checklists.current?.notes ?? '';
  });

  // Autofocus the Add-item input when this pane becomes visible or a
  // different checklist session is opened.
  $effect(() => {
    if (selected?.kind === 'checklist' && addInput) {
      addInput.focus();
    }
  });

  onDestroy(() => {
    checklists.reset();
  });

  async function handleAdd(ev: Event) {
    ev.preventDefault();
    const label = newLabel;
    newLabel = '';
    await checklists.add(label);
    addInput?.focus();
  }

  async function handleNotesBlur() {
    const next = notesDraft.trim() === '' ? null : notesDraft;
    if (next === (checklists.current?.notes ?? null)) return;
    await checklists.setNotes(next);
  }

  function startEdit(itemId: number, label: string) {
    editingId = itemId;
    editDraft = label;
  }

  async function commitEdit() {
    const id = editingId;
    if (id === null) return;
    const trimmed = editDraft.trim();
    editingId = null;
    if (trimmed === '') return;
    await checklists.update(id, { label: trimmed });
  }

  function cancelEdit() {
    editingId = null;
  }

  async function handleToggle(itemId: number, checked: boolean) {
    await checklists.toggle(itemId, checked);
  }

  async function handleDelete(itemId: number) {
    await checklists.remove(itemId);
  }

  function onEditKey(ev: KeyboardEvent) {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      void commitEdit();
    } else if (ev.key === 'Escape') {
      ev.preventDefault();
      cancelEdit();
    }
  }
</script>

<section class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-slate-950 text-slate-100">
  <header class="flex items-center gap-3 border-b border-slate-800 px-4 py-3">
    <span class="text-lg" aria-hidden="true">☑</span>
    <h2 class="flex-1 truncate text-sm font-semibold">
      {selected?.title ?? 'Checklist'}
    </h2>
  </header>

  {#if checklists.loading}
    <p class="px-4 py-6 text-sm text-slate-400">Loading checklist…</p>
  {:else if checklists.error}
    <p class="px-4 py-6 text-sm text-rose-400">Error: {checklists.error}</p>
  {:else if checklists.current}
    <div class="flex flex-1 min-h-0 flex-col gap-4 overflow-y-auto px-4 py-4">
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-slate-400">Notes</span>
        <textarea
          class="min-h-[3rem] resize-y rounded border border-slate-800 bg-slate-900 p-2 text-slate-100 focus:border-sky-500 focus:outline-none"
          bind:value={notesDraft}
          onblur={handleNotesBlur}
          placeholder="Optional longform notes for this checklist"
        ></textarea>
      </label>

      <ul class="flex flex-col gap-1">
        {#each checklists.current.items as item (item.id)}
          {@const checked = item.checked_at !== null}
          <li
            class="group flex items-center gap-2 rounded border border-slate-900 px-2 py-1 hover:border-slate-700"
            data-item-id={item.id}
          >
            <input
              type="checkbox"
              class="h-4 w-4 accent-sky-500"
              aria-label={`Toggle ${item.label}`}
              {checked}
              onchange={(ev) =>
                handleToggle(item.id, (ev.currentTarget as HTMLInputElement).checked)}
            />
            {#if editingId === item.id}
              <!-- svelte-ignore a11y_autofocus -->
              <input
                class="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm focus:border-sky-500 focus:outline-none"
                bind:value={editDraft}
                onkeydown={onEditKey}
                onblur={commitEdit}
                autofocus
              />
            {:else}
              <button
                type="button"
                class="flex-1 cursor-text truncate text-left text-sm {checked
                  ? 'text-slate-500 line-through'
                  : 'text-slate-100'}"
                onclick={() => startEdit(item.id, item.label)}
                title="Click to edit"
              >
                {item.label}
              </button>
            {/if}
            <button
              type="button"
              class="text-xs text-slate-500 opacity-0 hover:text-rose-400 group-hover:opacity-100"
              aria-label={`Delete ${item.label}`}
              onclick={() => handleDelete(item.id)}
            >
              ✕
            </button>
          </li>
        {/each}
      </ul>

      <form class="flex items-center gap-2" onsubmit={handleAdd}>
        <span aria-hidden="true" class="text-slate-500">+</span>
        <input
          bind:this={addInput}
          bind:value={newLabel}
          class="flex-1 rounded border border-slate-800 bg-slate-900 px-2 py-1 text-sm focus:border-sky-500 focus:outline-none"
          placeholder="Add item…"
          aria-label="Add a checklist item"
        />
        <button
          type="submit"
          class="rounded bg-sky-600 px-3 py-1 text-xs font-medium hover:bg-sky-500 disabled:opacity-50"
          disabled={newLabel.trim() === ''}>Add</button
        >
      </form>
    </div>
  {:else}
    <p class="px-4 py-6 text-sm text-slate-400">No checklist loaded.</p>
  {/if}
</section>
