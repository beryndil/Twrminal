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
  import type { AutoRunStatus, ChecklistItem } from '$lib/api';
  import { getAutoRun, startAutoRun, stopAutoRun } from '$lib/api/checklists';
  import { checklists } from '$lib/stores/checklists.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';
  import ChecklistChat from '$lib/components/ChecklistChat.svelte';

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
    // 2026-04-25: backend `toggle_item` now owns the close cascade.
    // When an item becomes checked, the storage layer closes EVERY
    // paired chat for that item (forward + handoff legs + nested
    // children) and auto-closes the parent checklist session if the
    // whole list completes. The frontend used to handle just the
    // forward-pointer chat here, missing handoff legs; that path is
    // gone — backend is now the single source of truth.
    //
    // Unchecking stays as a pure flag flip: reopening a closed chat
    // is a user decision that belongs in the sidebar, not this
    // affordance.
    await checklists.toggle(itemId, checked);
    // Refresh the sessions list so any sidebar entry that just
    // closed (the item's legs, or the whole checklist when this
    // toggle completed it) moves into the Closed group on the
    // next tick. The ChecklistView stays mounted — selected.id
    // still matches the (possibly now-closed) checklist row.
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

  // --- autonomous run -----------------------------------------------
  //
  // Tied to the selected checklist session. `runStatus` is the last
  // snapshot we've seen from the server; the poll loop below refreshes
  // it every 1s while `state === 'running'` and stops once the driver
  // reports `finished` or `errored`. Mounting a different checklist
  // resets the state cleanly via the `$effect` that watches
  // `selected.id`.
  let runStatus = $state<AutoRunStatus | null>(null);
  let runBusy = $state(false);
  let runError = $state<string | null>(null);
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  // Tour-mode toggle: when on, the next "Run autonomously" click
  // launches with `failure_policy='skip'` AND
  // `visit_existing_sessions=true`. These two flags travel together
  // because the documented use case is the same — walk a curated
  // list of pre-paired sessions, skip the ones that don't tidy up,
  // and don't halt the whole run on the first hard item. Off by
  // default to preserve the original spawn-fresh / halt-on-failure
  // behavior. Persists across the same selected session but resets
  // when the user switches checklists (the $effect below clears it).
  let tourMode = $state(false);

  // Poll interval for the autonomous run. 1s is plenty — individual
  // agent turns take seconds to tens of seconds, and the status
  // endpoint is cheap (in-memory lookup). Shorter would burn battery
  // on an idle tab for no user-visible benefit.
  const AUTO_RUN_POLL_MS = 1000;

  function clearPollTimer() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function schedulePoll(sessionId: string) {
    clearPollTimer();
    pollTimer = setTimeout(() => {
      void pollAutoRun(sessionId);
    }, AUTO_RUN_POLL_MS);
  }

  async function pollAutoRun(sessionId: string) {
    // If the user switched sessions mid-poll, bail — the switch's
    // $effect cleanup already reset runStatus and cleared the timer.
    if (selected?.id !== sessionId) return;
    try {
      const status = await getAutoRun(sessionId);
      runStatus = status;
      if (status.state === 'running') {
        schedulePoll(sessionId);
      } else {
        // Finished / errored — stop polling and refresh the checklist
        // so newly-completed items, auto-run failure notes, and any
        // appended followups all render on the next tick.
        clearPollTimer();
        await checklists.load(sessionId);
      }
    } catch (err) {
      // 404 = no run ever started (or it was DELETEd). Clear status
      // so the button returns to its idle label. Anything else is a
      // transient network error; show it and stop polling.
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('404')) {
        runStatus = null;
      } else {
        runError = msg;
        clearPollTimer();
      }
    }
  }

  // Reset autonomous-run state when the selected session changes so a
  // stale status from a prior checklist never bleeds through. We
  // deliberately do NOT probe the server on mount — a probe race with
  // the checklist-load fetch complicated test ordering, and the UX
  // cost of missing a pre-existing run on page refresh is small (a
  // second "Run" click returns 409; user can DELETE + retry). If
  // surfacing pre-existing runs becomes important, wire a WS push
  // on the sessions broker instead of polling.
  $effect(() => {
    const _sid = selected?.id ?? null;
    clearPollTimer();
    runStatus = null;
    runError = null;
    // Reset the tour-mode checkbox on session switch so a tour-mode
    // run on one checklist doesn't silently apply to the next.
    tourMode = false;
  });

  onDestroy(() => {
    clearPollTimer();
  });

  async function handleStartAutoRun() {
    const sid = selected?.id;
    if (!sid || selected?.kind !== 'checklist' || runBusy) return;
    runBusy = true;
    runError = null;
    // Tour mode: visit each item's pre-linked chat session and skip
    // failures rather than halting. Otherwise omit the body entirely
    // so the server uses the conservative spawn-fresh + halt defaults.
    const body = tourMode
      ? { failure_policy: 'skip' as const, visit_existing_sessions: true }
      : {};
    try {
      const status = await startAutoRun(sid, body);
      runStatus = status;
      if (status.state === 'running') schedulePoll(sid);
    } catch (err) {
      runError = err instanceof Error ? err.message : String(err);
    } finally {
      runBusy = false;
    }
  }

  async function handleStopAutoRun() {
    const sid = selected?.id;
    if (!sid || runBusy) return;
    runBusy = true;
    try {
      await stopAutoRun(sid);
      clearPollTimer();
      runStatus = null;
      runError = null;
      // Reload the checklist so any mid-run state (partial
      // completions, failure notes) surfaces immediately.
      await checklists.load(sid);
    } catch (err) {
      runError = err instanceof Error ? err.message : String(err);
    } finally {
      runBusy = false;
    }
  }

  /** Short label for the status pill. Kept terse — the pill lives in
   * the header beside the title, and verbose outcome strings would
   * push other controls off-screen on narrow panes. */
  function pillLabel(status: AutoRunStatus): string {
    if (status.state === 'running') {
      const done = status.items_completed ?? 0;
      const legs = status.legs_spawned ?? 0;
      return legs > 1
        ? `running · ${done} done · leg ${legs}`
        : `running · ${done} done`;
    }
    if (status.state === 'errored') return 'errored';
    // Finished — derive from outcome.
    const outcome = status.outcome ?? 'finished';
    if (outcome === 'completed') {
      const done = status.items_completed ?? 0;
      return `done · ${done} completed`;
    }
    if (outcome === 'halted_empty') return 'nothing to do';
    if (outcome === 'halted_failure') return 'failed';
    if (outcome === 'halted_max_items') return 'hit item cap';
    if (outcome === 'halted_stop') return 'stopped';
    return outcome;
  }

  function pillTone(status: AutoRunStatus): string {
    if (status.state === 'running') return 'bg-sky-800 text-sky-100';
    if (status.state === 'errored') return 'bg-rose-800 text-rose-100';
    const outcome = status.outcome ?? '';
    if (outcome === 'completed') return 'bg-emerald-800 text-emerald-100';
    if (outcome === 'halted_failure') return 'bg-rose-800 text-rose-100';
    if (outcome === 'halted_stop' || outcome === 'halted_max_items')
      return 'bg-amber-800 text-amber-100';
    return 'bg-slate-700 text-slate-200';
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

    <!-- Autonomous-run affordances. Status pill renders when there's
         a snapshot; Run / Stop buttons swap based on whether a run is
         active. Hidden on non-checklist sessions (the enclosing
         `selected.kind === 'checklist'` render condition covers it
         indirectly, but the explicit check here is defensive if the
         header is ever extracted from this component). -->
    {#if selected?.kind === 'checklist' && !selected.closed_at}
      {#if runStatus}
        <span
          class="rounded px-2 py-0.5 text-xs font-medium {pillTone(runStatus)}"
          title={runStatus.failure_reason ?? runStatus.error ?? undefined}
          data-testid="auto-run-pill"
        >
          {pillLabel(runStatus)}
        </span>
      {/if}
      {#if runStatus?.state === 'running'}
        <button
          type="button"
          class="rounded border border-rose-700 px-2 py-0.5 text-xs text-rose-300 hover:bg-rose-900 hover:text-rose-100 disabled:opacity-50"
          disabled={runBusy}
          onclick={handleStopAutoRun}
          data-testid="auto-run-stop"
        >
          Stop
        </button>
      {:else}
        <label
          class="flex items-center gap-1 text-xs text-slate-400"
          title="Tour mode: visit each item's pre-linked chat session and skip failures (instead of spawning fresh chats and halting on first failure)."
        >
          <input
            type="checkbox"
            class="h-3 w-3 rounded border-slate-700 bg-slate-900 text-sky-500 focus:ring-sky-500"
            bind:checked={tourMode}
            data-testid="auto-run-tour-mode"
          />
          Tour
        </label>
        <button
          type="button"
          class="rounded border border-sky-700 px-2 py-0.5 text-xs text-sky-300 hover:bg-sky-900 hover:text-sky-100 disabled:opacity-50"
          disabled={runBusy}
          onclick={handleStartAutoRun}
          data-testid="auto-run-start"
        >
          {runStatus ? 'Run again' : 'Run autonomously'}
        </button>
      {/if}
    {/if}
  </header>
  {#if runError}
    <p class="border-b border-rose-900 bg-rose-950 px-4 py-2 text-xs text-rose-300">
      Autonomous run error: {runError}
    </p>
  {/if}

  <!-- v0.5.2: inline chat about the whole list. Mounted only when a
       checklist is selected so the agent WS never opens for a
       transient null selection. Compact by design — height-capped so
       the checklist body stays reachable below. -->
  {#if selected?.kind === 'checklist'}
    <ChecklistChat />
  {/if}

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
