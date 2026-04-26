/** Specs for SettingsShell.
 *
 * Contract surface:
 *  - Opens onto the first (lowest-weight) section in the registry.
 *  - Clicking a rail item activates that section's pane.
 *  - ↓ on the rail moves focus/active section down one entry.
 *  - ↑ moves up; Home jumps to first; End jumps to last.
 *  - aria-selected on the active rail item is "true" (the rest are
 *    "false") so a screen reader can announce it as the current tab.
 */
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import SettingsShell from './SettingsShell.svelte';
import { SETTINGS_SECTIONS } from './sections';

afterEach(cleanup);

// SettingsShell now seeds its initial active section from
// `?settings=<id>` on the URL and writes the active id back as the
// user navigates. Tests run in a single jsdom window, so a previous
// test's URL writes leak forward unless we strip them. Without this,
// the "ArrowDown advances by one" test starts on whatever section the
// last test landed on, not on SETTINGS_SECTIONS[0].
beforeEach(() => {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  if (url.searchParams.has('settings')) {
    url.searchParams.delete('settings');
    window.history.replaceState(window.history.state, '', url);
  }
});

describe('SettingsShell', () => {
  it('lands on the first section by default', () => {
    const { getByTestId } = render(SettingsShell);
    const firstId = SETTINGS_SECTIONS[0].id;
    const railItem = getByTestId(`settings-rail-${firstId}`);
    expect(railItem.getAttribute('aria-selected')).toBe('true');
  });

  it('clicking a rail item activates that section', async () => {
    const { getByTestId } = render(SettingsShell);
    const target = SETTINGS_SECTIONS[2]; // arbitrary non-first
    await fireEvent.click(getByTestId(`settings-rail-${target.id}`));
    expect(
      getByTestId(`settings-rail-${target.id}`).getAttribute('aria-selected')
    ).toBe('true');
  });

  it('ArrowDown on the rail advances by one section', async () => {
    const { getByTestId, getByRole } = render(SettingsShell);
    const tablist = getByRole('tablist');
    await fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    const secondId = SETTINGS_SECTIONS[1].id;
    expect(
      getByTestId(`settings-rail-${secondId}`).getAttribute('aria-selected')
    ).toBe('true');
  });

  it('End jumps to the last section', async () => {
    const { getByTestId, getByRole } = render(SettingsShell);
    await fireEvent.keyDown(getByRole('tablist'), { key: 'End' });
    const lastId = SETTINGS_SECTIONS[SETTINGS_SECTIONS.length - 1].id;
    expect(
      getByTestId(`settings-rail-${lastId}`).getAttribute('aria-selected')
    ).toBe('true');
  });

  it('Home jumps to the first section', async () => {
    const { getByTestId, getByRole } = render(SettingsShell);
    // Move away first.
    await fireEvent.keyDown(getByRole('tablist'), { key: 'End' });
    await fireEvent.keyDown(getByRole('tablist'), { key: 'Home' });
    const firstId = SETTINGS_SECTIONS[0].id;
    expect(
      getByTestId(`settings-rail-${firstId}`).getAttribute('aria-selected')
    ).toBe('true');
  });
});
