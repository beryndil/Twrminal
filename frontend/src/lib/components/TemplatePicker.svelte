<script lang="ts">
  /**
   * Template picker (Phase 9b.3 of docs/context-menu-plan.md).
   *
   * Lives in the sidebar header next to "+ New". Clicking the 📋 button
   * toggles a small dropdown that lists saved templates newest-first;
   * clicking a row calls `templates.instantiate(id)`, navigates to the
   * new session, and closes the panel. Each row has a × to delete.
   *
   * Instantiation without overrides works only when the saved template
   * carried both a working_dir and a model. If the backend 400s
   * ("working_dir required (template had none)" / "model required"),
   * the error surfaces via the store's `error` field rather than
   * blocking the UI — a later phase can add an "instantiate with
   * overrides" modal to fill in the missing pieces.
   *
   * Visual parity with the existing icon buttons (⇡, ⚙, + New) is
   * intentional so the button doesn't look bolted on.
   */

  import { agent } from '$lib/agent.svelte';
  import { sessions } from '$lib/stores/sessions.svelte';
  import { templates } from '$lib/stores/templates.svelte';
  import { uiActions } from '$lib/stores/ui_actions.svelte';
  import BearingsMark from '$lib/components/icons/BearingsMark.svelte';

  // Open state lives on the shared `uiActions` store so the keyboard
  // registry's `t` action and `Esc` cascade can flip the picker
  // without holding a component ref. Local mirror keeps the rest of
  // the file readable; `$derived` ties it to the store.
  const open = $derived(uiActions.templatePickerOpen);
  // Per-row confirm for delete — two-click pattern identical to the
  // session-row ✕ button in SessionList. Prevents accidental wipes of a
  // saved template.
  const confirmDelete = $state<{ id: string | null }>({ id: null });
  let confirmTimer: ReturnType<typeof setTimeout> | null = null;
  const CONFIRM_TIMEOUT_MS = 3_000;

  function clearConfirm() {
    if (confirmTimer !== null) {
      clearTimeout(confirmTimer);
      confirmTimer = null;
    }
    confirmDelete.id = null;
  }

  async function toggle() {
    if (uiActions.templatePickerOpen) {
      uiActions.templatePickerOpen = false;
      clearConfirm();
      return;
    }
    uiActions.openTemplatePicker();
    await templates.refresh();
  }

  // Auto-refresh when the picker opens via the keyboard registry
  // (uiActions.openTemplatePicker doesn't await templates.refresh
  // because it's called from a synchronous keydown handler). The
  // effect re-runs only on transitions, not on every store tick.
  let lastSeenOpen = false;
  $effect(() => {
    const now = uiActions.templatePickerOpen;
    if (now && !lastSeenOpen) void templates.refresh();
    if (!now && lastSeenOpen) clearConfirm();
    lastSeenOpen = now;
  });

  async function onPick(id: string) {
    const created = await templates.instantiate(id);
    if (!created) return;
    uiActions.templatePickerOpen = false;
    sessions.select(created.id);
    await agent.connect(created.id);
  }

  async function onDelete(e: MouseEvent, id: string) {
    e.stopPropagation();
    if (confirmDelete.id !== id) {
      confirmDelete.id = id;
      if (confirmTimer !== null) clearTimeout(confirmTimer);
      confirmTimer = setTimeout(clearConfirm, CONFIRM_TIMEOUT_MS);
      return;
    }
    clearConfirm();
    await templates.remove(id);
  }
</script>

<div class="relative">
  <button
    type="button"
    class="text-[11px] rounded bg-slate-800 hover:bg-slate-700 px-1.5 py-0.5"
    aria-label="Open template picker"
    aria-expanded={open}
    title="Start a session from a saved template"
    onclick={toggle}
    data-testid="template-picker-toggle"
  >
    📋
  </button>
  {#if open}
    <div
      class="absolute right-0 top-full mt-1 w-64 rounded border border-slate-700
        bg-slate-900 shadow-lg z-20 text-xs"
      role="menu"
      data-testid="template-picker-panel"
    >
      <div
        class="px-2 py-1 uppercase tracking-wider text-[10px] text-slate-500
          border-b border-slate-800 flex items-center justify-between"
      >
        <span>Templates</span>
        {#if templates.loading}
          <span
            class="inline-flex items-center gap-1 text-slate-600 normal-case tracking-normal"
          >
            <BearingsMark size={10} spin label="Loading templates" />
            loading…
          </span>
        {/if}
      </div>
      {#if templates.error}
        <p class="px-2 py-1 text-rose-400">{templates.error}</p>
      {/if}
      {#if templates.list.length === 0 && !templates.loading}
        <p class="px-2 py-2 text-slate-500">
          No templates yet. Right-click a session → Save as template…
        </p>
      {:else}
        <ul class="max-h-72 overflow-y-auto">
          {#each templates.list as t (t.id)}
            <li class="group flex items-stretch hover:bg-slate-800">
              <button
                type="button"
                class="flex-1 text-left px-2 py-1 min-w-0"
                onclick={() => onPick(t.id)}
                data-testid="template-picker-row"
              >
                <div class="truncate">{t.name}</div>
                <div class="text-[10px] text-slate-500 font-mono truncate">
                  {t.working_dir ?? '— no working dir —'}
                </div>
              </button>
              <button
                type="button"
                class="px-1.5 text-[11px] transition {confirmDelete.id === t.id
                  ? 'text-rose-400 font-medium'
                  : 'text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100'}"
                aria-label={confirmDelete.id === t.id
                  ? 'Confirm delete template'
                  : 'Delete template'}
                onclick={(e) => onDelete(e, t.id)}
                data-testid="template-picker-delete"
              >
                {confirmDelete.id === t.id ? 'Confirm?' : '✕'}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</div>
