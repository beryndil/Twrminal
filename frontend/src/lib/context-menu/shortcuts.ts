/**
 * Shortcut collector for the CheatSheet — Phase 13 of the context-menu
 * plan. Walks the action registry + `menuConfig` overrides and returns
 * a flat list of `{target, id, label, chord}` so the cheat sheet can
 * render whatever chord rebindings the user has declared in
 * `menus.toml`. No actions in the current registry carry a built-in
 * `shortcut` field, so the list is entirely user-driven today — it
 * becomes non-empty once the user edits `menus.toml`.
 *
 * Kept as a pure function rather than a store so reactive consumers
 * (Svelte components) can call it inside a `$derived.by` and pick up
 * both the built-in defaults and any rebindings pushed via
 * `menuConfig.hydrate`.
 */

import { menuConfig } from '$lib/stores/menuConfig.svelte';
import { getActions } from './registry';
import type { TargetType } from './types';

export type MenuShortcutEntry = {
  /** Discriminator the action belongs to (`session`, `message`, …). */
  target: TargetType;
  /** Stable action id — the same key `menus.toml` uses. */
  id: string;
  /** Visible label for the action. Falls back to the id if the action
   * was hidden or retired between releases (the user could still have
   * a dangling shortcut in their TOML). */
  label: string;
  /** The chord the user bound (e.g. "ctrl+d"). Normalised to lowercase
   * so the renderer can split on `+` and stable-sort. */
  chord: string;
};

/** Every target type we know about. Mirrors the Pydantic
 * `KNOWN_TARGET_TYPES` on the backend — if one drifts, the other's
 * test suite catches it. */
const TARGET_TYPES: readonly TargetType[] = [
  'session',
  'message',
  'tag',
  'tag_chip',
  'tool_call',
  'code_block',
  'link',
  'checkpoint',
  'multi_select'
];

/** Resolve an action id to its display label for the current release.
 * Returns `id` verbatim when the id doesn't match any registered
 * action — the user might have a binding for an action that was
 * retired or renamed without an alias. Keeping stale rows visible
 * beats hiding them silently, because the user needs to know their
 * TOML references something that no longer exists. */
function labelFor(target: TargetType, id: string): string {
  const action = getActions(target).find((a) => a.id === id);
  return action?.label ?? id;
}

/** Collect every chord rebinding across every target type. Ordered
 * by target (registry order) then chord for a stable render. */
export function collectMenuShortcuts(): MenuShortcutEntry[] {
  const out: MenuShortcutEntry[] = [];
  for (const target of TARGET_TYPES) {
    const overrides = menuConfig.forTarget(target);
    const entries = Object.entries(overrides.shortcuts);
    // Stable alphabetical ordering within a target makes the cheat
    // sheet easier to scan and keeps test assertions deterministic.
    entries.sort(([a], [b]) => a.localeCompare(b));
    for (const [id, chord] of entries) {
      out.push({
        target,
        id,
        label: labelFor(target, id),
        chord: chord.toLowerCase()
      });
    }
  }
  return out;
}
