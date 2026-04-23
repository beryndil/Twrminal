/**
 * Session-target actions — Phase 4a.2 of the context-menu plan.
 *
 * Every action in this file either:
 *   - hits a real endpoint shipped in Phase 4a.1 (PATCH pinned / model,
 *     /api/shell/open, existing close/reopen/delete) and is bound live;
 *   - renders disabled-with-tooltip per plan §2.3 when the backend
 *     primitive isn't ready yet (checkpoints / share-link / duplicate —
 *     future phases).
 *
 * Gating is driven by reaching back into `sessions.list` for the latest
 * row inside `disabled(target)` / `requires(target)` rather than
 * snapshotting closed/pinned state into `SessionTarget`. Keeps the
 * target payload minimal and prevents a stale predicate from showing
 * "Archive" on a session that was just closed via another tab.
 *
 * Handlers stay thin — per `Conversation.svelte` being at its 400-line
 * cap, all mutation logic lives here, never in the binding site.
 */

import * as api from '$lib/api';
import { agent } from '$lib/agent.svelte';
import { KNOWN_MODELS } from '$lib/models';
import { checkpoints } from '$lib/stores/checkpoints.svelte';
import { conversation } from '$lib/stores/conversation.svelte';
import { sessions } from '$lib/stores/sessions.svelte';
import { templates } from '$lib/stores/templates.svelte';
import { writeClipboard } from '../clipboard';
import { confirmStore } from '../confirm.svelte';
import { notYetImplemented, stubStore } from '../stub.svelte';
import { undoStore } from '../undo.svelte';
import type { Action, ContextTarget, SessionTarget } from '../types';

/** Narrow a `ContextTarget` to `SessionTarget`. Centralises the
 * discriminator check so each handler stays focused. */
function asSession(t: ContextTarget): SessionTarget | null {
  return t.type === 'session' ? t : null;
}

/** Latest session row by id. `null` when the sidebar hasn't loaded or
 * the session was deleted in another tab between menu-open and handler
 * fire. Callers treat `null` as a silent no-op — the sidebar will
 * remove the ghost row on the next softRefresh tick. */
function lookup(id: string): api.Session | null {
  return sessions.list.find((s) => s.id === id) ?? null;
}

/** Post to `/api/shell/open` for the given kind. Translates backend
 * 400 ("shell.<kind>_command not configured") into a stub toast
 * naming the exact config key so Dave can drop it into his TOML. */
async function dispatchOpenIn(
  kind: api.ShellKind,
  actionId: string,
  path: string
): Promise<void> {
  try {
    await api.openShell(kind, path);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    stubStore.show({
      actionId,
      reason: msg.includes('shell.')
        ? `Configure ${msg} in config.toml`
        : `Shell dispatch failed: ${msg}`
    });
  }
}

/** Build one `session.open_in.<kind>` entry with a live handler. */
function openInItem(
  kind: api.ShellKind,
  label: string,
  mnemonic: string
): Action {
  const id = `session.open_in.${kind}`;
  return {
    id,
    label,
    section: 'navigate',
    mnemonic,
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      const row = lookup(t.id);
      if (!row) return;
      await dispatchOpenIn(kind, id, row.working_dir);
    }
  };
}

/** Build one `session.change_model.<model>` leaf. Gated off when the
 * session already uses that model — no point in a no-op PATCH. */
function changeModelItem(model: string): Action {
  const id = `session.change_model.${model}`;
  return {
    id,
    label: model,
    section: 'edit',
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      const row = lookup(t.id);
      if (!row || row.model === model) return;
      await sessions.update(t.id, { model });
      // Runner drop is server-side (plan §2.1 via _RUNNER_RESPAWN_FIELDS
      // in routes_sessions). If the UI happens to be connected to this
      // session, the next turn naturally reconnects.
      if (agent.sessionId === t.id) agent.close();
    },
    disabled: (target) => {
      const t = asSession(target);
      if (!t) return null;
      const row = lookup(t.id);
      if (row && row.model === model) return `Already on ${model}`;
      return null;
    }
  };
}

