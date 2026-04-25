import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import CheatSheet from './CheatSheet.svelte';
import { uiActions } from '$lib/stores/ui_actions.svelte';

beforeEach(() => {
  // Reset shared overlay state — the component reads `open` directly
  // from `uiActions` rather than a prop, so each test must set the
  // initial value before mount.
  uiActions.cheatSheetOpen = false;
});

afterEach(cleanup);

describe('CheatSheet', () => {
  it('renders nothing when closed', () => {
    uiActions.cheatSheetOpen = false;
    const { queryByRole } = render(CheatSheet);
    expect(queryByRole('heading', { name: 'Shortcuts' })).toBeNull();
  });

  it('renders the registry-driven binding list when open', () => {
    uiActions.cheatSheetOpen = true;
    const { getByRole, getByText } = render(CheatSheet);
    expect(getByRole('heading', { name: 'Shortcuts' })).toBeInTheDocument();
    // Registry-driven entries.
    expect(getByText('New chat')).toBeInTheDocument();
    expect(getByText('Next session in sidebar')).toBeInTheDocument();
    expect(getByText('Defocus input / dismiss overlay')).toBeInTheDocument();
    expect(getByText('Toggle command palette')).toBeInTheDocument();
    // Static (mouse-only) sections still render.
    expect(getByText('Send the prompt')).toBeInTheDocument();
  });

  it('close button flips the shared open flag', async () => {
    uiActions.cheatSheetOpen = true;
    const { getByRole } = render(CheatSheet);
    const close = getByRole('button', { name: 'Close cheat sheet' });
    await fireEvent.click(close);
    expect(uiActions.cheatSheetOpen).toBe(false);
  });
});
