import { cleanup, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { tick } from 'svelte';

import VirtualItem from './VirtualItem.svelte';
import VirtualItemHarness from './VirtualItemHarness.svelte';

afterEach(cleanup);

// Capture the IntersectionObserver instances the component creates
// so each test can drive `isIntersecting` synchronously. The real
// browser fires async; here we let tests pull the lever directly.
type Recorded = {
  callback: IntersectionObserverCallback;
  options: IntersectionObserverInit | undefined;
  targets: Element[];
  disconnected: boolean;
};

let observers: Recorded[] = [];
let resizeObservers: { callback: ResizeObserverCallback; targets: Element[] }[] = [];

beforeEach(() => {
  observers = [];
  resizeObservers = [];

  globalThis.IntersectionObserver = class {
    callback: IntersectionObserverCallback;
    options: IntersectionObserverInit | undefined;
    targets: Element[] = [];
    rec: Recorded;
    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
      this.callback = callback;
      this.options = options;
      this.rec = { callback, options, targets: this.targets, disconnected: false };
      observers.push(this.rec);
    }
    observe(target: Element) {
      this.targets.push(target);
    }
    unobserve() {}
    disconnect() {
      this.rec.disconnected = true;
    }
    takeRecords() {
      return [];
    }
    root = null;
    rootMargin = '';
    thresholds = [];
  } as unknown as typeof IntersectionObserver;

  globalThis.ResizeObserver = class {
    callback: ResizeObserverCallback;
    targets: Element[] = [];
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
      resizeObservers.push({ callback, targets: this.targets });
    }
    observe(target: Element) {
      this.targets.push(target);
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function fireIntersection(rec: Recorded, target: Element, isIntersecting: boolean) {
  rec.callback(
    [
      {
        target,
        isIntersecting,
        intersectionRatio: isIntersecting ? 1 : 0,
        boundingClientRect: {} as DOMRectReadOnly,
        intersectionRect: {} as DOMRectReadOnly,
        rootBounds: null,
        time: 0
      }
    ],
    rec as unknown as IntersectionObserver
  );
}

describe('VirtualItem', () => {
  it('starts unmounted (placeholder) and renders content when IO marks visible', async () => {
    const { findByTestId } = render(VirtualItemHarness, { label: 'cell-A' });
    const wrapper = await findByTestId('virtual-item');
    expect(wrapper.getAttribute('data-visible')).toBe('false');
    expect(wrapper.querySelector('[data-testid="cell-content"]')).toBeNull();
    expect(observers.length).toBe(1);

    fireIntersection(observers[0], wrapper, true);
    await tick();

    expect(wrapper.getAttribute('data-visible')).toBe('true');
    const content = wrapper.querySelector('[data-testid="cell-content"]');
    expect(content?.textContent).toBe('cell-A');
  });

  it('renders content immediately when forceVisible is set', async () => {
    const { findByTestId } = render(VirtualItemHarness, {
      label: 'forced',
      forceVisible: true
    });
    const wrapper = await findByTestId('virtual-item');
    expect(wrapper.getAttribute('data-visible')).toBe('true');
    expect(wrapper.querySelector('[data-testid="cell-content"]')?.textContent).toBe('forced');
    // forceVisible bypasses IO entirely — no observer should be set up.
    expect(observers.length).toBe(0);
  });

  it('returns to placeholder with measured min-height when item leaves viewport', async () => {
    const { findByTestId } = render(VirtualItemHarness, { label: 'cell-B' });
    const wrapper = (await findByTestId('virtual-item')) as HTMLDivElement;

    // Mount it, measure a height, then push it back offscreen.
    fireIntersection(observers[0], wrapper, true);
    await tick();
    expect(wrapper.getAttribute('data-visible')).toBe('true');

    // jsdom's offsetHeight is always 0, so simulate a measurement by
    // firing the ResizeObserver callback after stubbing offsetHeight.
    Object.defineProperty(wrapper, 'offsetHeight', { value: 742, configurable: true });
    expect(resizeObservers.length).toBe(1);
    resizeObservers[0].callback(
      [] as unknown as ResizeObserverEntry[],
      {} as ResizeObserver
    );
    await tick();

    fireIntersection(observers[0], wrapper, false);
    await tick();
    expect(wrapper.getAttribute('data-visible')).toBe('false');
    expect(wrapper.style.minHeight).toBe('742px');
  });

  it('applies fallbackHeightPx as min-height before any measurement', async () => {
    const { findByTestId } = render(VirtualItemHarness, {
      label: 'cell-C',
      fallbackHeightPx: 250
    });
    const wrapper = (await findByTestId('virtual-item')) as HTMLDivElement;
    expect(wrapper.getAttribute('data-visible')).toBe('false');
    expect(wrapper.style.minHeight).toBe('250px');
  });

  it('uses provided rootMargin and scrollRoot on the IntersectionObserver', async () => {
    const root = document.createElement('div');
    document.body.appendChild(root);
    render(VirtualItemHarness, {
      label: 'cell-D',
      scrollRoot: root,
      rootMarginPx: 800
    });
    expect(observers.length).toBe(1);
    expect(observers[0].options?.root).toBe(root);
    expect(observers[0].options?.rootMargin).toBe('800px 0px 800px 0px');
    document.body.removeChild(root);
  });

  it('disconnects the observer on unmount', async () => {
    const { unmount } = render(VirtualItemHarness, { label: 'cell-E' });
    expect(observers.length).toBe(1);
    expect(observers[0].disconnected).toBe(false);
    unmount();
    expect(observers[0].disconnected).toBe(true);
  });

  it('falls back to mounted content when IntersectionObserver is unavailable', async () => {
    // Some headless test envs lack IO — the wrapper must fail open
    // (render content) rather than hide it. Lock that contract here.
    delete (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
    const { findByTestId } = render(VirtualItemHarness, { label: 'cell-F' });
    const wrapper = await findByTestId('virtual-item');
    expect(wrapper.getAttribute('data-visible')).toBe('true');
    expect(wrapper.querySelector('[data-testid="cell-content"]')?.textContent).toBe('cell-F');
  });
});

// Re-export so the harness module sees the symbol; suppresses
// "unused import" warnings since the harness uses VirtualItem
// directly.
export { VirtualItem };
