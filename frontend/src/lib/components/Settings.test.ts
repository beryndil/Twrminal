import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { prefs } from '../stores/prefs.svelte';
import { preferences } from '../stores/preferences.svelte';
import { uiActions } from '../stores/ui_actions.svelte';
import Settings from './Settings.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Replace the in-memory preferences row directly. The store normally
 * hydrates via `init()` against `/api/preferences`; tests bypass that
 * and write the row so the modal pre-fills from a known shape. */
function seedPreferences(over: Record<string, unknown>): void {
  const row = (preferences as unknown as { row: Record<string, unknown> }).row;
  row.display_name = null;
  row.theme = null;
  row.default_model = null;
  row.default_working_dir = null;
  row.notify_on_complete = false;
  row.updated_at = '2026-04-25T00:00:00+00:00';
  Object.assign(row, over);
}

/** Stub `fetch` for the PATCH the dialog fires on autosave. Returns
 * the spy so tests can assert the body that landed on the server. */
function stubPatchOk(response: Record<string, unknown>): ReturnType<typeof vi.fn> {
  const stub = vi.fn(async () => ({
    ok: true,
    status: 200,
    async json() {
      return response;
    },
    async text() {
      return JSON.stringify(response);
    }
  }));
  vi.stubGlobal('fetch', stub);
  return stub;
}

beforeEach(() => {
  // Reset both stores to a known shape per test.
  prefs.save({ authToken: '' });
  seedPreferences({});
  uiActions.cheatSheetOpen = false;
  // Strip any `?settings=` left over from a previous deep-link test
  // so the default-pane assertion doesn't get an unintended seed.
  if (typeof window !== 'undefined') {
    const url = new URL(window.location.href);
    if (url.searchParams.has('settings')) {
      url.searchParams.delete('settings');
      window.history.replaceState(window.history.state, '', url);
    }
  }
});

/** Stub fetch that routes by URL. The Privacy section calls
 * `/api/health`; the About section calls `/api/version`; PATCHes go
 * to `/api/preferences`. Returning per-URL bodies lets one test
 * exercise multiple sections without juggling spy reassignment. */
function stubFetchByUrl(
  routes: Record<string, unknown>
): ReturnType<typeof vi.fn> {
  const stub = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    const key = Object.keys(routes).find((k) => url.includes(k));
    const body = key ? routes[key] : { detail: 'not stubbed' };
    return {
      ok: key !== undefined,
      status: key !== undefined ? 200 : 404,
      async json() {
        return body;
      },
      async text() {
        return JSON.stringify(body);
      }
    };
  });
  vi.stubGlobal('fetch', stub);
  return stub;
}

