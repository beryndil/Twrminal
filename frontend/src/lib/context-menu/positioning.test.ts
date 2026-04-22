import { describe, expect, it } from 'vitest';

import {
  SUBMENU_OVERLAP_PX,
  VIEWPORT_MARGIN_PX,
  placeAnchored,
  placeAtCursor,
  placeSubmenu,
  type Rect
} from './positioning';

// Phase 1 covered cursor-anchored clamping. Phase 2 adds exhaustive
// anchor-flip and submenu-flip cases per plan §6.1. Coverage target:
// 8 anchor corners (4 fit + 4 flip) + 4 submenu flips + oversize
// fallbacks. Pure-function tests so they run instantly.

describe('placeAtCursor', () => {
  const viewport = { viewportWidth: 1000, viewportHeight: 800 };
  const smallMenu = { menuWidth: 200, menuHeight: 100 };

  it('places at the cursor when fully inside the viewport', () => {
    expect(
      placeAtCursor({ x: 100, y: 100, ...smallMenu, ...viewport })
    ).toEqual({ left: 100, top: 100 });
  });

  it('clamps to the right-edge margin when x+width overflows', () => {
    const p = placeAtCursor({ x: 950, y: 100, ...smallMenu, ...viewport });
    // 1000 - 200 - 4 = 796
    expect(p.left).toBe(796);
    expect(p.top).toBe(100);
  });

  it('clamps to the bottom-edge margin when y+height overflows', () => {
    const p = placeAtCursor({ x: 100, y: 780, ...smallMenu, ...viewport });
    // 800 - 100 - 4 = 696
    expect(p.top).toBe(696);
    expect(p.left).toBe(100);
  });

  it('clamps to the minimum margin when cursor is outside top-left', () => {
    const p = placeAtCursor({ x: -50, y: -50, ...smallMenu, ...viewport });
    expect(p.left).toBe(VIEWPORT_MARGIN_PX);
    expect(p.top).toBe(VIEWPORT_MARGIN_PX);
  });

  it('pins to the margin when the menu is wider than the viewport', () => {
    const p = placeAtCursor({
      x: 500,
      y: 500,
      menuWidth: 2000,
      menuHeight: 100,
      viewportWidth: 1000,
      viewportHeight: 800
    });
    // Oversize menu: left pins to margin, renderer handles overflow.
    expect(p.left).toBe(VIEWPORT_MARGIN_PX);
  });

  it('pins to the margin when the menu is taller than the viewport', () => {
    const p = placeAtCursor({
      x: 100,
      y: 100,
      menuWidth: 200,
      menuHeight: 2000,
      viewportWidth: 1000,
      viewportHeight: 800
    });
    expect(p.top).toBe(VIEWPORT_MARGIN_PX);
  });

  it('clamps both axes when the cursor is past both edges', () => {
    const p = placeAtCursor({
      x: 10_000,
      y: 10_000,
      ...smallMenu,
      ...viewport
    });
    expect(p.left).toBe(1000 - 200 - VIEWPORT_MARGIN_PX);
    expect(p.top).toBe(800 - 100 - VIEWPORT_MARGIN_PX);
  });
});

