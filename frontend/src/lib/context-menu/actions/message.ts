/**
 * Message-target actions — Phase 5 of the context-menu plan.
 *
 * Absorbs the `⋯` popover that used to live in `MessageTurn.svelte`:
 * Move-to-session and Split-here now fire as registry actions and
 * route through the `reorgStore` bridge so Conversation.svelte (which
 * owns the picker modal) can open it. See `reorg.svelte.ts` for the
 * rationale on why a store and not a prop callback.
 *
 * Every mutating handler is thin — lookups go back to the conversation
 * store to pull the live message row. Snapshotting into the target
 * would leave copy actions stale when a streaming assistant turn edits
 * itself between right-click and handler fire.
 *
 * Pin / hide-from-context are live as of Phase 8 (v0.9.2, migration
 * 0023): both toggle in place via `PATCH /messages/{id}` and reflect
 * immediately in the conversation via `conversation.applyMessagePatch`.
 * `message.delete` stays disabled until its primitive arrives.
 */

import * as api from '$lib/api';
import { checkpoints } from '$lib/stores/checkpoints.svelte';
import { conversation } from '$lib/stores/conversation.svelte';
import { sessions } from '$lib/stores/sessions.svelte';
import { scrollBehavior } from '$lib/utils/motion';
import { writeClipboard } from '../clipboard';
import { reorgStore } from '../reorg.svelte';
import { notYetImplemented } from '../stub.svelte';
import type { Action, ContextTarget, MessageTarget } from '../types';

function asMessage(t: ContextTarget): MessageTarget | null {
  return t.type === 'message' ? t : null;
}

/** Pull the live message row from the conversation store. Returns
 * null when the store hasn't loaded this session yet or the id doesn't
 * exist — handlers treat null as a silent no-op. */
function lookupMessage(id: string): { content: string; role: string } | null {
  const found = conversation.messages.find((m) => m.id === id);
  return found ? { content: found.content, role: found.role } : null;
}

/** Scroll the article DOM node for `messageId` into view and briefly
 * highlight it. The article carries `data-message-id` already (see
 * `MessageTurn.svelte`), so the lookup is a single querySelector. Used
 * by both user and assistant message rows. */
function jumpToTurn(messageId: string): void {
  if (typeof document === 'undefined') return;
  const el = document.querySelector<HTMLElement>(
    `[data-message-id="${CSS.escape(messageId)}"]`
  );
  if (!el) return;
  el.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
  // A 1.5s outline pulse so the user's eye follows the scroll —
  // matches the sidebar-search jump feel. Use outline rather than
  // mutating classes so existing highlight / selection state survives.
  const prev = el.style.outline;
  const prevOffset = el.style.outlineOffset;
  el.style.outline = '2px solid rgb(16, 185, 129)';
  el.style.outlineOffset = '2px';
  setTimeout(() => {
    el.style.outline = prev;
    el.style.outlineOffset = prevOffset;
  }, 1500);
}

