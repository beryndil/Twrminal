/**
 * Tests for the seamless-reload watcher. We exercise the public state
 * transitions (`pollOnce`, `attemptReload`) directly so we don't have
 * to wait out the 60-s poll interval; production paths fire from the
 * timer + visibility handler set up in `init()`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { VersionWatcher } from './version_watcher.svelte';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function stubVersionFetch(build: string | null): () => void {
  const calls: number[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      calls.push(Date.now());
      return {
        ok: true,
        async json() {
          return { version: '0.10.0', build };
        }
      } as unknown as Response;
    })
  );
  return () => calls.length as unknown as () => void;
}

describe('VersionWatcher.wantsReload', () => {
  it('returns false until both pin and server build are known', () => {
    const w = new VersionWatcher();
    expect(w.wantsReload).toBe(false);
    w.myBuild = 'abc';
    expect(w.wantsReload).toBe(false);
    w.serverBuild = 'abc';
    expect(w.wantsReload).toBe(false);
  });

  it('returns true when myBuild and serverBuild diverge', () => {
    const w = new VersionWatcher();
    w.myBuild = 'old';
    w.serverBuild = 'new';
    expect(w.wantsReload).toBe(true);
  });

  it('returns false when either side is null (dev mode)', () => {
    const w = new VersionWatcher();
    w.myBuild = null;
    w.serverBuild = 'something';
    expect(w.wantsReload).toBe(false);

    w.myBuild = 'something';
    w.serverBuild = null;
    expect(w.wantsReload).toBe(false);
  });
});

describe('VersionWatcher.pollOnce', () => {
  it('updates serverBuild on a successful fetch', async () => {
    stubVersionFetch('newbuild');
    const w = new VersionWatcher();
    w.myBuild = 'oldbuild';
    w.serverBuild = 'oldbuild';
    await w.pollOnce();
    expect(w.serverBuild).toBe('newbuild');
    expect(w.wantsReload).toBe(true);
  });

  it('preserves the last known serverBuild when the fetch throws', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('transport blip');
      })
    );
    const w = new VersionWatcher();
    w.myBuild = 'oldbuild';
    w.serverBuild = 'oldbuild';
    await w.pollOnce();
    expect(w.serverBuild).toBe('oldbuild');
    expect(w.wantsReload).toBe(false);
  });
});

describe('VersionWatcher.attemptReload disruption guards', () => {
  it('triggers reload when armed and no guard blocks', () => {
    const w = new VersionWatcher();
    w.myBuild = 'old';
    w.serverBuild = 'new';
    const reload = vi.fn();
    expect(w.attemptReload(reload)).toBe(true);
    expect(reload).toHaveBeenCalledOnce();
  });

  it('does nothing when not armed', () => {
    const w = new VersionWatcher();
    w.myBuild = 'same';
    w.serverBuild = 'same';
    const reload = vi.fn();
    expect(w.attemptReload(reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it('blocks while the agent is streaming', () => {
    const w = new VersionWatcher();
    w.configure({ isAgentStreaming: () => true });
    w.myBuild = 'old';
    w.serverBuild = 'new';
    const reload = vi.fn();
    expect(w.attemptReload(reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it('blocks while a modal is open', () => {
    const w = new VersionWatcher();
    w.configure({ isModalOpen: () => true });
    w.myBuild = 'old';
    w.serverBuild = 'new';
    const reload = vi.fn();
    expect(w.attemptReload(reload)).toBe(false);
  });

  it('blocks while the composer holds a draft', () => {
    const w = new VersionWatcher();
    w.configure({ hasComposerDraft: () => true });
    w.myBuild = 'old';
    w.serverBuild = 'new';
    const reload = vi.fn();
    expect(w.attemptReload(reload)).toBe(false);
  });
});
