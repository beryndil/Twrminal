<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { TodoItem } from '$lib/api';

  /**
   * Live TodoWrite snapshot rendered as a sticky card at the top of
   * the Conversation pane. Mirrors the checkbox widget the Claude
   * Code CLI renders inline when the agent calls the `TodoWrite`
   * tool — Bearings gets one persistent card that reflects the
   * latest state, instead of one stale widget per-turn in the
   * conversation flow.
   *
   * Data source (see `agent/events.TodoWriteUpdate` on the backend):
   * full-replacement semantics — every `todo_write_update` event
   * overwrites the list entirely, no per-item merge. The reducer
   * just assigns; this component just renders.
   *
   * Tri-state glyphs track the SDK's status enum:
   *   pending     — ○ slate
   *   in_progress — ● amber (mirrors the running-tool-call indicator
   *                 in MessageTurn so the same "work in flight"
   *                 visual language applies across the UI)
   *   completed   — ✓ emerald
   *
   * When the active item has an `active_form` ("Running the tests")
   * distinct from its `content` ("Run the tests"), the card surfaces
   * the active form below the list so "what is the agent doing
   * right now" stays answerable without scrolling into the tool-call
   * panel. Multiple `in_progress` entries are uncommon in practice
   * (the tool prompt nudges the model toward single-active) but
   * supported — we show the first one's active form.
   *
   * Visibility (v2, L5.7): the card renders only when the latest
   * TodoWrite carries at least one item. `null` (never invoked) and
   * `[]` (explicitly cleared) both hide the widget. The data layer
   * still distinguishes the two — see `conversation.todos` and
   * `SessionTodos.todos` — but the user-visible card treats them the
   * same: nothing in flight, nothing to show. The previous behaviour
   * of rendering an empty "no active todos" footer was visual noise
   * that paid no information dividend.
   *
   * Auto-collapse (v2, L5.7): when every item in the latest list is
   * `completed` and the user hasn't already collapsed, a 30s timer
   * shrinks the card to header-only. Fires on the *edge* into
   * all-completed, not on every update — a fresh add to an already
   * all-done list doesn't restart the countdown, and a manual toggle
   * cancels any pending timer so the user always wins.
   */

  type Props = {
    /** Null = session has never invoked TodoWrite; render nothing.
     * Empty array = agent explicitly cleared the list; also render
     * nothing. The data layer keeps the distinction (matters for
     * the reducer / WS replay) but the widget treats both as "no
     * card." */
    todos: TodoItem[] | null;
  };

  const { todos }: Props = $props();

  // Collapse toggle — when the list grows tall it crowds the scroll
  // area. The button in the bottom-right hides the list while keeping
  // the header row visible so the completed/total counter and the
  // active-form line stay glanceable.
  //
  // Persisted to localStorage so the preference survives page
  // refreshes. Mirrors the pattern in `stores/tags.svelte.ts` for the
  // tag-filter panel collapsed state: SSR-guarded, try/catch-wrapped
  // (private-mode / quota), '1' = collapsed, '0' = expanded.
  const COLLAPSED_KEY = 'bearings.liveTodos.collapsed';

  function readCollapsed(): boolean {
    if (typeof localStorage === 'undefined') return false;
    try {
      return localStorage.getItem(COLLAPSED_KEY) === '1';
    } catch {
      return false;
    }
  }

  function writeCollapsed(value: boolean): void {
    if (typeof localStorage === 'undefined') return;
    try {
      localStorage.setItem(COLLAPSED_KEY, value ? '1' : '0');
    } catch {
      // Quota exhausted / private-mode — cosmetic preference, skip.
    }
  }

  let collapsed = $state(readCollapsed());

  // Auto-collapse 30s after the latest update lands all-completed.
  // Constants out of magic-number land per project rules (functions
  // ≤40 lines, no magic numbers). 30s is the shipped default agreed
  // in the L5.7 design; tune here if a real session shows it's wrong.
  const AUTO_COLLAPSE_MS = 30_000;
  let autoCollapseTimer: ReturnType<typeof setTimeout> | null = null;

  function clearAutoCollapseTimer(): void {
    if (autoCollapseTimer !== null) {
      clearTimeout(autoCollapseTimer);
      autoCollapseTimer = null;
    }
  }

  function toggleCollapsed(): void {
    // Manual toggle wins. If a pending auto-collapse was about to
    // fire, kill it — the user just told us what they want, don't
    // fight them 4s later by snapping the card shut again.
    clearAutoCollapseTimer();
    collapsed = !collapsed;
    writeCollapsed(collapsed);
  }

  const completed = $derived(todos?.filter((t) => t.status === 'completed').length ?? 0);
  const total = $derived(todos?.length ?? 0);
  // First `in_progress` entry's active_form, if any. Falls back to
  // the item's `content` when the active form is blank — a noun-form
  // task line beats nothing.
  const activeLine = $derived.by(() => {
    const active = todos?.find((t) => t.status === 'in_progress');
    if (!active) return null;
    return active.active_form ?? active.content;
  });

  function glyph(status: TodoItem['status']): { mark: string; cls: string } {
    switch (status) {
      case 'completed':
        return { mark: '✓', cls: 'text-emerald-400' };
      case 'in_progress':
        return { mark: '●', cls: 'text-amber-400' };
      case 'pending':
        return { mark: '○', cls: 'text-slate-500' };
    }
  }

  // Edge-triggered auto-collapse. We only schedule on the *transition*
  // from "not all completed" → "all completed" so a fresh add to an
  // already-done list (rare but legal) doesn't restart the countdown.
  // `prevAllCompleted` is a plain `let`, not `$state`, so mutating it
  // inside the effect doesn't loop the effect back on itself.
  let prevAllCompleted = false;
  $effect(() => {
    const isAllCompleted = total > 0 && completed === total;
    if (isAllCompleted && !prevAllCompleted) {
      // Edge into all-completed → schedule auto-collapse. Replace any
      // stale timer just in case (defensive; clearAutoCollapseTimer is
      // a no-op when nothing's pending).
      clearAutoCollapseTimer();
      autoCollapseTimer = setTimeout(() => {
        autoCollapseTimer = null;
        if (collapsed) return; // user beat us to it via the chevron
        collapsed = true;
        writeCollapsed(true);
      }, AUTO_COLLAPSE_MS);
    } else if (!isAllCompleted) {
      // Left all-completed (new pending/in_progress item arrived) →
      // cancel the pending shrink. Don't auto-expand; if the user had
      // collapsed manually they probably still want it collapsed.
      clearAutoCollapseTimer();
    }
    prevAllCompleted = isAllCompleted;
  });

  // Component unmount (session switch / pane teardown). Without this
  // the timer keeps a closure alive on the destroyed component and
  // fires harmlessly-but-pointlessly. Effect cleanup would also run
  // on every dependency change which would defeat the schedule.
  onDestroy(clearAutoCollapseTimer);