export const SESSION_ACTIONS: readonly Action[] = [
  openInItem('editor', 'Open in editor', 'e'),
  openInItem('terminal', 'Open terminal here', 't'),
  openInItem('file_explorer', 'Open in file explorer', 'f'),
  openInItem('git_gui', 'Open in git GUI', 'g'),
  openInItem('claude_cli', 'Open Claude CLI', 'c'),
  {
    id: 'session.pin',
    label: 'Pin session',
    section: 'organize',
    mnemonic: 'p',
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      const row = lookup(t.id);
      if (!row) return;
      await sessions.update(t.id, { pinned: !row.pinned });
    },
    // Relabel at render time via a second entry would double the ID
    // list — instead, the label is static ("Pin session") and the
    // disabled-predicate hides it when already pinned, leaving
    // `session.unpin` to take over. See the sibling action below.
    requires: (target) => {
      const t = asSession(target);
      if (!t) return false;
      const row = lookup(t.id);
      return row ? !row.pinned : false;
    }
  },
  {
    id: 'session.unpin',
    label: 'Unpin session',
    section: 'organize',
    mnemonic: 'p',
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      await sessions.update(t.id, { pinned: false });
    },
    requires: (target) => {
      const t = asSession(target);
      if (!t) return false;
      const row = lookup(t.id);
      return row ? row.pinned : false;
    }
  },
  {
    id: 'session.archive',
    label: 'Archive session',
    section: 'organize',
    mnemonic: 'a',
    aliases: ['session.close'],
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      await sessions.close(t.id);
      undoStore.push({
        message: 'Session archived',
        inverse: async () => {
          await sessions.reopen(t.id);
        }
      });
    },
    requires: (target) => {
      const t = asSession(target);
      if (!t) return false;
      const row = lookup(t.id);
      return row ? !row.closed_at : false;
    }
  },
  {
    id: 'session.reopen',
    label: 'Reopen session',
    section: 'organize',
    mnemonic: 'r',
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      await sessions.reopen(t.id);
    },
    requires: (target) => {
      const t = asSession(target);
      if (!t) return false;
      const row = lookup(t.id);
      return row ? !!row.closed_at : false;
    }
  },
  {
    id: 'session.change_model',
    label: 'Change model for continuation ▸',
    section: 'edit',
    mnemonic: 'm',
    // The leaf is a no-op — clicking the parent just opens the
    // submenu. Phase 2's keyboard FSM drives expansion from here.
    handler: () => {},
    submenu: KNOWN_MODELS.map((m) => changeModelItem(m))
  },
  {
    id: 'session.duplicate',
    label: 'Duplicate',
    section: 'create',
    handler: () => notYetImplemented('session.duplicate'),
    disabled: () => 'Duplicate lands in Phase 4a.3'
  },
  {
    id: 'session.save_as_template',
    label: 'Save as template…',
    section: 'create',
    mnemonic: 's',
    // v0.9.2 MVP: window.prompt for the name. A richer modal (with a
    // working_dir/model preview and a first-prompt textarea) can replace
    // this when the template editor lands — the action ID stays stable
    // because `menus.toml` users key off it.
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      const row = lookup(t.id);
      if (!row) return;
      const suggested = row.title ?? row.model;
      const entered =
        typeof window !== 'undefined' && typeof window.prompt === 'function'
          ? window.prompt('Template name:', suggested)
          : null;
      if (entered === null) return; // user cancelled
      const name = entered.trim();
      if (!name) {
        stubStore.show({
          actionId: 'session.save_as_template',
          reason: 'Template name cannot be empty'
        });
        return;
      }
      const created = await templates.create({
        name,
        working_dir: row.working_dir,
        model: row.model,
        tag_ids: [...(row.tag_ids ?? [])]
      });
      if (!created) {
        stubStore.show({
          actionId: 'session.save_as_template',
          reason: templates.error ?? 'Failed to save template'
        });
      }
    }
  },
  {
    id: 'session.fork.from_last_message',
    label: 'Fork from last message',
    section: 'create',
    advanced: true,
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      // The conversation store owns the message list for the currently-
      // selected session. If the user right-clicks a sidebar row that
      // isn't selected, `conversation.messages` belongs to a different
      // session — bail rather than forking off an unrelated anchor.
      if (conversation.sessionId !== t.id) {
        stubStore.show({
          actionId: 'session.fork.from_last_message',
          reason: 'Open the session first so its last message is known'
        });
        return;
      }
      const msgs = conversation.messages;
      const last = msgs.length > 0 ? msgs[msgs.length - 1] : null;
      if (!last) {
        stubStore.show({
          actionId: 'session.fork.from_last_message',
          reason: 'Session has no messages yet'
        });
        return;
      }
      // Auto-create an anchor checkpoint (null label — the UI renders
      // these as unlabelled chips), then fork it. The checkpoint
      // survives on the source session as a durable mark of the fork
      // point; users can relabel via the gutter right-click.
      const cp = await checkpoints.create(t.id, last.id, null);
      if (!cp) return;
      const forked = await checkpoints.fork(t.id, cp.id);
      if (forked) sessions.select(forked.id);
    },
    requires: (target) => {
      const t = asSession(target);
      if (!t) return false;
      const row = lookup(t.id);
      return !!row;
    }
  },
  {
    id: 'session.copy_id',
    label: 'Copy session ID',
    section: 'copy',
    advanced: true,
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      await writeClipboard(t.id);
    }
  },
  {
    id: 'session.copy_title',
    label: 'Copy session title',
    section: 'copy',
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      const row = lookup(t.id);
      if (!row) return;
      await writeClipboard(row.title ?? row.model);
    }
  },
  {
    id: 'session.copy_share_link',
    label: 'Copy share link',
    section: 'copy',
    advanced: true,
    handler: () => notYetImplemented('session.copy_share_link'),
    disabled: () => 'Share links land in v0.10.x'
  },
  {
    id: 'session.delete',
    label: 'Delete session',
    section: 'destructive',
    destructive: true,
    mnemonic: 'd',
    handler: async ({ target }) => {
      const t = asSession(target);
      if (!t) return;
      const row = lookup(t.id);
      const title = row?.title ?? row?.model ?? 'this session';
      await confirmStore.request({
        actionId: 'session.delete',
        targetType: 'session',
        message: `Delete "${title}"? This removes every message, tool call, and cost row. Cannot be undone.`,
        confirmLabel: 'Delete',
        destructive: true,
        onConfirm: async () => {
          if (agent.sessionId === t.id) agent.close();
          await sessions.remove(t.id);
        }
      });
    }
  }
];
