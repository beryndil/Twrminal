/**
 * Menu placement math. Pure functions — unit tested, no DOM access.
 *
 * Phase 1 shipped cursor-anchored placement with viewport clamping
 * (`placeAtCursor`). Phase 2 adds:
 *
 *   - `placeAnchored` — a menu anchored to a DOM rect (e.g. a `⋯`
 *     trigger button). Prefers below-right, flips vertically when the
 *     bottom overflows, flips horizontally when the right overflows.
 *   - `placeSubmenu` — a submenu anchored to the parent row rect.
 *     Prefers to the right of the parent item, flips to the left when
 *     the right overflows.
 *
 * The cursor flavor is intentionally kept separate: right-click opens
 * at a 1-pixel point and benefits from clamp semantics (pin-to-margin)
 * whereas an anchored/submenu open prefers a full side flip. Keeping
 * the two call paths distinct avoids a forest of "was this a cursor or
 * an anchor?" branches inside one function.
 */

/** Minimum breathing room from the viewport edge. Matches the 4px
 * clamp called out in the plan's §6.1 rules. */
export const VIEWPORT_MARGIN_PX = 4;

/** Pixels of overlap between a submenu and its parent row. Keeps the
 * submenu visually tethered so users don't feel they're "jumping"
 * across a gap when the pointer crosses. */
export const SUBMENU_OVERLAP_PX = 2;

export type Placement = {
  left: number;
  top: number;
};

/** A viewport-relative rectangle. Matches the subset of DOMRect we
 * actually use so tests don't need to stub a full DOM object. */
export type Rect = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

export type Viewport = {
  viewportWidth: number;
  viewportHeight: number;
};

export type MenuSize = {
  menuWidth: number;
  menuHeight: number;
};

export type PlaceInput = {
  /** Desired anchor — usually the right-click `clientX`/`clientY`. */
  x: number;
  y: number;
} & MenuSize &
  Viewport;

/**
 * Place the menu's top-left at (x, y), clamped so no edge leaves the
 * viewport. If the menu is wider/taller than the viewport minus
 * margins, the margin wins — left/top pin to `VIEWPORT_MARGIN_PX`
 * and the overflow is accepted (the renderer's scroll handles it).
 */
export function placeAtCursor(input: PlaceInput): Placement {
  const { x, y, menuWidth, menuHeight, viewportWidth, viewportHeight } = input;
  const maxLeft = Math.max(
    VIEWPORT_MARGIN_PX,
    viewportWidth - menuWidth - VIEWPORT_MARGIN_PX
  );
  const maxTop = Math.max(
    VIEWPORT_MARGIN_PX,
    viewportHeight - menuHeight - VIEWPORT_MARGIN_PX
  );
  const left = Math.min(Math.max(x, VIEWPORT_MARGIN_PX), maxLeft);
  const top = Math.min(Math.max(y, VIEWPORT_MARGIN_PX), maxTop);
  return { left, top };
}

export type AnchoredInput = {
  /** Rect of the trigger element (button, row, etc). */
  anchor: Rect;
} & MenuSize &
  Viewport;

/**
 * Place a menu anchored to a trigger rect. Default side is below-right:
 * the menu's top aligns to `anchor.bottom`, its left aligns to
 * `anchor.left`. When the bottom of the menu would overflow the viewport
 * we flip above (top = `anchor.top - menuHeight`); when the right would
 * overflow we flip left (left = `anchor.right - menuWidth`).
 *
 * After the flip, a final clamp keeps the menu inside the viewport
 * margins — that covers pathological cases where neither side fits
 * (menu taller than viewport, etc). This matches the plan's §6.1 rule
 * "clamp 4px min margin" as the backstop.
 */
export function placeAnchored(input: AnchoredInput): Placement {
  const { anchor, menuWidth, menuHeight, viewportWidth, viewportHeight } =
    input;

  // Vertical: prefer below; flip above when below overflows.
  const fitsBelow =
    anchor.bottom + menuHeight + VIEWPORT_MARGIN_PX <= viewportHeight;
  const fitsAbove = anchor.top - menuHeight - VIEWPORT_MARGIN_PX >= 0;
  let top: number;
  if (fitsBelow) {
    top = anchor.bottom;
  } else if (fitsAbove) {
    top = anchor.top - menuHeight;
  } else {
    // Neither side has room — prefer below and let the clamp pin.
    top = anchor.bottom;
  }

  // Horizontal: prefer left-align; flip right-align when left overflows.
  const fitsLeftAlign =
    anchor.left + menuWidth + VIEWPORT_MARGIN_PX <= viewportWidth;
  const fitsRightAlign = anchor.right - menuWidth - VIEWPORT_MARGIN_PX >= 0;
  let left: number;
  if (fitsLeftAlign) {
    left = anchor.left;
  } else if (fitsRightAlign) {
    left = anchor.right - menuWidth;
  } else {
    left = anchor.left;
  }

  return clampToViewport(
    { left, top },
    { menuWidth, menuHeight, viewportWidth, viewportHeight }
  );
}

export type SubmenuInput = {
  /** Rect of the parent item (the row that expands into a submenu). */
  parent: Rect;
} & MenuSize &
  Viewport;

/**
 * Place a submenu next to its parent row. Default side is to the right
 * of the parent with a 2px overlap (`SUBMENU_OVERLAP_PX`). Flips to the
 * left of the parent when the right side overflows. Vertically the
 * submenu aligns to the parent's top, flipping to end-align when the
 * bottom overflows.
 */
export function placeSubmenu(input: SubmenuInput): Placement {
  const { parent, menuWidth, menuHeight, viewportWidth, viewportHeight } =
    input;

  const rightStart = parent.right - SUBMENU_OVERLAP_PX;
  const leftStart = parent.left - menuWidth + SUBMENU_OVERLAP_PX;
  const fitsRight =
    rightStart + menuWidth + VIEWPORT_MARGIN_PX <= viewportWidth;
  const fitsLeft = leftStart - VIEWPORT_MARGIN_PX >= 0;
  let left: number;
  if (fitsRight) {
    left = rightStart;
  } else if (fitsLeft) {
    left = leftStart;
  } else {
    left = rightStart; // clamp will pin
  }

  const topStart = parent.top;
  const fitsDown =
    topStart + menuHeight + VIEWPORT_MARGIN_PX <= viewportHeight;
  const upStart = parent.bottom - menuHeight;
  const fitsUp = upStart - VIEWPORT_MARGIN_PX >= 0;
  let top: number;
  if (fitsDown) {
    top = topStart;
  } else if (fitsUp) {
    top = upStart;
  } else {
    top = topStart;
  }

  return clampToViewport(
    { left, top },
    { menuWidth, menuHeight, viewportWidth, viewportHeight }
  );
}

/** Shared final clamp used by every flavor above. Extracted so the
 * margin semantics are identical whether the caller flipped or not. */
function clampToViewport(
  placement: Placement,
  size: MenuSize & Viewport
): Placement {
  const { menuWidth, menuHeight, viewportWidth, viewportHeight } = size;
  const maxLeft = Math.max(
    VIEWPORT_MARGIN_PX,
    viewportWidth - menuWidth - VIEWPORT_MARGIN_PX
  );
  const maxTop = Math.max(
    VIEWPORT_MARGIN_PX,
    viewportHeight - menuHeight - VIEWPORT_MARGIN_PX
  );
  return {
    left: Math.min(Math.max(placement.left, VIEWPORT_MARGIN_PX), maxLeft),
    top: Math.min(Math.max(placement.top, VIEWPORT_MARGIN_PX), maxTop)
  };
}
