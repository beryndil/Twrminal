/**
 * Unit tests for ``src/lib/utils/motion.ts`` (gap-cycle-14-001).
 *
 * Acceptance criteria covered:
 *
 * 1. ``prefersReducedMotion`` returns ``false`` when ``matchMedia`` is absent
 *    (SSR / jsdom without polyfill).
 * 2. ``prefersReducedMotion`` returns ``false`` when
 *    ``matchMedia("(prefers-reduced-motion: reduce)").matches`` is ``false``.
 * 3. ``prefersReducedMotion`` returns ``true`` when
 *    ``matchMedia("(prefers-reduced-motion: reduce)").matches`` is ``true``.
 * 4. ``scrollBehavior`` returns ``"smooth"`` when reduced motion is off.
 * 5. ``scrollBehavior`` returns ``"auto"`` when reduced motion is on.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { prefersReducedMotion, scrollBehavior } from "../motion";

// ---------------------------------------------------------------------------
// Helpers — stub window.matchMedia
// ---------------------------------------------------------------------------

function stubMatchMedia(matches: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockReturnValue({ matches }),
  });
}

function clearMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: undefined,
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  clearMatchMedia();
});

// ---------------------------------------------------------------------------
// 1. prefersReducedMotion — no matchMedia API
// ---------------------------------------------------------------------------

describe("prefersReducedMotion — matchMedia absent", () => {
  it("returns false when window.matchMedia is undefined", () => {
    clearMatchMedia();
    expect(prefersReducedMotion()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 2. prefersReducedMotion — matches false
// ---------------------------------------------------------------------------

describe("prefersReducedMotion — reduce motion off", () => {
  it("returns false when matchMedia reports matches: false", () => {
    stubMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 3. prefersReducedMotion — matches true
// ---------------------------------------------------------------------------

describe("prefersReducedMotion — reduce motion on", () => {
  it("returns true when matchMedia reports matches: true", () => {
    stubMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 4. scrollBehavior — returns "smooth" when reduced motion is off
// ---------------------------------------------------------------------------

describe("scrollBehavior — reduce motion off", () => {
  it("returns 'smooth' when matchMedia reports matches: false", () => {
    stubMatchMedia(false);
    expect(scrollBehavior()).toBe("smooth");
  });

  it("returns 'smooth' when matchMedia is absent", () => {
    clearMatchMedia();
    expect(scrollBehavior()).toBe("smooth");
  });
});

// ---------------------------------------------------------------------------
// 5. scrollBehavior — returns "auto" when reduced motion is on
// ---------------------------------------------------------------------------

describe("scrollBehavior — reduce motion on", () => {
  it("returns 'auto' when matchMedia reports matches: true", () => {
    stubMatchMedia(true);
    expect(scrollBehavior()).toBe("auto");
  });
});
