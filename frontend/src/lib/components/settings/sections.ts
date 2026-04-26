/**
 * Section registry for the Settings dialog.
 *
 * Each entry describes one pane that the left nav rail surfaces and
 * the content pane renders when active. The shell composes the dialog
 * from this list — there is no hardcoded section switch in
 * `Settings.svelte`. To add a section: append an entry, ship the
 * component, done.
 *
 * `weight` is the sort key. Tightly-spaced integers (10, 20, 30, …)
 * leave room to wedge new sections in without renumbering. Lower is
 * higher in the rail.
 *
 * `id` is the URL-safe slug used for in-dialog routing if/when we
 * wire `?settings=<id>` deep-links. It also serves as the stable
 * `data-testid` selector and the localStorage key for "remember the
 * last section the user was on."
 *
 * Mirrors the pattern of Spyglass's `SettingsSection` (one entry per
 * pluggable module), but without the runtime registration plumbing —
 * Bearings settings are centrally defined, so a static array suffices.
 */

import type { Component } from 'svelte';

import ProfileSection from './sections/ProfileSection.svelte';
import AppearanceSection from './sections/AppearanceSection.svelte';
import DefaultsSection from './sections/DefaultsSection.svelte';
import NotificationsSection from './sections/NotificationsSection.svelte';
import AuthSection from './sections/AuthSection.svelte';
import PrivacySection from './sections/PrivacySection.svelte';
import HelpSection from './sections/HelpSection.svelte';
import AboutSection from './sections/AboutSection.svelte';

export interface SettingsSection {
  /** Stable URL-safe slug. Used for routing + test selectors. */
  id: string;
  /** Display label in the rail and content header. Sentence case. */
  label: string;
  /** Optional one-line subtitle rendered under the section header. */
  description?: string;
  /** Sort key for the rail. Lower is higher. */
  weight: number;
  /** The pane component. Receives no props — pulls from stores. */
  component: Component;
}

export const SETTINGS_SECTIONS: SettingsSection[] = [
  {
    id: 'profile',
    label: 'Profile',
    description: 'How you appear in your own conversations.',
    weight: 10,
    component: ProfileSection
  },
  {
    id: 'appearance',
    label: 'Appearance',
    description: 'Theme and visual density.',
    weight: 20,
    component: AppearanceSection
  },
  {
    id: 'defaults',
    label: 'Defaults',
    description: 'What new sessions start with.',
    weight: 30,
    component: DefaultsSection
  },
  {
    id: 'notifications',
    label: 'Notifications',
    description: 'When Bearings is allowed to interrupt you.',
    weight: 40,
    component: NotificationsSection
  },
  {
    id: 'auth',
    label: 'Authentication',
    description: 'Server access token. Stays on this device.',
    weight: 50,
    component: AuthSection
  },
  {
    id: 'privacy',
    label: 'Privacy',
    description: 'What Bearings collects, where your data lives.',
    weight: 60,
    component: PrivacySection
  },
  {
    id: 'help',
    label: 'Help',
    description: 'Keyboard shortcuts, README, and documentation.',
    weight: 70,
    component: HelpSection
  },
  {
    id: 'about',
    label: 'About',
    description: 'Version and build information.',
    weight: 80,
    component: AboutSection
  }
].sort((a, b) => a.weight - b.weight);
