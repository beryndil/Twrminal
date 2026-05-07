/**
 * Unit tests for context-menu viewport clamping (gap-cycle-15-002).
 *
 * Table-driven cases cover all four clamp edges plus the fits-inside
 * and oversized-menu scenarios mandated by the acceptance criteria.
 */
import { describe, expect, it } from "vitest";

import { VIEWPORT_MARGIN_PX, placeAtCursor } from "../positioning";

const VW = 1920;
const VH = 1080;
const MENU_W = 200;
const MENU_H = 300;
const M = VIEWPORT_MARGIN_PX; // 4

describe("VIEWPORT_MARGIN_PX", () => {
  it("equals 4 px (matching v17)", () => {
    expect(VIEWPORT_MARGIN_PX).toBe(4);
  });
});

describe("placeAtCursor", () => {
  it("fits inside — cursor position returned unchanged", () => {
    const pos = placeAtCursor({
      x: 100,
      y: 100,
      menuWidth: MENU_W,
      menuHeight: MENU_H,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    expect(pos.left).toBe(100);
    expect(pos.top).toBe(100);
  });

  it("clamps right edge — menu pinned to viewportWidth - menuWidth - margin", () => {
    // Right-click 50 px from the right edge: the right side of the menu
    // would overflow, so left is pulled left.
    const x = VW - 50;
    const pos = placeAtCursor({
      x,
      y: 100,
      menuWidth: MENU_W,
      menuHeight: MENU_H,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    expect(pos.left).toBe(VW - MENU_W - M);
    expect(pos.top).toBe(100);
  });

  it("clamps bottom edge — menu pinned to viewportHeight - menuHeight - margin", () => {
    // Right-click 50 px from the bottom: the menu bottom would overflow.
    const y = VH - 50;
    const pos = placeAtCursor({
      x: 100,
      y,
      menuWidth: MENU_W,
      menuHeight: MENU_H,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    expect(pos.left).toBe(100);
    expect(pos.top).toBe(VH - MENU_H - M);
  });

  it("clamps left edge — cursor at x<margin pins to VIEWPORT_MARGIN_PX", () => {
    const pos = placeAtCursor({
      x: -10,
      y: 100,
      menuWidth: MENU_W,
      menuHeight: MENU_H,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    expect(pos.left).toBe(M);
  });

  it("clamps top edge — cursor at y=0 pins to VIEWPORT_MARGIN_PX", () => {
    const pos = placeAtCursor({
      x: 100,
      y: 0,
      menuWidth: MENU_W,
      menuHeight: MENU_H,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    expect(pos.top).toBe(M);
  });

  it("oversized menu — pins to top-left margin rather than overflowing left", () => {
    // A menu wider/taller than the viewport: the right-clamp max() would
    // underflow below VIEWPORT_MARGIN_PX; the outer min/max keeps it at M.
    const pos = placeAtCursor({
      x: 100,
      y: 100,
      menuWidth: VW + 100,
      menuHeight: VH + 100,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    expect(pos.left).toBe(M);
    expect(pos.top).toBe(M);
  });

  it("acceptance criteria scenario — right-click at (viewportWidth-10, viewportHeight-10)", () => {
    // The menu must be fully inside the viewport with ≥4 px clearance.
    const x = VW - 10;
    const y = VH - 10;
    const pos = placeAtCursor({
      x,
      y,
      menuWidth: MENU_W,
      menuHeight: MENU_H,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    // Right and bottom edges must not escape the viewport.
    expect(pos.left + MENU_W + M).toBeLessThanOrEqual(VW);
    expect(pos.top + MENU_H + M).toBeLessThanOrEqual(VH);
    // Left and top must respect the margin.
    expect(pos.left).toBeGreaterThanOrEqual(M);
    expect(pos.top).toBeGreaterThanOrEqual(M);
  });

  it("exact margin boundary — cursor exactly at viewportWidth-menuWidth-margin stays put", () => {
    // This is the tightest valid position without clamping.
    const x = VW - MENU_W - M;
    const pos = placeAtCursor({
      x,
      y: 100,
      menuWidth: MENU_W,
      menuHeight: MENU_H,
      viewportWidth: VW,
      viewportHeight: VH,
    });
    expect(pos.left).toBe(x);
  });
});
