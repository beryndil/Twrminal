/**
 * Svelte action — wires a right-click on the host element to open the
 * Bearings context menu for the given target.
 *
 * Usage in a consumer component:
 *
 * ```svelte
 * <button
 *   use:contextMenu={{
 *     target: MENU_TARGET_SESSION,
 *     handlers: {
 *       [MENU_ACTION_SESSION_RENAME]: () => rename(sessionId),
 *       [MENU_ACTION_SESSION_DELETE]: () => deleteSession(sessionId),
 *     },
 *     data: { sessionId },
 *   }}
 *   ...
 * >
 *   ...
 * </button>
 * ```
 *
 * The action stops native ``contextmenu`` propagation (preventing the
 * browser's default menu) and dispatches into :func:`openMenu`. Shift
 * held during the right-click reveals advanced actions per
 * ``docs/behavior/context-menus.md`` §"Common behavior".
 */
import type { MenuTargetId } from "../config";
import { openMenu } from "../context-menu/store.svelte";
import type { HandlerEntry } from "../context-menu/store.svelte";
import { longpress } from "../context-menu/touch";

interface ContextMenuActionParams {
  readonly target: MenuTargetId;
  readonly handlers: Readonly<Record<string, HandlerEntry>>;
  /**
   * When ``true`` the right-click is suppressed and no menu opens.
   * Used by consumers that conditionally show / hide the menu (e.g.
   * inside a cheat-sheet modal where right-click should fall through
   * to the browser's native menu per the doc).
   */
  readonly disabled?: boolean;
  /** Opaque payload exposed on :type:`OpenMenu.data` for tests. */
  readonly data?: unknown;
  /**
   * Force the stale flag — used by consumers that detected the target
   * was deleted between mouse-down and the menu opening. The menu
   * renders with every action greyed.
   */
  readonly stale?: boolean;
}

type CleanupFn = () => void;

interface ActionReturn {
  update: (params: ContextMenuActionParams) => void;
  destroy: CleanupFn;
}

export function contextMenu(node: HTMLElement, initial: ContextMenuActionParams): ActionReturn {
  let params = initial;

  function handleContextMenu(event: MouseEvent): void {
    if (params.disabled === true) return;
    event.preventDefault();
    event.stopPropagation();
    openMenu({
      target: params.target,
      handlers: params.handlers,
      data: params.data ?? null,
      x: event.clientX,
      y: event.clientY,
      advancedRevealed: event.shiftKey,
      stale: params.stale ?? false,
    });
  }

  function handleLongPress(x: number, y: number): void {
    if (params.disabled === true) return;
    openMenu({
      target: params.target,
      handlers: params.handlers,
      data: params.data ?? null,
      x,
      y,
      advancedRevealed: false,
      stale: params.stale ?? false,
    });
  }

  node.addEventListener("contextmenu", handleContextMenu);
  const { destroy: destroyLongPress } = longpress(node, { onLongPress: handleLongPress });

  return {
    update(next: ContextMenuActionParams): void {
      params = next;
    },
    destroy(): void {
      node.removeEventListener("contextmenu", handleContextMenu);
      destroyLongPress();
    },
  };
}
