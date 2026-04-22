<script lang="ts">
  import { confirmStore } from '$lib/context-menu/confirm.svelte';
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

  // `disabled` is a predicate; Phase 3 still ships no action with one,
  // but decision §2.3 reserves the shape for "Coming in v0.9.2"
  // tooltips that Phase 4+ will introduce.
  const disabledReason = $derived(action.disabled?.(ctx.target) ?? null);

  async function runHandler(): Promise<void> {
    try {
      await action.handler(ctx);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('[context-menu] handler threw', action.id, err);
    }
  }

  async function onClick(e: MouseEvent): Promise<void> {
    e.stopPropagation();
    if (disabledReason !== null) return;
    // Destructive actions route through the session-scoped confirm
    // store (plan §6.7). The store itself handles the "don't ask
    // again" short-circuit — if the user has already suppressed this
    // action/target pair, the handler fires inline without a dialog.
    if (action.destructive) {
      // Close the menu first so the dialog doesn't land over it.
      onDone();
      await confirmStore.request({
        actionId: action.id,
        targetType: ctx.target.type,
        message: `${action.label}?`,
        confirmLabel: action.label,
        destructive: true,
        onConfirm: runHandler
      });
      return;
    }
    await runHandler();
    onDone();
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
