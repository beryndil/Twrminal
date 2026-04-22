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
   * v0.5.1 behaviour on paired items:
   *  - Clicking the checkbox on a paired item also closes the chat
   *    session (no prompt). The close cascades on the server: it
   *    flips the linked item, walks up through any parents, and
   *    auto-closes the parent checklist session when every root-level
   *    item carries `checked_at`.
   *  - Nesting renders recursively via a snippet. Parents with at
   *    least one child show a disabled checkbox whose state is
   *    derived from the cascade — never directly toggled.
   *  - Paired-chat affordances (title link + 💬 Work-on button) only
   *    render on leaves; parents aren't work units.
   *
   * Layout mirrors Conversation.svelte's header+body split so the
   * right pane has a consistent chrome regardless of session kind.
   */

  import { onDestroy } from 'svelte';
  import type { ChecklistItem } from '$lib/api';
  import { checklists } from '$lib/stores/checklists.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';

  const selected = $derived(sessions.selected);

  // Derived tree: parent_item_id → sorted children. A single pass
  // over the flat item list builds the whole tree and is cheap enough
  // to redo whenever the checklist store updates.
  const childrenByParent = $derived.by(() => {
    const map = new Map<number | null, ChecklistItem[]>();
    const items = checklists.current?.items ?? [];
    for (const item of items) {
      const key = item.parent_item_id ?? null;
      const bucket = map.get(key) ?? [];
      bucket.push(item);
      map.set(key, bucket);
    }
    for (const bucket of map.values()) {
      bucket.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
    }
    return map;
  });

  const rootItems = $derived(childrenByParent.get(null) ?? []);

  function hasChildren(itemId: number): boolean {
    return (childrenByParent.get(itemId)?.length ?? 0) > 0;
  }

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
    // v0.5.1: checking an item with an open paired chat closes the
    // chat automatically. No prompt — the coupling is intentional
    // and an extra click would just be noise. The close_session
    // cascade on the backend flips the item + cascades up through
    // parents + auto-closes the parent checklist session when every
    // root-level item becomes checked. We still call `checklists.
    // toggle` afterward so the optimistic UI lands regardless of
    // pairing; the server write is idempotent on an already-checked
    // item (COALESCE preserves the original check timestamp).
    //
    // Unchecking is left untouched — reopening a closed chat is a
    // user decision that belongs in the sidebar, not this affordance.
    if (checked) {
      const item = checklists.current?.items.find((i) => i.id === itemId);
      const pairedId = item?.chat_session_id ?? null;
      if (pairedId) {
        const pairedSession = sessions.list.find((s) => s.id === pairedId);
        if (pairedSession && !pairedSession.closed_at) {
          await sessions.close(pairedId);
        }
      }
    }
    await checklists.toggle(itemId, checked);
    // The close_session cascade may have stamped `closed_at` on the
    // parent checklist session when the last item landed checked.
    // Refresh sessions so the sidebar moves it into Closed promptly;
    // the ChecklistView itself stays mounted for the now-closed list.
    if (checked) {
      await sessions.refresh();
    }
  }

  async function handleDelete(itemId: number) {
    await checklists.remove(itemId);
  }

  /** Spawn-or-navigate handler for the per-item "Work on this"
   * button. Idempotent on the server — a double-click lands on the
   * same chat session. We select the target session after spawning
   * so the right pane swaps to the Conversation view on the same
   * click; the conversation store picks it up via the existing
   * `sessions.selected` derivation. */
  async function handleWorkOnThis(itemId: number) {
    const chat = await checklists.spawnChat(itemId);
    if (!chat) return;
    sessions.list = [chat, ...sessions.list.filter((s) => s.id !== chat.id)];
    sessions.select(chat.id);
    await agent.connect(chat.id);
  }

  /** Jump to an already-paired chat. Separate from `handleWorkOnThis`
   * because we skip the spawn call — the session exists and is in
   * `sessions.list`. Connects the agent so the Conversation view
   * streams events on arrival (no-op when the session is closed —
   * `agent.connect` rejects closed sessions up front). */
  async function handleOpenPairedChat(chatId: string) {
    sessions.select(chatId);
    const target = sessions.list.find((s) => s.id === chatId);
    if (target && !target.closed_at) {
      await agent.connect(chatId);
    }
  }

  /** Manual close/reopen toggle for the checklist session itself.
   * Mirrors the Conversation header affordance so the user always has
   * a one-click escape hatch — the auto-close cascade only fires when
   * the list is complete, but an abandoned / WIP list still needs a
   * way out. No confirm; reopen is equally cheap. */
  async function onToggleClosed() {
    const sid = sessions.selectedId;
    if (!sid) return;
    const current = sessions.selected;
    if (!current) return;
    if (current.closed_at) {
      await sessions.reopen(sid);
    } else {
      await sessions.close(sid);
    }
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
    <h2 class="flex flex-1 items-center gap-2 min-w-0 text-sm font-semibold">
      <span class="truncate">{selected?.title ?? 'Checklist'}</span>
      {#if selected}
        <button
          type="button"
          class="text-xs hover:text-slate-300 {selected.closed_at
            ? 'text-emerald-400'
            : 'text-slate-500'}"
          aria-label={selected.closed_at ? 'Reopen checklist' : 'Close checklist'}
          aria-pressed={!!selected.closed_at}
          title={selected.closed_at ? 'Reopen checklist' : 'Close checklist'}
          onclick={onToggleClosed}
          data-testid="close-checklist"
        >
          ✓
        </button>
      {/if}
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

      {#snippet itemRow(item: ChecklistItem)}
        {@const checked = item.checked_at !== null}
        {@const parentOf = hasChildren(item.id)}
        {@const pairedChat = item.chat_session_id
          ? (sessions.list.find((s) => s.id === item.chat_session_id) ?? null)
          : null}
        <li
          class="group flex flex-col rounded border border-slate-900 px-2 py-1 hover:border-slate-700"
          data-item-id={item.id}
          data-parent={parentOf ? 'true' : 'false'}
        >
          <div class="flex items-center gap-2">
            <input
              type="checkbox"
              class="h-4 w-4 accent-sky-500 disabled:cursor-not-allowed disabled:opacity-70"
              aria-label={parentOf
                ? `All children of ${item.label} checked`
                : `Toggle ${item.label}`}
              {checked}
              disabled={parentOf}
              title={parentOf
                ? 'Parents are auto-checked when all their children are done'
                : undefined}
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
            {#if !parentOf && pairedChat}
              <!-- Paired-chat title as a link. Always visible (not
                   opacity-gated) so Dave can see at a glance which
                   items have live sessions. -->
              <button
                type="button"
                class="max-w-[24ch] truncate text-xs text-sky-400 hover:text-sky-300"
                data-testid="paired-chat-link"
                aria-label={`Open paired chat: ${pairedChat.title ?? 'Untitled chat'}`}
                title={pairedChat.title ?? 'Untitled chat'}
                onclick={() => handleOpenPairedChat(pairedChat.id)}
              >
                → {pairedChat.title ?? 'Untitled chat'}
              </button>
            {:else if !parentOf}
              <button
                type="button"
                class="text-xs text-slate-400 opacity-0 hover:text-sky-400 group-hover:opacity-100"
                aria-label={`Work on ${item.label} in a new chat`}
                title="Work on this"
                onclick={() => handleWorkOnThis(item.id)}
              >
                💬
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
          </div>
          {#if parentOf}
            <ul class="mt-1 ml-6 flex flex-col gap-1 border-l border-slate-800 pl-2">
              {#each childrenByParent.get(item.id) ?? [] as child (child.id)}
                {@render itemRow(child)}
              {/each}
            </ul>
          {/if}
        </li>
      {/snippet}

      <ul class="flex flex-col gap-1">
        {#each rootItems as root (root.id)}
          {@render itemRow(root)}
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
