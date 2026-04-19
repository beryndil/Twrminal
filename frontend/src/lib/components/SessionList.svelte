<script lang="ts">
  import { onMount } from 'svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { agent } from '$lib/agent.svelte';

  const CONFIRM_TIMEOUT_MS = 3_000;

  let showNewForm = $state(false);
  let newWorkingDir = $state('');
  let newModel = $state('claude-sonnet-4-6');
  let newTitle = $state('');
  let newBudget = $state('');
  let submitting = $state(false);
  const confirm = $state<{ id: string | null }>({ id: null });
  let confirmTimer: ReturnType<typeof setTimeout> | null = null;

  function clearConfirm() {
    if (confirmTimer !== null) {
      clearTimeout(confirmTimer);
      confirmTimer = null;
    }
    confirm.id = null;
  }

  onMount(async () => {
    await sessions.refresh();
    if (sessions.selectedId) {
      await agent.connect(sessions.selectedId);
    }
  });

  async function onCreate() {
    submitting = true;
    const budgetTrimmed = newBudget.trim();
    const budget = budgetTrimmed ? Number(budgetTrimmed) : null;
    const created = await sessions.create({
      working_dir: newWorkingDir.trim() || '/tmp',
      model: newModel.trim() || 'claude-sonnet-4-6',
      title: newTitle.trim() || null,
      max_budget_usd: budget !== null && Number.isFinite(budget) ? budget : null
    });
    submitting = false;
    if (created) {
      showNewForm = false;
      newWorkingDir = '';
      newTitle = '';
      newBudget = '';
      await agent.connect(created.id);
    }
  }

  async function onSelect(id: string) {
    sessions.select(id);
    await agent.connect(id);
  }

  async function onDelete(e: MouseEvent, id: string) {
    e.stopPropagation();
    if (confirm.id !== id) {
      confirm.id = id;
      if (confirmTimer !== null) clearTimeout(confirmTimer);
      confirmTimer = setTimeout(clearConfirm, CONFIRM_TIMEOUT_MS);
      return;
    }
    clearConfirm();
    if (agent.sessionId === id) agent.close();
    await sessions.remove(id);
  }

  function formatTimestamp(ts: string): string {
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  }
</script>

<aside class="bg-slate-900 p-4 overflow-y-auto border-r border-slate-800 flex flex-col gap-3">
  <div class="flex items-center justify-between">
    <h2 class="text-sm uppercase tracking-wider text-slate-400">Sessions</h2>
    <button
      type="button"
      class="text-xs rounded bg-slate-800 hover:bg-slate-700 px-2 py-1"
      onclick={() => (showNewForm = !showNewForm)}
      aria-label="Toggle new session form"
    >
      {showNewForm ? 'Cancel' : '+ New'}
    </button>
  </div>

  {#if showNewForm}
    <form
      class="flex flex-col gap-2 rounded bg-slate-800/60 p-3"
      onsubmit={(e) => {
        e.preventDefault();
        onCreate();
      }}
    >
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400">Working dir</span>
        <input
          type="text"
          class="rounded bg-slate-950 px-2 py-1 text-sm"
          placeholder="/home/..."
          bind:value={newWorkingDir}
        />
      </label>
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400">Model</span>
        <input
          type="text"
          class="rounded bg-slate-950 px-2 py-1 text-sm font-mono"
          bind:value={newModel}
        />
      </label>
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400">Title <span class="text-slate-600">(optional)</span></span>
        <input
          type="text"
          class="rounded bg-slate-950 px-2 py-1 text-sm"
          bind:value={newTitle}
        />
      </label>
      <label class="flex flex-col text-xs gap-1">
        <span class="text-slate-400"
          >Budget USD <span class="text-slate-600">(optional)</span></span
        >
        <input
          type="number"
          inputmode="decimal"
          step="0.01"
          min="0"
          placeholder="no cap"
          class="rounded bg-slate-950 px-2 py-1 text-sm font-mono"
          bind:value={newBudget}
        />
      </label>
      <button
        type="submit"
        class="rounded bg-emerald-600 hover:bg-emerald-500 px-2 py-1 text-sm mt-1 disabled:opacity-50"
        disabled={submitting}
      >
        {submitting ? 'Creating…' : 'Create session'}
      </button>
    </form>
  {/if}

  {#if sessions.error}
    <p class="text-xs text-rose-400">{sessions.error}</p>
  {/if}

  {#if sessions.loading && sessions.list.length === 0}
    <p class="text-slate-500 text-sm">Loading…</p>
  {:else if sessions.list.length === 0}
    <p class="text-slate-500 text-sm">No sessions yet.</p>
  {:else}
    <ul class="flex flex-col gap-1">
      {#each sessions.list as session (session.id)}
        <li
          class="group flex items-stretch gap-1 rounded hover:bg-slate-800 {sessions.selectedId ===
          session.id
            ? 'bg-slate-800'
            : ''}"
        >
          <button
            type="button"
            class="flex-1 min-w-0 text-left px-2 py-2 rounded-l"
            onclick={() => onSelect(session.id)}
          >
            <div class="text-sm truncate">
              {session.title ?? session.model}
            </div>
            <div class="text-[10px] text-slate-500 font-mono truncate">
              {session.working_dir}
            </div>
            <div class="text-[10px] text-slate-600">
              {formatTimestamp(session.created_at)}
            </div>
          </button>
          <button
            type="button"
            class="px-2 text-xs transition {confirm.id === session.id
              ? 'text-rose-400 font-medium'
              : 'text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100'}"
            aria-label={confirm.id === session.id
              ? 'Confirm delete session'
              : 'Delete session'}
            onclick={(e) => onDelete(e, session.id)}
          >
            {confirm.id === session.id ? 'Confirm?' : '✕'}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</aside>
