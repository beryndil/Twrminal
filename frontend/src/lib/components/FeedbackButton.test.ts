/** Unit specs for FeedbackButton.
 *
 * Contract surface:
 *  - Renders a <button> with an aria-label that announces the
 *    target action (bug vs feature).
 *  - On click, opens a github.com /issues/new URL in a new tab via
 *    `window.open` with `noopener,noreferrer`.
 *  - The opened URL carries a body that embeds env (version + UA).
 *  - When `/api/version` rejects, the button still opens the URL
 *    with version="unknown" — a transient network blip should
 *    never block bug filing.
 *  - Bearings does NOT POST anything itself — verifying the click
 *    path is purely `window.open`, no `fetch` to non-/api/version
 *    endpoints, no analytics ping. (Standards §17 telemetry-free.)
 */
import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import FeedbackButton from './FeedbackButton.svelte';

interface OpenCall {
  url: string;
  target: string;
  features: string;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  // Stub navigator fields so the env block is deterministic
  // regardless of the test runner's UA.
  Object.defineProperty(navigator, 'userAgent', {
    value: 'TestUA/1.0',
    configurable: true
  });
  Object.defineProperty(navigator, 'platform', {
    value: 'TestPlatform',
    configurable: true
  });
  Object.defineProperty(navigator, 'language', {
    value: 'en-US',
    configurable: true
  });
});

function captureWindowOpen(): { calls: OpenCall[] } {
  const calls: OpenCall[] = [];
  vi.spyOn(window, 'open').mockImplementation(
    (url?: string | URL, target?: string, features?: string): null => {
      calls.push({
        url: String(url ?? ''),
        target: target ?? '',
        features: features ?? ''
      });
      return null;
    }
  );
  return { calls };
}

describe('FeedbackButton', () => {
  it('renders a button with a bug-report aria-label by default', () => {
    const { getByTestId } = render(FeedbackButton);
    const btn = getByTestId('feedback-button') as HTMLButtonElement;
    expect(btn.tagName).toBe('BUTTON');
    expect(btn.getAttribute('aria-label')).toMatch(/bug/i);
  });

  it('renders a feature-request aria-label when kind=feature', () => {
    const { getByTestId } = render(FeedbackButton, { props: { kind: 'feature' } });
    const btn = getByTestId('feedback-button') as HTMLButtonElement;
    expect(btn.getAttribute('aria-label')).toMatch(/feature/i);
  });

  it('opens a prefilled github.com URL on click with noopener', async () => {
    const { calls } = captureWindowOpen();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/version') {
          return new Response(
            JSON.stringify({ version: '0.21.0', build: '1714075200000000000' }),
            { status: 200, headers: { 'content-type': 'application/json' } }
          );
        }
        throw new Error(`unexpected fetch: ${url}`);
      })
    );

    const { getByTestId } = render(FeedbackButton);
    await fireEvent.click(getByTestId('feedback-button'));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].target).toBe('_blank');
    expect(calls[0].features).toContain('noopener');
    expect(calls[0].features).toContain('noreferrer');

    const opened = new URL(calls[0].url);
    expect(opened.origin).toBe('https://github.com');
    expect(opened.pathname).toBe('/Beryndil/Bearings/issues/new');
    expect(opened.searchParams.get('template')).toBe('bug.yml');
    const body = opened.searchParams.get('body') ?? '';
    expect(body).toMatch(/Bearings version:\*\* 0\.21\.0/);
    expect(body).toMatch(/Browser:\*\* TestUA\/1\.0/);
  });

  it('opens with version="unknown" when /api/version rejects', async () => {
    const { calls } = captureWindowOpen();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network down');
      })
    );

    const { getByTestId } = render(FeedbackButton);
    await fireEvent.click(getByTestId('feedback-button'));

    await waitFor(() => expect(calls).toHaveLength(1));
    const body = new URL(calls[0].url).searchParams.get('body') ?? '';
    expect(body).toMatch(/Bearings version:\*\* unknown/);
  });

  it('only fetches /api/version — no other requests on click', async () => {
    captureWindowOpen();
    const fetchSpy = vi.fn(async (url: string) => {
      return new Response(JSON.stringify({ version: '0.21.0', build: null }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      });
    });
    vi.stubGlobal('fetch', fetchSpy);

    const { getByTestId } = render(FeedbackButton);
    await fireEvent.click(getByTestId('feedback-button'));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    // Every fetch call's first arg is the version probe — no
    // analytics, no telemetry, no third-party reporter.
    for (const call of fetchSpy.mock.calls) {
      expect(call[0]).toBe('/api/version');
    }
  });
});