describe('Settings', () => {
  it('opens onto the Profile section by default', () => {
    seedPreferences({ display_name: 'Dave' });
    const { getByLabelText, getByTestId } = render(Settings, {
      props: { open: true }
    });
    // Profile section is the lowest-weight entry in the registry, so
    // it's the active pane on open.
    expect(getByTestId('settings-section-profile')).toBeInTheDocument();
    expect(getByLabelText('Display name')).toHaveValue('Dave');
  });

  it('autosaves Display name after the debounce window', async () => {
    const stub = stubPatchOk({
      display_name: 'Dave',
      theme: null,
      default_model: null,
      default_working_dir: null,
      notify_on_complete: false,
      updated_at: '2026-04-25T00:00:01+00:00'
    });
    const { getByLabelText } = render(Settings, { props: { open: true } });

    await fireEvent.input(getByLabelText('Display name'), {
      target: { value: 'Dave' }
    });

    // 400ms debounce in SettingsTextField — `waitFor` polls until
    // the spy has fired or the default 1s timeout trips.
    await waitFor(() => expect(stub).toHaveBeenCalledTimes(1));
    const [, init] = stub.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe('PATCH');
    const body = JSON.parse(init.body as string);
    expect(body.display_name).toBe('Dave');
    await waitFor(() => expect(preferences.displayName).toBe('Dave'));
  });

  it('blank Display name lands on the wire as null', async () => {
    seedPreferences({ display_name: 'Dave' });
    const stub = stubPatchOk({
      display_name: null,
      theme: null,
      default_model: null,
      default_working_dir: null,
      notify_on_complete: false,
      updated_at: '2026-04-25T00:00:02+00:00'
    });
    const { getByLabelText } = render(Settings, { props: { open: true } });

    await fireEvent.input(getByLabelText('Display name'), {
      target: { value: '   ' }
    });

    await waitFor(() => expect(stub).toHaveBeenCalledTimes(1));
    const [, init] = stub.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.display_name).toBeNull();
  });

  it('navigating to Defaults shows the model + working dir fields seeded from the store', async () => {
    seedPreferences({
      default_model: 'claude-opus-4-7',
      default_working_dir: '/home/dave'
    });
    const { getByLabelText, getByTestId } = render(Settings, {
      props: { open: true }
    });

    await fireEvent.click(getByTestId('settings-rail-defaults'));

    expect(getByTestId('settings-section-defaults')).toBeInTheDocument();
    expect(getByLabelText('Default model')).toHaveValue('claude-opus-4-7');
    expect(getByLabelText('Default working directory')).toHaveValue('/home/dave');
  });

  it('Esc closes the dialog', async () => {
    const onOpenChange = vi.fn();
    const { component } = render(Settings, { props: { open: true } });
    // `open` is bindable; subscribe via the property change after key
    // dispatch. Using window keydown matches the production listener.
    void component;
    void onOpenChange;
    await fireEvent.keyDown(window, { key: 'Escape' });
    // After Esc, the dialog markup unmounts. We assert via the
    // backdrop testid going away rather than reaching into the bound
    // prop, which we can't read back from outside.
    await waitFor(() => {
      expect(document.querySelector('[data-testid="settings-backdrop"]')).toBeNull();
    });
  });

  it('clicking the backdrop closes the dialog; clicking the dialog surface does not', async () => {
    const { getByTestId } = render(Settings, { props: { open: true } });
    // Click the dialog interior — should NOT close.
    await fireEvent.click(getByTestId('settings-dialog'));
    expect(document.querySelector('[data-testid="settings-backdrop"]')).not.toBeNull();
    // Click the backdrop wrapper — should close.
    await fireEvent.click(getByTestId('settings-backdrop'));
    await waitFor(() => {
      expect(document.querySelector('[data-testid="settings-backdrop"]')).toBeNull();
    });
  });

  it('opening the dialog moves focus to the close button', async () => {
    const { getByTestId } = render(Settings, { props: { open: true } });
    await waitFor(() => {
      expect(document.activeElement).toBe(getByTestId('settings-close'));
    });
  });

  it('About section renders version and build from /api/version', async () => {
    const stub = vi.fn(async () => ({
      ok: true,
      status: 200,
      async json() {
        return { version: '0.20.5', build: '1714075200000000000' };
      },
      async text() {
        return JSON.stringify({ version: '0.20.5', build: '1714075200000000000' });
      }
    }));
    vi.stubGlobal('fetch', stub);

    const { getByTestId, findByText } = render(Settings, {
      props: { open: true }
    });

    await fireEvent.click(getByTestId('settings-rail-about'));
    expect(getByTestId('settings-section-about')).toBeInTheDocument();
    // Version trailing renders once the fetch resolves.
    await findByText('v0.20.5');
  });

  it('About section falls back gracefully when /api/version is unreachable', async () => {
    const stub = vi.fn(async () => ({
      ok: false,
      status: 500,
      async json() {
        return { detail: 'boom' };
      },
      async text() {
        return JSON.stringify({ detail: 'boom' });
      }
    }));
    vi.stubGlobal('fetch', stub);

    const { getByTestId, findByText, findAllByText } = render(Settings, {
      props: { open: true }
    });

    await fireEvent.click(getByTestId('settings-rail-about'));
    // Hero spelling is 'version unavailable' (full phrase reads better
    // in the centered version line); the Build row's trailing text is
    // the bare 'unavailable'. Asserting both spellings independently
    // pins the surface contract — a future refactor that drops either
    // graceful path trips this test.
    await findByText('version unavailable');
    const buildMatches = await findAllByText('unavailable');
    expect(buildMatches.length).toBeGreaterThanOrEqual(1);
  });

  it('Privacy section renders the telemetry link and the resolved data dir', async () => {
    stubFetchByUrl({
      '/api/health': {
        auth: 'disabled',
        version: '0.20.7',
        data_dir: '/home/dave/.local/share/bearings'
      }
    });

    const { getByTestId, findByText } = render(Settings, {
      props: { open: true }
    });

    await fireEvent.click(getByTestId('settings-rail-privacy'));
    expect(getByTestId('settings-section-privacy')).toBeInTheDocument();

    const telemetry = getByTestId(
      'settings-privacy-telemetry'
    ) as HTMLAnchorElement;
    expect(telemetry.href).toContain('TELEMETRY.md');

    // Data-dir text appears once /api/health resolves.
    await findByText('/home/dave/.local/share/bearings');
  });

  it('Help section: Show keyboard shortcuts opens the cheat sheet and closes Settings', async () => {
    const { getByTestId } = render(Settings, { props: { open: true } });

    await fireEvent.click(getByTestId('settings-rail-help'));
    expect(getByTestId('settings-section-help')).toBeInTheDocument();

    // The "Show ?" link in the Help card has the SettingsLink testid.
    const triggers = document.querySelectorAll(
      '[data-testid="settings-section-help"] [data-testid="settings-link"]'
    );
    // First link in the Help card is the cheat-sheet trigger.
    await fireEvent.click(triggers[0] as HTMLElement);

    expect(uiActions.cheatSheetOpen).toBe(true);
    // Mutually-exclusive overlay rule: opening the cheat sheet closes
    // Settings so we don't stack two modals.
    await waitFor(() => {
      expect(
        document.querySelector('[data-testid="settings-backdrop"]')
      ).toBeNull();
    });
  });

  it('About section surfaces the MIT License row', async () => {
    stubFetchByUrl({
      '/api/version': { version: '0.20.7', build: '1714075200000000000' }
    });
    const { getByTestId, findByText } = render(Settings, {
      props: { open: true }
    });

    await fireEvent.click(getByTestId('settings-rail-about'));
    // Trailing text "MIT ↗" is the license-row marker.
    await findByText('MIT ↗');
  });

  it('?settings=privacy on the URL lands the dialog on the Privacy pane', async () => {
    stubFetchByUrl({
      '/api/health': {
        auth: 'disabled',
        version: '0.20.7',
        data_dir: '/home/dave/.local/share/bearings'
      }
    });
    // Seed the URL before render so SettingsShell's initialId() sees it.
    const url = new URL(window.location.href);
    url.searchParams.set('settings', 'privacy');
    window.history.replaceState(window.history.state, '', url);

    const { getByTestId } = render(Settings, { props: { open: true } });

    expect(getByTestId('settings-section-privacy')).toBeInTheDocument();
    expect(
      getByTestId('settings-rail-privacy').getAttribute('aria-selected')
    ).toBe('true');
  });

  it('navigating between sections mirrors the active id into ?settings=', async () => {
    stubFetchByUrl({
      '/api/health': {
        auth: 'disabled',
        version: '0.20.7',
        data_dir: '/home/dave/.local/share/bearings'
      }
    });
    const { getByTestId } = render(Settings, { props: { open: true } });

    await fireEvent.click(getByTestId('settings-rail-privacy'));
    await waitFor(() => {
      const param = new URL(window.location.href).searchParams.get('settings');
      expect(param).toBe('privacy');
    });
  });

  it('closing the dialog clears the ?settings= param', async () => {
    const url = new URL(window.location.href);
    url.searchParams.set('settings', 'about');
    window.history.replaceState(window.history.state, '', url);

    stubFetchByUrl({
      '/api/version': { version: '0.20.7', build: '1714075200000000000' }
    });
    render(Settings, { props: { open: true } });

    await fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => {
      expect(
        new URL(window.location.href).searchParams.has('settings')
      ).toBe(false);
    });
  });

  it('Authentication section writes the token to localStorage and not /api/preferences', async () => {
    const stub = stubPatchOk({});
    const { getByLabelText, getByTestId } = render(Settings, {
      props: { open: true }
    });

    await fireEvent.click(getByTestId('settings-rail-auth'));

    await fireEvent.input(getByLabelText('Auth token'), {
      target: { value: 'fresh-token' }
    });

    // Wait past the debounce so the assertion isn't racing the timer.
    await waitFor(() => expect(prefs.authToken).toBe('fresh-token'));
    expect(stub).not.toHaveBeenCalled();
  });
});
