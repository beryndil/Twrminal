/**
 * Frozen ID snapshot per plan §7.4.
 *
 * Message IDs are the public API for `~/.config/bearings/menus.toml`
 * overrides. Growing the catalog is a one-line snapshot update; renames
 * need a deprecation alias (see `Action.aliases`).
 *
 * The disabled-with-tooltip items here are the ones the plan §2.3
 * hybrid-stub rule defers to later phases — pin / hide move in Phase 8
 * (migration 0023), fork-from-here waits for checkpoints in v0.9.2,
 * delete waits for `DELETE /messages/{id}`.
 */

import { describe, expect, it } from 'vitest';

import { MESSAGE_ACTIONS } from './message';
import type { ContextTarget } from '../types';

const MESSAGE: ContextTarget = {
  type: 'message',
  id: 'm-1',
  sessionId: 's-1',
  role: 'user'
};

describe('message.ts — action-ID stability', () => {
  it('exposes the frozen v0.9.1 catalog', () => {
    const ids = MESSAGE_ACTIONS.map((a) => a.id).sort();
    expect(ids).toEqual([
      'message.copy_as_markdown',
      'message.copy_content',
      'message.copy_id',
      'message.delete',
      'message.fork.from_here',
      'message.hide_from_context',
      'message.jump_to_turn',
      'message.move_to_session',
      'message.pin',
      'message.split_here'
    ]);
  });

  it('every ID follows `message.<verb>[.<qualifier>]` naming', () => {
    for (const a of MESSAGE_ACTIONS) {
      expect(a.id.startsWith('message.')).toBe(true);
      expect(a.id).toMatch(/^message\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/);
    }
  });

  it('disabled-with-tooltip items name their target milestone', () => {
    // plan §2.3: items without a backing primitive render disabled
    // with a tooltip pointing at the phase where they un-stub.
    // Phase 7 (v0.9.2) un-stubbed `message.fork.from_here` — removed
    // from this set. Phase 8 (v0.9.2) un-stubbed `message.pin` and
    // `message.hide_from_context` via migration 0023. Delete still
    // waits on the single-message DELETE primitive.
    const expectedDisabled = ['message.delete'];
    for (const id of expectedDisabled) {
      const action = MESSAGE_ACTIONS.find((a) => a.id === id);
      expect(action?.disabled?.(MESSAGE)).toBeTruthy();
    }
  });

  it('message.fork.from_here is no longer a stub', () => {
    const fork = MESSAGE_ACTIONS.find((a) => a.id === 'message.fork.from_here');
    expect(fork).toBeDefined();
    expect(fork?.disabled).toBeUndefined();
    expect(typeof fork?.handler).toBe('function');
  });

  it('message.pin and message.hide_from_context are no longer stubs', () => {
    const pin = MESSAGE_ACTIONS.find((a) => a.id === 'message.pin');
    const hide = MESSAGE_ACTIONS.find((a) => a.id === 'message.hide_from_context');
    expect(pin).toBeDefined();
    expect(pin?.disabled).toBeUndefined();
    expect(typeof pin?.handler).toBe('function');
    expect(hide).toBeDefined();
    expect(hide?.disabled).toBeUndefined();
    expect(typeof hide?.handler).toBe('function');
  });

  it('message.delete is destructive and advanced', () => {
    const del = MESSAGE_ACTIONS.find((a) => a.id === 'message.delete');
    expect(del?.destructive).toBe(true);
    expect(del?.section).toBe('destructive');
    // Hidden behind Shift-right-click until the primitive exists — a
    // visible-but-disabled delete is too easy to mis-click past.
    expect(del?.advanced).toBe(true);
  });

  it('move + split fire without a delete primitive (reorg store bridge)', () => {
    const move = MESSAGE_ACTIONS.find((a) => a.id === 'message.move_to_session');
    const split = MESSAGE_ACTIONS.find((a) => a.id === 'message.split_here');
    // These are live: no `disabled` predicate, real handler.
    expect(move?.disabled).toBeUndefined();
    expect(split?.disabled).toBeUndefined();
    expect(typeof move?.handler).toBe('function');
    expect(typeof split?.handler).toBe('function');
  });
});
