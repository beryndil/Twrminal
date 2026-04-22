<script lang="ts">
  import type { Action, ActionContext } from '$lib/context-menu/types';

  type Props = {
    action: Action;
    ctx: ActionContext;
    onDone: () => void;
    /** Zero-based position in the flat (section-order) action list.
     * ContextMenu.svelte uses this to route keyboard-FSM focus via
     * `[data-flat-index="..."]` queries rather than a ref map. */
    flatIndex: number;
  };

  const { action, ctx, onDone, flatIndex }: Props = $props();

  // Phase 1: `disabled` is a predicate but no action ships with one yet.
  // Still respect it — when Phase 4 introduces "Coming in v0.9.2"
  // tooltips per decision §2.3 they need to render correctly.
  const disabledReason = $derived(action.disabled?.(ctx.target) ?? null);

  async function onClick(e: MouseEvent): Promise<void> {
    e.stopPropagation();
    if (disabledReason !== null) return;
    try {
      await action.handler(ctx);
    } catch (err) {
      // Phase 1 has no toast host; log loudly so failures aren't
      // silent. Phase 3 routes this through StubToast / error toast.
      // eslint-disable-next-line no-console
      console.error('[context-menu] handler threw', action.id, err);
    } finally {
      onDone();
    }
  }
</script>

<button
  type="button"
  role="menuitem"
  class="w-full text-left px-3 py-1.5 text-xs flex items-center gap-2
    hover:bg-slate-800 focus:bg-slate-800 focus:outline-none
    {disabledReason !== null ? 'opacity-40 cursor-not-allowed' : 'text-slate-200'}
    {action.destructive ? 'text-rose-300' : ''}"
  aria-disabled={disabledReason !== null}
  title={disabledReason ?? undefined}
  data-action-id={action.id}
  data-flat-index={flatIndex}
  data-testid="context-menu-item"
  onclick={onClick}
>
  <span class="flex-1 min-w-0 truncate">{action.label}</span>
  {#if action.shortcut}
    <span class="text-[10px] text-slate-500 font-mono shrink-0">
      {action.shortcut}
    </span>
  {/if}
</button>
