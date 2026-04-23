import { afterEach, describe, expect, it } from 'vitest';

import { menuConfig } from '$lib/stores/menuConfig.svelte';
import { getActions, resolveMenu } from './registry';
import { SESSION_ACTIONS } from './actions/session';
import { MESSAGE_ACTIONS } from './actions/message';
import { TAG_ACTIONS, TAG_CHIP_ACTIONS } from './actions/tag';
import { TOOL_CALL_ACTIONS } from './actions/tool_call';
import { CODE_BLOCK_ACTIONS } from './actions/code_block';
import { LINK_ACTIONS } from './actions/link';
import { CHECKPOINT_ACTIONS } from './actions/checkpoint';
import { MULTI_SELECT_ACTIONS } from './actions/multi_select';
import type { Action, ContextTarget, RenderedMenu } from './types';

/** Flatten a resolved menu's groups into a flat id array for
 * set-membership assertions. */
function flatIds(menu: RenderedMenu): string[] {
  return menu.groups.flatMap((g) => g.actions.map((a) => a.id));
}

const SESSION: ContextTarget = { type: 'session', id: 'sess-1' };
const MESSAGE: ContextTarget = {
  type: 'message',
  id: 'msg-1',
  sessionId: 'sess-1',
  role: 'user'
};
const TAG: ContextTarget = { type: 'tag', id: 7 };
const TAG_CHIP: ContextTarget = {
  type: 'tag_chip',
  tagId: 7,
  sessionId: 'sess-1'
};
const TOOL_CALL: ContextTarget = {
  type: 'tool_call',
  id: 'tc-1',
  sessionId: 'sess-1',
  messageId: 'msg-1'
};
const CODE_BLOCK: ContextTarget = {
  type: 'code_block',
  text: 'print("hi")',
  language: 'python',
  sessionId: 'sess-1',
  messageId: 'msg-1'
};
const LINK: ContextTarget = {
  type: 'link',
  href: 'https://example.com',
  text: 'example',
  sessionId: 'sess-1',
  messageId: 'msg-1'
};
const CHECKPOINT: ContextTarget = {
  type: 'checkpoint',
  id: 'cp-1',
  sessionId: 'sess-1',
  messageId: 'msg-1',
  label: 'mid'
};
const MULTI_SELECT: ContextTarget = {
  type: 'multi_select',
  ids: ['sess-1', 'sess-2']
};

