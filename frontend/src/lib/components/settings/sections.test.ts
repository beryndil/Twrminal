/** Specs for the settings section registry.
 *
 * Contract surface:
 *  - SETTINGS_SECTIONS is sorted ascending by `weight` so the rail
 *    renders in the intended order.
 *  - Every entry carries a stable id, label, and component.
 *  - The standards-§15 navigation set ships: profile, appearance,
 *    defaults, notifications, auth, privacy, help, about.
 *  - The §15 standard explicitly names appearance, notifications,
 *    privacy, help, about as required — guard those individually so
 *    a future refactor that drops one trips this test.
 */
import { describe, expect, it } from 'vitest';

import { SETTINGS_SECTIONS } from './sections';

describe('SETTINGS_SECTIONS', () => {
  it('is sorted ascending by weight', () => {
    const weights = SETTINGS_SECTIONS.map((s) => s.weight);
    const sorted = [...weights].sort((a, b) => a - b);
    expect(weights).toEqual(sorted);
  });

  it('every entry has id, label, and component', () => {
    for (const s of SETTINGS_SECTIONS) {
      expect(typeof s.id).toBe('string');
      expect(s.id).toMatch(/^[a-z][a-z0-9-]*$/);
      expect(typeof s.label).toBe('string');
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.component).toBeDefined();
    }
  });

  it('ships the standards-§15 navigation set', () => {
    const ids = SETTINGS_SECTIONS.map((s) => s.id).sort();
    expect(ids).toEqual([
      'about',
      'appearance',
      'auth',
      'defaults',
      'help',
      'notifications',
      'privacy',
      'profile'
    ]);
  });

  it.each(['appearance', 'notifications', 'privacy', 'help', 'about'])(
    'includes the §15-required %s section',
    (id) => {
      expect(SETTINGS_SECTIONS.find((s) => s.id === id)).toBeDefined();
    }
  );

  it('ids are unique', () => {
    const ids = SETTINGS_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
