/**
 * Central registry mapping target types to action lists.
 *
 * Phase 10 wires in the user's `~/.config/bearings/menus.toml`
 * overrides via the `menuConfig` store: `hidden` IDs drop, `pinned` IDs
 * float to the top of their section in the listed order. Shortcut
 * rebindings live on the same config surface but apply at the
 * keyboard-FSM layer (Phase 2 code), not here.
 *
 * Invariants:
 *   - Every `Action` belongs to exactly one target type.
 *   - IDs are unique within a target type. Enforced by registry.test.ts.
 *   - IDs are public API. Renames go through `Action.aliases` with a
 *     deprecation warning, never silently. See §7.3 of the plan.
 */

import { menuConfig } from '$lib/stores/menuConfig.svelte';
import type {
  Action,
  ActionSection,
  ContextTarget,
  RenderedMenu,
  TargetType
} from './types';
import { SECTIONS } from './types';
import { SESSION_ACTIONS } from './actions/session';
import { MESSAGE_ACTIONS } from './actions/message';
import { TAG_ACTIONS, TAG_CHIP_ACTIONS } from './actions/tag';
import { TOOL_CALL_ACTIONS } from './actions/tool_call';
import { CODE_BLOCK_ACTIONS } from './actions/code_block';
import { LINK_ACTIONS } from './actions/link';
import { CHECKPOINT_ACTIONS } from './actions/checkpoint';
import { MULTI_SELECT_ACTIONS } from './actions/multi_select';

const REGISTRY: Record<TargetType, readonly Action[]> = {
  session: SESSION_ACTIONS,
  message: MESSAGE_ACTIONS,
  tag: TAG_ACTIONS,
  tag_chip: TAG_CHIP_ACTIONS,
  tool_call: TOOL_CALL_ACTIONS,
  code_block: CODE_BLOCK_ACTIONS,
  link: LINK_ACTIONS,
  checkpoint: CHECKPOINT_ACTIONS,
  multi_select: MULTI_SELECT_ACTIONS
};

/** Unfiltered actions for a target type. */
export function getActions(type: TargetType): readonly Action[] {
  return REGISTRY[type] ?? [];
}

/** Reorder a section bucket so IDs listed in `pinnedOrder` appear
 * first, in that order, followed by the remaining actions in their
 * original declaration order. Pinned IDs that don't match any action
 * in the bucket are silently ignored — unknown IDs in `menus.toml` are
 * a no-op rather than a hard error (the user might pin an action from
 * a newer version of Bearings). */
function applyPinning(
  bucket: Action[],
  pinnedOrder: readonly string[]
): Action[] {
  if (pinnedOrder.length === 0) return bucket;
  const pinnedSet = new Set(pinnedOrder);
  const byId = new Map(bucket.map((a) => [a.id, a]));
  const pinned: Action[] = [];
  for (const id of pinnedOrder) {
    const action = byId.get(id);
    if (action) pinned.push(action);
  }
  const rest = bucket.filter((a) => !pinnedSet.has(a.id));
  return [...pinned, ...rest];
}

/**
 * Resolve the menu for a specific target at render time.
 *
 * Filters out:
 *   - `advanced: true` items when `advanced` is false.
 *   - items whose `requires(target)` returns false.
 *   - items whose id appears in the target's `menus.toml` `hidden`
 *     list. Hidden items stay reachable via Ctrl+Shift+P — the
 *     command palette queries the raw registry, not `resolveMenu`.
 *
 * Reorders each section bucket so `menus.toml` `pinned` IDs float to
 * the top in their listed order. Unknown pinned IDs are dropped
 * silently so a typo or a reference to a retired action ID doesn't
 * brick the menu.
 *
 * Does NOT filter by `disabled` — disabled items render in place
 * (greyed with tooltip) per decision §2.3.
 *
 * Groups results by section, preserving the spec's canonical section
 * order. Empty sections are dropped so the renderer doesn't produce
 * stray dividers.
 */
export function resolveMenu(
  target: ContextTarget,
  advanced: boolean
): RenderedMenu {
  const overrides = menuConfig.forTarget(target.type);
  const hiddenSet = new Set(overrides.hidden);
  const all = getActions(target.type);
  const visible = all.filter((a) => {
    if (a.advanced && !advanced) return false;
    if (a.requires && !a.requires(target)) return false;
    if (hiddenSet.has(a.id)) return false;
    return true;
  });
  const bySection = new Map<ActionSection, Action[]>();
  for (const action of visible) {
    const bucket = bySection.get(action.section);
    if (bucket) bucket.push(action);
    else bySection.set(action.section, [action]);
  }
  const groups: RenderedMenu['groups'] = [];
  for (const section of SECTIONS) {
    const actions = bySection.get(section);
    if (actions && actions.length > 0) {
      groups.push({ section, actions: applyPinning(actions, overrides.pinned) });
    }
  }
  return { target, advanced, groups };
}