</script>

{#if todos !== null && todos.length > 0}
  <section
    class="border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs"
    aria-label="Agent todo list"
  >
    <header class="flex items-center justify-between gap-2 text-slate-300">
      <span class="font-medium uppercase tracking-wider text-[10px]">
        todos · {completed}/{total}
      </span>
      <div class="flex items-center gap-2 min-w-0">
        {#if activeLine}
          <span class="truncate text-slate-400" title={activeLine}>
            {activeLine}
          </span>
        {/if}
        {#if collapsed}
          <!-- When collapsed, inline the toggle in the header so the
               card is a single row. Moving it to a second justify-end
               div (as in the expanded state) would double the height
               of a card that has nothing else to show. -->
          <button
            type="button"
            class="text-slate-500 hover:text-slate-300 text-[10px] leading-none px-1 shrink-0"
            onclick={toggleCollapsed}
            aria-label="Expand todo list"
            aria-expanded="false"
            data-testid="live-todos-collapse"
          >
            ⌄
          </button>
        {/if}
      </div>
    </header>
    {#if !collapsed}
      <ul class="mt-1 space-y-0.5">
        {#each todos ?? [] as todo, i (i)}
          {@const g = glyph(todo.status)}
          <li class="flex items-start gap-2">
            <span class={`mt-[1px] ${g.cls}`} aria-hidden="true">{g.mark}</span>
            <span
              class={todo.status === 'completed'
                ? 'text-slate-500 line-through'
                : 'text-slate-200'}
            >
              {todo.content}
            </span>
          </li>
        {/each}
      </ul>
      <div class="flex justify-end mt-1">
        <button
          type="button"
          class="text-slate-500 hover:text-slate-300 text-[10px] leading-none px-1"
          onclick={toggleCollapsed}
          aria-label="Collapse todo list"
          aria-expanded="true"
          data-testid="live-todos-collapse"
        >
          ⌃
        </button>
      </div>
    {/if}
  </section>
{/if}
