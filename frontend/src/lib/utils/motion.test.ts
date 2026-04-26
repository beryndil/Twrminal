import { afterEach, describe, expect, it, vi } from 'vitest';

import { prefersReducedMotion, scrollBehavior } from './motion';

type MatchMediaShim = (query: string) => Pick<MediaQueryList, 'matches'> & {
  media: string;
  onchange: null;
  addListener: () => void;
  removeListener: () => void;
  addEventListener: () => void;
  removeEventListener: () => void;
  dispatchEvent: () => boolean;
};

function installMatchMedia(matches: boolean): MatchMediaShim {
  const shim: MatchMediaShim = (query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false
  });
  vi.stubGlobal('window', { matchMedia: shim });
  return shim;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('prefersReducedMotion', () => {
  it('returns true when matchMedia reports the reduce preference', () => {
    installMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
  });

  it('returns false when matchMedia reports no reduce preference', () => {
    installMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
  });

  it('returns false when matchMedia is unavailable (SSR-style env)', () => {
    // No window.matchMedia stubbed → fall through to the safe default.
    vi.stubGlobal('window', {});
    expect(prefersReducedMotion()).toBe(false);
  });
});

describe('scrollBehavior', () => {
  it('returns "auto" when reduced motion is preferred', () => {
    installMatchMedia(true);
    expect(scrollBehavior()).toBe('auto');
  });

  it('returns "smooth" when reduced motion is not preferred', () => {
    installMatchMedia(false);
    expect(scrollBehavior()).toBe('smooth');
  });
});
