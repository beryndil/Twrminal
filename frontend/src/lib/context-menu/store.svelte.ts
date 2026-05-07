/**
 * Context-menu store — the single canonical "is the menu open, and
 * what is it pointed at" state. One menu can be open at a time; a
 * second open call overrides the first (mirroring browser native
 * context-menu behavior).
 *
 * Components do NOT subscribe to this store reactively — the
 * :class:`ContextMenu.svelte` root reads it via ``$derived`` so the
 * floating menu re-renders on open / close. Mutation flows through
 * :func:`openMenu` / :func:`closeMenu`.
 */
import type { MenuTargetId } from "../config";

/**
 * A value in the consumer handler map.
 *
 * - ``() => void`` — the action is enabled; calling it fires the behaviour.
 * - ``{ disabledReason }`` — the action is explicitly disabled and the menu
 *   renders a native browser tooltip (via the ``title`` HTML attribute)
 *   explaining why it is unavailable.  Use this instead of omitting the key
 *   when you want the user to understand the precondition.
 *
 * Absent key (no entry) → disabled with no tooltip, matching the previous
 * behaviour for actions that have no applicable state context to explain.
 */
export type HandlerEntry = (() => void) | { readonly disabledReason: string };

/**
 * Open-menu state. ``null`` when no menu is open.
 *
 * Fields:
 *
 * - ``target`` — which per-target action list to walk.
 * - ``handlers`` — action-id → :type:`HandlerEntry` map; the consumer
 *   passes this on the right-click event so the menu can fire the right
 *   code.  Actions whose id is absent from the map render disabled with
 *   no tooltip; actions mapped to ``{ disabledReason }`` render disabled
 *   with a native tooltip explaining why.
 * - ``x`` / ``y`` — viewport coordinates the menu opens at.
 * - ``advancedRevealed`` — Shift was held during the right-click.
 * - ``stale`` — the right-clicked target no longer exists. The menu
 *   still opens but every action is disabled and the explanation
 *   "this object no longer exists." renders.
 * - ``data`` — opaque payload the consumer attaches; the action
 *   handlers close over it via the handler map closures, but
 *   exposing it on the open-record helps tests assert what the menu
 *   was opened with.
 */
interface OpenMenu {
  readonly target: MenuTargetId;
  readonly x: number;
  readonly y: number;
  readonly handlers: Readonly<Record<string, HandlerEntry>>;
  readonly advancedRevealed: boolean;
  readonly stale: boolean;
  readonly data: unknown;
}

interface ContextMenuState {
  open: OpenMenu | null;
}

const state: ContextMenuState = $state({ open: null });

/**
 * Reactive snapshot. Read ``contextMenuStore.open`` inside ``$derived``
 * to react to open / close.
 */
export const contextMenuStore = state;

/**
 * Open the menu at the given coordinates with the supplied handlers.
 * If a menu is already open, the new open replaces it.
 */
export function openMenu(menu: OpenMenu): void {
  state.open = menu;
}

/** Close the currently-open menu. No-op when no menu is open. */
export function closeMenu(): void {
  state.open = null;
}

/** Test seam — drop any open menu without invoking close handlers. */
export function _resetForTests(): void {
  state.open = null;
}