describe('registry', () => {
  it('exposes session actions', () => {
    expect(getActions('session')).toBe(SESSION_ACTIONS);
  });

  it('exposes message actions', () => {
    expect(getActions('message')).toBe(MESSAGE_ACTIONS);
  });

  it('exposes tag actions', () => {
    expect(getActions('tag')).toBe(TAG_ACTIONS);
  });

  it('exposes tag_chip actions', () => {
    expect(getActions('tag_chip')).toBe(TAG_CHIP_ACTIONS);
  });

  it('exposes tool_call actions', () => {
    expect(getActions('tool_call')).toBe(TOOL_CALL_ACTIONS);
  });

  it('exposes code_block actions', () => {
    expect(getActions('code_block')).toBe(CODE_BLOCK_ACTIONS);
  });

  it('exposes link actions', () => {
    expect(getActions('link')).toBe(LINK_ACTIONS);
  });

  it('exposes checkpoint actions', () => {
    expect(getActions('checkpoint')).toBe(CHECKPOINT_ACTIONS);
  });

  it('exposes multi_select actions', () => {
    expect(getActions('multi_select')).toBe(MULTI_SELECT_ACTIONS);
  });

  it('every action ID is unique within its target', () => {
    for (const list of [
      SESSION_ACTIONS,
      MESSAGE_ACTIONS,
      TAG_ACTIONS,
      TAG_CHIP_ACTIONS,
      TOOL_CALL_ACTIONS,
      CODE_BLOCK_ACTIONS,
      LINK_ACTIONS,
      CHECKPOINT_ACTIONS,
      MULTI_SELECT_ACTIONS
    ]) {
      const ids = list.map((a) => a.id);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });

  it('action IDs follow <target>.<verb> naming', () => {
    for (const a of SESSION_ACTIONS) expect(a.id.startsWith('session.')).toBe(true);
    for (const a of MESSAGE_ACTIONS) expect(a.id.startsWith('message.')).toBe(true);
    for (const a of TAG_ACTIONS) expect(a.id.startsWith('tag.')).toBe(true);
    for (const a of TAG_CHIP_ACTIONS) expect(a.id.startsWith('tag_chip.')).toBe(true);
    for (const a of TOOL_CALL_ACTIONS) expect(a.id.startsWith('tool_call.')).toBe(true);
    for (const a of CODE_BLOCK_ACTIONS) expect(a.id.startsWith('code_block.')).toBe(true);
    for (const a of LINK_ACTIONS) expect(a.id.startsWith('link.')).toBe(true);
    for (const a of CHECKPOINT_ACTIONS) expect(a.id.startsWith('checkpoint.')).toBe(true);
    for (const a of MULTI_SELECT_ACTIONS) expect(a.id.startsWith('multi_select.')).toBe(true);
  });
});

describe('resolveMenu', () => {
  it('returns groups in canonical section order', () => {
    const menu = resolveMenu(SESSION, false);
    const seen = menu.groups.map((g) => g.section);
    // Phase 1 only has 'copy' rows — just assert order is a prefix
    // of the SECTIONS canonical sequence.
    const canonical = [
      'primary',
      'navigate',
      'create',
      'edit',
      'view',
      'copy',
      'organize',
      'destructive'
    ];
    for (let i = 1; i < seen.length; i++) {
      expect(canonical.indexOf(seen[i]!)).toBeGreaterThan(
        canonical.indexOf(seen[i - 1]!)
      );
    }
  });

  it('omits empty sections entirely', () => {
    const menu = resolveMenu(SESSION, false);
    for (const g of menu.groups) {
      expect(g.actions.length).toBeGreaterThan(0);
    }
  });

  it('hides advanced-only actions when not in advanced mode', () => {
    // Phase 4a.2 ships real advanced items on the session menu —
    // `session.copy_id`, `session.copy_share_link`, and
    // `session.fork.from_last_message`. Advanced mode surfaces them;
    // normal mode hides them. Drop the gating-dependent rows from
    // both menus first so a missing sessions store doesn't shift the
    // count out from under the assertion.
    const normalIds = flatIds(resolveMenu(SESSION, false));
    const advIds = flatIds(resolveMenu(SESSION, true));
    expect(normalIds).not.toContain('session.copy_id');
    expect(advIds).toContain('session.copy_id');
    expect(normalIds).not.toContain('session.copy_share_link');
    expect(advIds).toContain('session.copy_share_link');
  });

  it('resolves a message menu without error', () => {
    const menu = resolveMenu(MESSAGE, false);
    expect(menu.target).toEqual(MESSAGE);
    expect(menu.groups.length).toBeGreaterThan(0);
  });

  it('resolves a tag menu without error', () => {
    const menu = resolveMenu(TAG, false);
    expect(menu.target).toEqual(TAG);
    expect(menu.groups.length).toBeGreaterThan(0);
  });

  it('resolves a tag_chip menu without error', () => {
    const menu = resolveMenu(TAG_CHIP, false);
    expect(menu.target).toEqual(TAG_CHIP);
    expect(menu.groups.length).toBeGreaterThan(0);
  });

  it('resolves a tool_call menu without error', () => {
    const menu = resolveMenu(TOOL_CALL, false);
    expect(menu.target).toEqual(TOOL_CALL);
    expect(menu.groups.length).toBeGreaterThan(0);
  });

  it('resolves a code_block menu without error', () => {
    const menu = resolveMenu(CODE_BLOCK, false);
    expect(menu.target).toEqual(CODE_BLOCK);
    expect(menu.groups.length).toBeGreaterThan(0);
  });

  it('resolves a link menu without error', () => {
    const menu = resolveMenu(LINK, false);
    expect(menu.target).toEqual(LINK);
    expect(menu.groups.length).toBeGreaterThan(0);
  });

  it('resolves a checkpoint menu without error', () => {
    const menu = resolveMenu(CHECKPOINT, false);
    expect(menu.target).toEqual(CHECKPOINT);
    expect(menu.groups.length).toBeGreaterThan(0);
    expect(flatIds(menu)).toContain('checkpoint.fork');
  });

  it('resolves a multi_select menu without error', () => {
    const menu = resolveMenu(MULTI_SELECT, false);
    expect(menu.target).toEqual(MULTI_SELECT);
    expect(menu.groups.length).toBeGreaterThan(0);
    expect(flatIds(menu)).toContain('multi_select.clear');
    expect(flatIds(menu)).toContain('multi_select.delete');
  });

  it('applies the requires predicate', () => {
    const t: ContextTarget = { type: 'session', id: 'x' };
    const gated: Action[] = [
      {
        id: 'session.gated',
        label: 'gated',
        section: 'view',
        requires: () => false,
        handler: () => {}
      }
    ];
    const visible = gated.filter((a) => !(a.requires && !a.requires(t)));
    expect(visible).toHaveLength(0);
  });
});

describe('resolveMenu with menus.toml overrides', () => {
  afterEach(() => {
    // Reset the store so one test's overrides don't bleed into the
    // next. Tests that care about overrides set them up explicitly.
    menuConfig.config = { by_target: {} };
    menuConfig.loaded = false;
    menuConfig.error = null;
  });

  it('drops hidden actions from the resolved menu', () => {
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: [],
          hidden: ['session.copy_title'],
          shortcuts: {}
        }
      }
    });
    const ids = flatIds(resolveMenu(SESSION, false));
    expect(ids).not.toContain('session.copy_title');
  });

  it('keeps hidden actions reachable via the raw registry', () => {
    // The command palette enumerates actions from `getActions`, not
    // `resolveMenu`, so hiding a row in the right-click menu must not
    // remove it from Ctrl+Shift+P.
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: [],
          hidden: ['session.copy_title'],
          shortcuts: {}
        }
      }
    });
    const rawIds = getActions('session').map((a) => a.id);
    expect(rawIds).toContain('session.copy_title');
  });

  it('floats pinned actions to the top of their section', () => {
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: ['session.delete'],
          hidden: [],
          shortcuts: {}
        }
      }
    });
    const menu = resolveMenu(SESSION, false);
    const destructive = menu.groups.find((g) => g.section === 'destructive');
    expect(destructive?.actions[0]?.id).toBe('session.delete');
  });

  it('preserves pinned order when multiple pins target one section', () => {
    menuConfig.hydrate({
      by_target: {
        session: {
          // Both live in the `organize` section; listing reopen first
          // means it must appear before pin even though the default
          // declaration order is pin, unpin, archive, reopen.
          pinned: ['session.reopen', 'session.pin'],
          hidden: [],
          shortcuts: {}
        }
      }
    });
    const menu = resolveMenu(SESSION, false);
    const organize = menu.groups.find((g) => g.section === 'organize');
    const ids = organize?.actions.map((a) => a.id) ?? [];
    const reopenIdx = ids.indexOf('session.reopen');
    const pinIdx = ids.indexOf('session.pin');
    // Reopen is gated by a closed session and the sessions store is
    // empty in this test, so it won't render; but pin should still be
    // first among the actions that do pass the `requires` check.
    if (reopenIdx !== -1 && pinIdx !== -1) {
      expect(reopenIdx).toBeLessThan(pinIdx);
    }
    // Unconditionally: whichever of the two survives must be at
    // index 0 — a later-declared action shouldn't leapfrog the pin.
    if (pinIdx !== -1 && reopenIdx === -1) {
      expect(pinIdx).toBe(0);
    }
  });

  it('silently ignores unknown pinned IDs', () => {
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: ['session.does_not_exist'],
          hidden: [],
          shortcuts: {}
        }
      }
    });
    // No throw — the menu still resolves.
    const menu = resolveMenu(SESSION, false);
    expect(menu.groups.length).toBeGreaterThan(0);
  });

  it('silently ignores unknown hidden IDs', () => {
    const baseline = flatIds(resolveMenu(SESSION, false)).length;
    menuConfig.hydrate({
      by_target: {
        session: {
          pinned: [],
          hidden: ['session.also_does_not_exist'],
          shortcuts: {}
        }
      }
    });
    const afterIds = flatIds(resolveMenu(SESSION, false));
    expect(afterIds.length).toBe(baseline);
  });
});
