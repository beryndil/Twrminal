/**
 * Context-menu viewport-clamping helpers.
 *
 * ``placeAtCursor`` computes a top-left origin for a floating menu so
 * that the menu stays entirely within the viewport.  The math mirrors
 * v17's ``positioning.ts::placeAtCursor``:
 *
 *   left = clamp(x, MARGIN, viewportWidth  - menuWidth  - MARGIN)
 *   top  = clamp(y, MARGIN, viewportHeight - menuHeight - MARGIN)
 *
 * where ``MARGIN = VIEWPORT_MARGIN_PX = 4``.
 *
 * Behavior anchor: ``docs/behavior/context-menus.md``
 * §"Common behavior — Opening the menu".
 */

/** Minimum gap (px) between any menu edge and the viewport boundary. */
export const VIEWPORT_MARGIN_PX = 4;

/** Input to :func:`placeAtCursor`. */
export interface PlaceAtCursorInput {
  /** Raw cursor X (``event.clientX``). */
  readonly x: number;
  /** Raw cursor Y (``event.clientY``). */
  readonly y: number;
  /** Rendered menu width in px. */
  readonly menuWidth: number;
  /** Rendered menu height in px. */
  readonly menuHeight: number;
  /** Viewport width (``window.innerWidth``). */
  readonly viewportWidth: number;
  /** Viewport height (``window.innerHeight``). */
  readonly viewportHeight: number;
}

/** Clamped ``position: fixed`` origin for a floating menu. */
export interface Position {
  /** CSS ``left`` value in px. */
  readonly left: number;
  /** CSS ``top`` value in px. */
  readonly top: number;
}

/**
 * Clamp a cursor position so the floating menu fits inside the viewport.
 *
 * The returned ``left`` / ``top`` are suitable for ``style:left`` /
 * ``style:top`` on a ``position: fixed`` element.
 *
 * When the menu is wider or taller than the viewport the origin pins to
 * ``VIEWPORT_MARGIN_PX`` (top-left margin), which is the least-bad
 * fallback for oversized menus.
 */
export function placeAtCursor({
  x,
  y,
  menuWidth,
  menuHeight,
  viewportWidth,
  viewportHeight,
}: PlaceAtCursorInput): Position {
  // Upper bounds are floored at VIEWPORT_MARGIN_PX so that an oversized menu
  // (wider or taller than the viewport) pins to the top-left margin rather
  // than producing a negative coordinate.
  const maxLeft = Math.max(VIEWPORT_MARGIN_PX, viewportWidth - menuWidth - VIEWPORT_MARGIN_PX);
  const maxTop = Math.max(VIEWPORT_MARGIN_PX, viewportHeight - menuHeight - VIEWPORT_MARGIN_PX);
  const left = Math.min(Math.max(x, VIEWPORT_MARGIN_PX), maxLeft);
  const top = Math.min(Math.max(y, VIEWPORT_MARGIN_PX), maxTop);
  return { left, top };
}
