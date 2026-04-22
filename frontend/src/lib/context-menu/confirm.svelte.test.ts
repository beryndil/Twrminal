import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { confirmStore, suppressionKey } from './confirm.svelte';

describe('suppressionKey', () => {
  it('formats as <actionId>:<targetType>', () => {
    expect(suppressionKey('session.delete', 'session')).toBe(
      'session.delete:session'
    );
  });

  it('treats same-id-different-target as distinct keys', () => {
    expect(suppressionKey('delete', 'session')).not.toBe(
      suppressionKey('delete', 'message')
    );
  });
});

describe('confirmStore', () => {
  beforeEach(() => {
    confirmStore._resetForTests();
  });

  afterEach(() => {
    confirmStore._resetForTests();
  });

  it('opens a dialog when no suppression exists', async () => {
    const handler = vi.fn();
    await confirmStore.request({
      actionId: 'session.delete',
      targetType: 'session',
      message: 'Delete?',
      destructive: true,
      onConfirm: handler
    });
    expect(confirmStore.pending).not.toBeNull();
    expect(handler).not.toHaveBeenCalled();
  });

  it('fires immediately when the key is already suppressed', async () => {
    const handler = vi.fn();
    // Prime suppression via a first accept with remember=true.
    await confirmStore.request({
      actionId: 'session.delete',
      targetType: 'session',
      message: 'Delete?',
      onConfirm: () => {}
    });
    await confirmStore.accept(true);
    expect(confirmStore.pending).toBeNull();

    // Second request — should bypass the dialog and run inline.
    await confirmStore.request({
      actionId: 'session.delete',
      targetType: 'session',
      message: 'Delete again?',
      onConfirm: handler
    });
    expect(confirmStore.pending).toBeNull();
    expect(handler).toHaveBeenCalledOnce();
  });

  it('suppression keys are independent across target types', async () => {
    // Suppress session.delete on session target.
    await confirmStore.request({
      actionId: 'delete',
      targetType: 'session',
      message: 'Delete session?',
      onConfirm: () => {}
    });
    await confirmStore.accept(true);

    // Same action id on a different target type must still prompt.
    const handler = vi.fn();
    await confirmStore.request({
      actionId: 'delete',
      targetType: 'message',
      message: 'Delete message?',
      onConfirm: handler
    });
    expect(confirmStore.pending).not.toBeNull();
    expect(handler).not.toHaveBeenCalled();
  });

  it('accept runs the handler and clears pending', async () => {
    const handler = vi.fn();
    await confirmStore.request({
      actionId: 'session.archive',
      targetType: 'session',
      message: 'Archive?',
      onConfirm: handler
    });
    await confirmStore.accept(false);
    expect(handler).toHaveBeenCalledOnce();
    expect(confirmStore.pending).toBeNull();
  });

  it('accept with remember=false does not suppress next call', async () => {
    const first = vi.fn();
    await confirmStore.request({
      actionId: 'a',
      targetType: 't',
      message: 'one?',
      onConfirm: first
    });
    await confirmStore.accept(false);
    expect(first).toHaveBeenCalledOnce();

    // Second call should still open the dialog.
    const second = vi.fn();
    await confirmStore.request({
      actionId: 'a',
      targetType: 't',
      message: 'two?',
      onConfirm: second
    });
    expect(confirmStore.pending).not.toBeNull();
    expect(second).not.toHaveBeenCalled();
  });

  it('dismiss clears pending without running handler', async () => {
    const handler = vi.fn();
    await confirmStore.request({
      actionId: 'x',
      targetType: 't',
      message: 'nope?',
      onConfirm: handler
    });
    confirmStore.dismiss();
    expect(confirmStore.pending).toBeNull();
    expect(handler).not.toHaveBeenCalled();
  });

  it('swallows handler errors so the dialog still closes', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    await confirmStore.request({
      actionId: 'boom',
      targetType: 't',
      message: '?',
      onConfirm: () => {
        throw new Error('blown');
      }
    });
    await confirmStore.accept(false);
    expect(confirmStore.pending).toBeNull();
    expect(errorSpy).toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it('busy is true during async handler execution', async () => {
    let resolve: (() => void) | undefined;
    const slow = new Promise<void>((r) => {
      resolve = r;
    });
    await confirmStore.request({
      actionId: 'slow',
      targetType: 't',
      message: '?',
      onConfirm: () => slow
    });
    const pending = confirmStore.accept(false);
    expect(confirmStore.busy).toBe(true);
    resolve?.();
    await pending;
    expect(confirmStore.busy).toBe(false);
  });

  it('double-accept is a no-op while busy', async () => {
    const handler = vi.fn(() => Promise.resolve());
    await confirmStore.request({
      actionId: 'race',
      targetType: 't',
      message: '?',
      onConfirm: handler
    });
    const a = confirmStore.accept(false);
    const b = confirmStore.accept(false); // should be ignored
    await Promise.all([a, b]);
    expect(handler).toHaveBeenCalledOnce();
  });
});