export const MESSAGE_ACTIONS: readonly Action[] = [
  {
    id: 'message.jump_to_turn',
    label: 'Scroll into view',
    section: 'navigate',
    mnemonic: 's',
    handler: ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      jumpToTurn(t.id);
    }
  },
  {
    id: 'message.copy_content',
    label: 'Copy message text',
    section: 'copy',
    mnemonic: 'c',
    handler: async ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      const row = lookupMessage(t.id);
      if (!row) return;
      await writeClipboard(row.content);
    }
  },
  {
    id: 'message.copy_as_markdown',
    label: 'Copy as Markdown',
    section: 'copy',
    advanced: true,
    handler: async ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      const row = lookupMessage(t.id);
      if (!row) return;
      // Fence with a role tag on assistant output so a pasted reply
      // retains speaker attribution. User messages paste as-is.
      if (row.role === 'assistant') {
        await writeClipboard(`**Assistant:**\n\n${row.content}`);
        return;
      }
      await writeClipboard(row.content);
    }
  },
  {
    id: 'message.copy_id',
    label: 'Copy message ID',
    section: 'copy',
    advanced: true,
    handler: async ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      await writeClipboard(t.id);
    }
  },
  {
    id: 'message.pin',
    label: 'Pin to turn header',
    section: 'organize',
    handler: async ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      const live = conversation.messages.find((m) => m.id === t.id);
      if (!live) return;
      const nextPinned = !live.pinned;
      const patched = await api.patchMessage(t.id, { pinned: nextPinned });
      conversation.applyMessagePatch(t.sessionId, patched);
    }
  },
  {
    id: 'message.hide_from_context',
    label: 'Hide from context window',
    section: 'organize',
    advanced: true,
    handler: async ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      const live = conversation.messages.find((m) => m.id === t.id);
      if (!live) return;
      const nextHidden = !live.hidden_from_context;
      const patched = await api.patchMessage(t.id, {
        hidden_from_context: nextHidden
      });
      conversation.applyMessagePatch(t.sessionId, patched);
    }
  },
  {
    id: 'message.move_to_session',
    label: 'Move to session…',
    section: 'organize',
    mnemonic: 'm',
    handler: ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      reorgStore.request({ kind: 'move', messageId: t.id, sessionId: t.sessionId });
    }
  },
  {
    id: 'message.split_here',
    label: 'Split here…',
    section: 'organize',
    mnemonic: 's',
    handler: ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      reorgStore.request({ kind: 'split', messageId: t.id, sessionId: t.sessionId });
    }
  },
  {
    id: 'message.fork.from_here',
    label: 'Fork from this message',
    section: 'create',
    advanced: true,
    handler: async ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      // Auto-checkpoint + fork at the target message. Mirrors the
      // `session.fork.from_last_message` flow but anchors at the row
      // the user right-clicked rather than the session's tail.
      const cp = await checkpoints.create(t.sessionId, t.id, null);
      if (!cp) return;
      const forked = await checkpoints.fork(t.sessionId, cp.id);
      if (forked) sessions.select(forked.id);
    }
  },
  {
    id: 'message.regenerate',
    label: 'Regenerate from this message…',
    section: 'create',
    handler: async ({ target }) => {
      const t = asMessage(target);
      if (!t) return;
      try {
        const result = await api.regenerateFromMessage(t.sessionId, t.id);
        sessions.select(result.session.id);
        // Seed the composer with the user prompt so the next turn
        // re-runs the same ask against a fresh sdk_session_id. The
        // composer-bridge custom event is what Conversation.svelte
        // listens for; the seed lands in the textarea on the next
        // mount tick.
        if (typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('bearings:composer-prefill', {
              detail: { sessionId: result.session.id, text: result.prompt }
            })
          );
        }
      } catch (err) {
        notYetImplemented(
          'message.regenerate',
          err instanceof Error ? err.message : String(err)
        );
      }
    },
    disabled: (target) => {
      const t = asMessage(target);
      if (!t) return null;
      // The fork is anchored on a user-turn boundary at-or-before the
      // target; an assistant-only conversation has no boundary to
      // pick. The server returns 400 on the same condition, so the
      // disabled tooltip just preempts the failed round-trip.
      const live = conversation.messages.find((m) => m.id === t.id);
      if (!live) return null;
      const userExists = conversation.messages.some(
        (m) => m.role === 'user' && m.created_at <= live.created_at
      );
      return userExists ? null : 'No user turn at or before this message';
    }
  },
  {
    id: 'message.regenerate.in_place',
    label: 'Regenerate (rewrite in place)',
    section: 'create',
    advanced: true,
    handler: () =>
      notYetImplemented(
        'message.regenerate.in_place',
        'Rewrite-in-place coming in a later version. Use Regenerate (fork) for now.'
      ),
    disabled: () =>
      'Rewrite-in-place lands in v0.10.x+. Use Regenerate (fork) for now.'
  },
  {
    id: 'message.delete',
    label: 'Delete message',
    section: 'destructive',
    destructive: true,
    advanced: true,
    handler: () => notYetImplemented('message.delete'),
    disabled: () => 'Single-message delete lands in v0.9.2'
  }
];
