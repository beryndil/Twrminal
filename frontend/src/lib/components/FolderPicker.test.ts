import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';

import FolderPicker from './FolderPicker.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Stub the backend `POST /api/fs/pick` bridge. The route shells out to
 * zenity/kdialog in production, so the test never executes a real binary —
 * we only exercise the client-side wiring (button → fetch → value update). */
function mockPickResponse(body: unknown, status = 200) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (!url.includes('/api/fs/pick')) {
      throw new Error(`unexpected fetch to ${url}`);
    }
    if (init?.method !== 'POST') {
      throw new Error(`expected POST, got ${init?.method}`);
    }
    return new Response(JSON.stringify(body), { status });
  });
}

describe('FolderPicker', () => {
  it('renders the value as a clickable trigger', () => {
    const { getByLabelText } = render(FolderPicker, { value: '/home/dave' });
    const trigger = getByLabelText('Folder path') as HTMLButtonElement;
    expect(trigger.tagName).toBe('BUTTON');
    expect(trigger.textContent?.trim()).toBe('/home/dave');
  });

  it('shows the placeholder when value is empty', () => {
    const { getByLabelText } = render(FolderPicker, {
      value: '',
      placeholder: 'click to choose…'
    });
    const trigger = getByLabelText('Folder path') as HTMLButtonElement;
    expect(trigger.textContent?.trim()).toBe('click to choose…');
  });

  it('clicking the trigger pops the native picker and writes the chosen path', async () => {
    const fetchSpy = mockPickResponse({
      path: '/home/dave/Projects/Bearings',
      paths: ['/home/dave/Projects/Bearings'],
      cancelled: false
    });
    vi.stubGlobal('fetch', fetchSpy);
    const { getByLabelText } = render(FolderPicker, { value: '/home/dave' });
    await fireEvent.click(getByLabelText('Folder path'));
    await waitFor(() => {
      const trigger = getByLabelText('Folder path') as HTMLButtonElement;
      expect(trigger.textContent?.trim()).toBe('/home/dave/Projects/Bearings');
    });
    expect(fetchSpy).toHaveBeenCalled();
    // Starts the dialog at the current value so the user isn't thrown
    // back to $HOME every time they re-open a session form.
    const url = fetchSpy.mock.calls[0][0];
    expect(url).toContain('mode=directory');
    expect(url).toContain('start=%2Fhome%2Fdave');
  });

  it('cancelled pick leaves the value untouched', async () => {
    const fetchSpy = mockPickResponse({
      path: null,
      paths: [],
      cancelled: true
    });
    vi.stubGlobal('fetch', fetchSpy);
    const { getByLabelText } = render(FolderPicker, { value: '/home/dave' });
    await fireEvent.click(getByLabelText('Folder path'));
    // Wait past the transient "Picking…" label so we're observing the
    // post-resolve state — otherwise the assertion races the promise.
    await waitFor(() => {
      const t = getByLabelText('Folder path') as HTMLButtonElement;
      expect(t.textContent?.trim()).not.toBe('Picking…');
    });
    const trigger = getByLabelText('Folder path') as HTMLButtonElement;
    expect(trigger.textContent?.trim()).toBe('/home/dave');
    expect(fetchSpy).toHaveBeenCalled();
  });

  it('surfaces backend errors inline without clobbering the value', async () => {
    const fetchSpy = vi.fn(
      async () =>
        new Response('no native file picker available', { status: 501 })
    );
    vi.stubGlobal('fetch', fetchSpy);
    const { getByLabelText, findByTestId } = render(FolderPicker, {
      value: '/home/dave'
    });
    await fireEvent.click(getByLabelText('Folder path'));
    const err = await findByTestId('folder-picker-error');
    expect(err.textContent).toMatch(/501|no native file picker/);
    const trigger = getByLabelText('Folder path') as HTMLButtonElement;
    expect(trigger.textContent?.trim()).toBe('/home/dave');
  });
});
