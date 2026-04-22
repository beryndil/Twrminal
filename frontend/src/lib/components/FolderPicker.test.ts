import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';

import FolderPicker from './FolderPicker.svelte';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const HOME_LIST = {
  path: '/home/dave',
  parent: '/home',
  entries: [
    { name: 'Projects', path: '/home/dave/Projects', is_dir: true },
    { name: 'docs', path: '/home/dave/docs', is_dir: true }
  ]
};

const PROJECTS_LIST = {
  path: '/home/dave/Projects',
  parent: '/home/dave',
  entries: [{ name: 'Bearings', path: '/home/dave/Projects/Bearings', is_dir: true }]
};

function mockFetch(map: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    for (const [needle, body] of Object.entries(map)) {
      if (url.includes(needle))
        return new Response(JSON.stringify(body), { status: 200 });
    }
    if (!url.includes('path=')) {
      return new Response(JSON.stringify(HOME_LIST), { status: 200 });
    }
    return new Response('not found', { status: 404 });
  });
}

describe('FolderPicker', () => {
  beforeEach(() => {
    // jsdom lacks a default global fetch — tests install a stub per case.
  });

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

  it('clicking the trigger opens the dialog and fetches the current value', async () => {
    const fetchSpy = mockFetch({
      'path=%2Fhome%2Fdave': HOME_LIST
    });
    vi.stubGlobal('fetch', fetchSpy);
    const { getByLabelText, findByText } = render(FolderPicker, {
      value: '/home/dave'
    });
    await fireEvent.click(getByLabelText('Folder path'));
    await findByText('Projects');
    expect(fetchSpy).toHaveBeenCalled();
  });

  it('descending into a subdirectory refetches and updates breadcrumb', async () => {
    const fetchSpy = mockFetch({
      'path=%2Fhome%2Fdave%2FProjects': PROJECTS_LIST,
      'path=%2Fhome%2Fdave': HOME_LIST
    });
    vi.stubGlobal('fetch', fetchSpy);
    const { getByText, getByLabelText, findByText } = render(FolderPicker, {
      value: '/home/dave'
    });
    await fireEvent.click(getByLabelText('Folder path'));
    await findByText('Projects');
    await fireEvent.click(getByText('Projects'));
    await findByText('Bearings');
    expect(getByText('Projects')).toBeDefined();
  });

  it('"Use this folder" writes currentPath back to the trigger and closes', async () => {
    const fetchSpy = mockFetch({
      'path=%2Fhome%2Fdave%2FProjects': PROJECTS_LIST
    });
    vi.stubGlobal('fetch', fetchSpy);
    const { getByText, getByLabelText, findByText, queryByText } = render(
      FolderPicker,
      { value: '/home/dave/Projects' }
    );
    await fireEvent.click(getByLabelText('Folder path'));
    await findByText('Bearings');
    await fireEvent.click(getByText('Use this folder'));
    await waitFor(() => expect(queryByText('Use this folder')).toBeNull());
    const trigger = getByLabelText('Folder path') as HTMLButtonElement;
    expect(trigger.textContent?.trim()).toBe('/home/dave/Projects');
  });

  it('Cancel closes the dialog without changing the value', async () => {
    const fetchSpy = mockFetch({
      'path=%2Fhome%2Fdave%2FProjects': PROJECTS_LIST
    });
    vi.stubGlobal('fetch', fetchSpy);
    const { getByText, getByLabelText, findByText, queryByText } = render(
      FolderPicker,
      { value: '/home/dave/Projects' }
    );
    await fireEvent.click(getByLabelText('Folder path'));
    await findByText('Bearings');
    await fireEvent.click(getByText('Cancel'));
    await waitFor(() => expect(queryByText('Use this folder')).toBeNull());
    const trigger = getByLabelText('Folder path') as HTMLButtonElement;
    expect(trigger.textContent?.trim()).toBe('/home/dave/Projects');
  });

  it('surfaces fetch errors inline without changing the trigger text', async () => {
    const fetchSpy = vi.fn(
      async () => new Response('not found', { status: 404 })
    );
    vi.stubGlobal('fetch', fetchSpy);
    const { getByLabelText, findByText } = render(FolderPicker, {
      value: '/nope'
    });
    await fireEvent.click(getByLabelText('Folder path'));
    await findByText(/not found|404/);
    const trigger = getByLabelText('Folder path') as HTMLButtonElement;
    expect(trigger.textContent?.trim()).toBe('/nope');
  });
});
