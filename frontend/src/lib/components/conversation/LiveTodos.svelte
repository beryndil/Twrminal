<script lang="ts">
  /**
   * Live todos panel — renders the agent's latest ``TodoWrite`` output
   * as a collapsible list inside the conversation pane (item 2.1).
   *
   * State source: ``conversationStore.liveTodos``, populated by the
   * ``todo_write_update`` reducer arm in ``conversation.svelte.ts``.
   * The panel is hidden when ``liveTodos`` is empty so it takes no
   * space during sessions that never call ``TodoWrite``.
   *
   * Design:
   * - Collapsible via a chevron toggle button in the header row.
   * - Each item shows a status icon (✓ completed, ● in-progress, ○
   *   pending) and an optional priority badge (H/M/L) when the item
   *   carries a ``priority`` field (richer TodoWrite variants).
   * - Completed items are rendered with muted text + strikethrough so
   *   active items stand out at a glance.
   * - Panel renders as a sticky strip above the message turns via
   *   ``Conversation.svelte`` layout.
   *
   * Key stability: ``todo.id`` is preferred; falls back to index so
   * the SDK's built-in TodoWrite (which omits ``id``) does not trigger
   * Svelte's ``each_key_duplicate`` error.
   */
  import { LIVE_TODOS_STRINGS } from "../../config";
  import { conversationStore, type LiveTodoItem } from "../../stores/conversation.svelte";

  let open = $state(true);

  const todos = $derived(conversationStore.liveTodos);
  const visible = $derived(todos.length > 0);

  function toggle(): void {
    open = !open;
  }

  function statusIcon(status: string): string {
    if (status === "completed") return "✓";
    if (status === "in_progress") return "●";
    return "○";
  }

  function priorityLabel(priority: string): string {
    if (priority === "high") return "H";
    if (priority === "medium") return "M";
    return "L";
  }

  function priorityClass(priority: string): string {
    if (priority === "high") return "text-red-400";
    if (priority === "medium") return "text-yellow-400";
    return "text-fg-muted";
  }

  /** Stable per-item key: prefer id, fall back to content, then index. */
  function todoKey(todo: LiveTodoItem, i: number): string {
    return todo.id ?? todo.content ?? String(i);
  }
</script>

{#if visible}
  <div class="live-todos border-b border-border bg-surface-1" data-testid="live-todos">
    <!-- Header row -->
    <button
      type="button"
      class="flex w-full items-center gap-2 px-4 py-2 text-left text-xs font-medium text-fg-muted hover:text-fg-strong"
      aria-label={open
        ? LIVE_TODOS_STRINGS.panelCollapseAriaLabel
        : LIVE_TODOS_STRINGS.panelExpandAriaLabel}
      aria-expanded={open}
      onclick={toggle}
      data-testid="live-todos-toggle"
    >
      <span class="select-none transition-transform {open ? 'rotate-90' : ''}">▶</span>
      <span>{LIVE_TODOS_STRINGS.panelLabel}</span>
      <span class="ml-auto tabular-nums text-fg-muted">
        {todos.filter((t) => t.status === "completed").length}/{todos.length}
      </span>
    </button>

    <!-- Item list -->
    {#if open}
      <ul class="px-4 pb-2" data-testid="live-todos-list">
        {#each todos as todo, i (todoKey(todo, i))}
          <li
            class="flex items-start gap-2 py-0.5 text-xs leading-snug"
            data-testid="live-todo-item"
            data-status={todo.status}
          >
            <!-- Status icon -->
            <span
              class="mt-0.5 shrink-0 font-mono {todo.status === 'completed'
                ? 'text-fg-muted'
                : todo.status === 'in_progress'
                  ? 'text-accent'
                  : 'text-fg-muted'}"
              aria-label={todo.status === "completed"
                ? LIVE_TODOS_STRINGS.statusCompleted
                : todo.status === "in_progress"
                  ? LIVE_TODOS_STRINGS.statusInProgress
                  : LIVE_TODOS_STRINGS.statusPending}
            >
              {statusIcon(todo.status)}
            </span>

            <!-- Content -->
            <span
              class="flex-1 {todo.status === 'completed'
                ? 'text-fg-muted line-through'
                : 'text-fg-strong'}"
            >
              {todo.content}
            </span>

            <!-- Priority badge — only rendered when the field is present -->
            {#if todo.priority !== undefined}
              <span
                class="shrink-0 font-mono font-bold {priorityClass(todo.priority)}"
                title={todo.priority === "high"
                  ? LIVE_TODOS_STRINGS.priorityHigh
                  : todo.priority === "medium"
                    ? LIVE_TODOS_STRINGS.priorityMedium
                    : LIVE_TODOS_STRINGS.priorityLow}
              >
                {priorityLabel(todo.priority)}
              </span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