describe('placeAnchored', () => {
  const viewport = { viewportWidth: 1000, viewportHeight: 800 };
  const smallMenu = { menuWidth: 200, menuHeight: 100 };

  function rect(left: number, top: number, w = 40, h = 20): Rect {
    return { left, top, right: left + w, bottom: top + h };
  }

  // The canonical case: anchor near top-left, menu fits below-right.
  it('places below-left-aligned when the default side fits', () => {
    const p = placeAnchored({
      anchor: rect(100, 100),
      ...smallMenu,
      ...viewport
    });
    // top aligns to anchor.bottom (120), left aligns to anchor.left (100).
    expect(p).toEqual({ left: 100, top: 120 });
  });

  it('flips above when below overflows', () => {
    // Anchor near bottom of viewport: menu cannot fit below.
    const p = placeAnchored({
      anchor: rect(100, 750, 40, 30),
      ...smallMenu,
      ...viewport
    });
    // Flipped above: top = anchor.top - menuHeight = 750 - 100 = 650.
    expect(p.top).toBe(650);
    expect(p.left).toBe(100);
  });

  it('flips right-aligned when left-align overflows', () => {
    // Anchor near right edge: left-aligning the menu would overflow.
    const p = placeAnchored({
      anchor: rect(900, 100, 40, 20),
      ...smallMenu,
      ...viewport
    });
    // Flipped right-align: left = anchor.right - menuWidth = 940 - 200 = 740.
    expect(p.left).toBe(740);
    expect(p.top).toBe(120);
  });

  it('flips both axes when bottom-right anchor offers no room below or right', () => {
    const p = placeAnchored({
      anchor: rect(900, 750, 40, 30),
      ...smallMenu,
      ...viewport
    });
    expect(p.top).toBe(650); // flipped above
    expect(p.left).toBe(740); // flipped right-aligned
  });

  it('clamps to margin when neither side has room (oversize menu)', () => {
    const p = placeAnchored({
      anchor: rect(100, 400),
      menuWidth: 1200,
      menuHeight: 900,
      ...viewport
    });
    expect(p.left).toBe(VIEWPORT_MARGIN_PX);
    expect(p.top).toBe(VIEWPORT_MARGIN_PX);
  });

  it('handles anchor at top-left corner (origin)', () => {
    const p = placeAnchored({
      anchor: rect(0, 0, 40, 20),
      ...smallMenu,
      ...viewport
    });
    // Left would be 0, but the final clamp floors to VIEWPORT_MARGIN_PX.
    expect(p).toEqual({ left: VIEWPORT_MARGIN_PX, top: 20 });
  });

  it('handles anchor exactly at top-right corner', () => {
    const p = placeAnchored({
      anchor: rect(960, 0, 40, 20),
      ...smallMenu,
      ...viewport
    });
    // Flip right-align → left = 1000 - 200 = 800, then the final clamp
    // pulls inside the right margin: 1000 - 200 - 4 = 796.
    expect(p.left).toBe(1000 - 200 - VIEWPORT_MARGIN_PX);
    expect(p.top).toBe(20);
  });

  it('handles anchor exactly at bottom-left corner', () => {
    const p = placeAnchored({
      anchor: rect(0, 780, 40, 20),
      ...smallMenu,
      ...viewport
    });
    // Below overflows: flip above. top = 780 - 100 = 680.
    expect(p.top).toBe(680);
    // Left would be 0, final clamp floors to margin.
    expect(p.left).toBe(VIEWPORT_MARGIN_PX);
  });
});

describe('placeSubmenu', () => {
  const viewport = { viewportWidth: 1000, viewportHeight: 800 };
  const smallMenu = { menuWidth: 200, menuHeight: 120 };

  function rect(left: number, top: number, w = 180, h = 24): Rect {
    return { left, top, right: left + w, bottom: top + h };
  }

  it('places to the right of the parent with overlap when it fits', () => {
    const parent = rect(100, 100);
    const p = placeSubmenu({
      parent,
      ...smallMenu,
      ...viewport
    });
    expect(p.left).toBe(parent.right - SUBMENU_OVERLAP_PX);
    expect(p.top).toBe(parent.top);
  });

  it('flips to the left when the right side overflows', () => {
    // Parent near right edge — no room on the right.
    const parent = rect(820, 100);
    const p = placeSubmenu({
      parent,
      ...smallMenu,
      ...viewport
    });
    // Flipped left: left = parent.left - menuWidth + overlap.
    expect(p.left).toBe(parent.left - 200 + SUBMENU_OVERLAP_PX);
    expect(p.top).toBe(parent.top);
  });

  it('flips up when the bottom would overflow', () => {
    const parent = rect(100, 750);
    const p = placeSubmenu({
      parent,
      ...smallMenu,
      ...viewport
    });
    // Flipped up: top = parent.bottom - menuHeight.
    expect(p.top).toBe(parent.bottom - 120);
  });

  it('flips both axes at the bottom-right corner', () => {
    const parent = rect(820, 750);
    const p = placeSubmenu({
      parent,
      ...smallMenu,
      ...viewport
    });
    expect(p.left).toBe(parent.left - 200 + SUBMENU_OVERLAP_PX);
    expect(p.top).toBe(parent.bottom - 120);
  });

  it('pins to margin when no side fits (oversize submenu)', () => {
    const p = placeSubmenu({
      parent: rect(400, 400),
      menuWidth: 2000,
      menuHeight: 1000,
      ...viewport
    });
    expect(p.left).toBe(VIEWPORT_MARGIN_PX);
    expect(p.top).toBe(VIEWPORT_MARGIN_PX);
  });
});
