<script lang="ts">
  /**
   * Checkpoint gutter — renders a horizontal chip strip at the top of
   * the conversation, one chip per checkpoint (newest first, matching
   * the store's order). Each chip:
   *   - Shows its label (or "Untitled" when null).
   *   - Click → scrolls the anchor message into view. Disabled when the
   *     anchor was dropped in a reorg audit (message_id null).
   *   - Right-click → opens the context menu with fork / copy / delete.
   *   - Shift+right-click → advanced-mode menu (adds "Copy checkpoint ID").
   *
   * The gutter lives outside MessageTurn on purpose: anchoring chips
   * inline would force absolute-positioning math on every scroll, and
   * the strip gives users an overview of every fork point in one place.
   * A later slice may add sidebar-gutter positioning once the Conversation
   * sidebar work from Phase 9 lands.
   */

  import { checkpoints } from '$lib/stores/checkpoints.svelte';
  import { contextmenu } from '$lib/actions/contextmenu';
  import { scrollBehavior } from '$lib/utils/motion';
  import type { Checkpoint } from '$lib/api';

  type Props = {
    sessionId: string;
  };

  const { sessionId }: Props = $props();

  const list = $derived<Checkpoint[]>(checkpoints.forSession(sessionId));

  // Load on mount / when session changes. Keeping this inside the
  // component (rather than in Conversation.svelte) means the gutter is
  // drop-in: mounting it is the only plumbing the host needs.
  $effect(() => {
    void checkpoints.load(sessionId);
  });

  /** Scroll the anchor message into view and briefly highlight it.
   * Mirrors the jump behavior in `actions/message.ts:jumpToTurn` so
   * the UX is consistent between "right-click message → scroll" and
   * "click gutter chip → scroll". */
  function jumpTo(messageId: string | null): void {
    if (messageId === null || typeof document === 'undefined') return;
    const el = document.querySelector<HTMLElement>(
      `[data-message-id="${CSS.escape(messageId)}"]`
    );
    if (!el) return;
    el.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
    const prev = el.style.outline;
    const prevOffset = el.style.outlineOffset;
    el.style.outline = '2px solid rgb(236, 72, 153)';
    el.style.outlineOffset = '2px';
    setTimeout(() => {
      el.style.outline = prev;
      el.style.outlineOffset = prevOffset;
    }, 1500);
  }

  function chipLabel(cp: Checkpoint): string {
    return cp.label && cp.label.trim() !== '' ? cp.label : 'Untitled';
  }
</script>

{#if list.length > 0}
  <div
    class="flex flex-wrap items-center gap-1.5 border-b border-slate-800
      bg-slate-900/60 px-3 py-1.5 text-[11px]"
    data-testid="checkpoint-gutter"
  >
    <span class="text-slate-500 uppercase tracking-wider">Checkpoints</span>
    {#each list as cp (cp.id)}
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5
          transition-colors disabled:cursor-not-allowed
          {cp.message_id === null
          ? 'border-slate-700 bg-slate-900 text-slate-500 italic'
          : 'border-fuchsia-900/60 bg-fuchsia-950/30 text-fuchsia-200 hover:border-fuchsia-600 hover:bg-fuchsia-900/40'}"
        title={cp.message_id === null
          ? 'Anchor message dropped in a reorg — right-click to delete'
          : `Click to jump · right-click for fork & more`}
        disabled={cp.message_id === null}
        onclick={() => jumpTo(cp.message_id)}
        use:contextmenu={{
          target: {
            type: 'checkpoint',
            id: cp.id,
            sessionId: cp.session_id,
            messageId: cp.message_id,
            label: cp.label
          }
        }}
        data-testid="checkpoint-chip"
        data-checkpoint-id={cp.id}
      >
        <span aria-hidden="true" class="text-[9px]">◆</span>
        <span>{chipLabel(cp)}</span>
      </button>
    {/each}
  </div>
{/if}
