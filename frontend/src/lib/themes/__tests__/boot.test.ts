/**
 * Unit tests for the no-flash theme boot script.
 *
 * :func:`runBootScript` mirrors the inline IIFE in
 * :file:`src/app.html` exactly. Testing it here verifies the
 * cold-load flow (localStorage seeded → correct data-theme + meta-color
 * written before any module loads) without needing a real browser.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  THEME_COLOR_HEX,
  THEME_DATA_ATTR_NAME,
  THEME_EVERGREEN,
  THEME_META_NAME,
  THEME_MIDNIGHT_GLASS,
  THEME_PAPER_LIGHT,
  THEME_STORAGE_KEY,
} from "../../config";
import { BOOT_FALLBACK_HEX, BOOT_FALLBACK_THEME, BOOT_THEME_HEX, runBootScript } from "../boot";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function seedStorage(theme: string): void {
  window.localStorage.setItem(THEME_STORAGE_KEY, theme);
}

function getDataTheme(): string | null {
  return document.documentElement.getAttribute(THEME_DATA_ATTR_NAME);
}

function getMetaColor(): string | null {
  return (
    document.querySelector<HTMLMetaElement>(`meta[name="${THEME_META_NAME}"]`)?.content ?? null
  );
}

function setMatchMedia(matches: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    () =>
      ({
        matches,
        media: "(prefers-color-scheme: light)",
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
}

beforeEach(() => {
  // Start each test with no stored theme + a clean DOM state matching
  // the static defaults in app.html (data-theme="evergreen", no meta tag).
  window.localStorage.clear();
  document.documentElement.removeAttribute(THEME_DATA_ATTR_NAME);
  document.querySelectorAll(`meta[name="${THEME_META_NAME}"]`).forEach((m) => m.remove());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// BOOT_THEME_HEX literal parity guard
// ---------------------------------------------------------------------------

describe("BOOT_THEME_HEX literal parity", () => {
  it("mirrors THEME_COLOR_HEX exactly — every runtime key is present with the same hex", () => {
    for (const [theme, hex] of Object.entries(THEME_COLOR_HEX)) {
      expect(BOOT_THEME_HEX[theme]).toBe(hex);
    }
  });

  it("contains no extra keys beyond THEME_COLOR_HEX", () => {
    const runtimeKeys = new Set(Object.keys(THEME_COLOR_HEX));
    for (const key of Object.keys(BOOT_THEME_HEX)) {
      expect(runtimeKeys.has(key)).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// Cold-load flow — localStorage seeded
// ---------------------------------------------------------------------------

describe("cold-load: localStorage seeded", () => {
  it("writes data-theme='paper-light' when localStorage holds paper-light", () => {
    seedStorage(THEME_PAPER_LIGHT);
    runBootScript();
    expect(getDataTheme()).toBe(THEME_PAPER_LIGHT);
  });

  it("writes the paper-light meta-color hex when localStorage holds paper-light", () => {
    seedStorage(THEME_PAPER_LIGHT);
    runBootScript();
    expect(getMetaColor()).toBe(THEME_COLOR_HEX[THEME_PAPER_LIGHT]);
  });

  it("writes data-theme='midnight-glass' and its hex when seeded with midnight-glass", () => {
    seedStorage(THEME_MIDNIGHT_GLASS);
    runBootScript();
    expect(getDataTheme()).toBe(THEME_MIDNIGHT_GLASS);
    expect(getMetaColor()).toBe(THEME_COLOR_HEX[THEME_MIDNIGHT_GLASS]);
  });

  it("writes data-theme='evergreen' and its hex when seeded with evergreen", () => {
    seedStorage(THEME_EVERGREEN);
    runBootScript();
    expect(getDataTheme()).toBe(THEME_EVERGREEN);
    expect(getMetaColor()).toBe(THEME_COLOR_HEX[THEME_EVERGREEN]);
  });
});

// ---------------------------------------------------------------------------
// Cold-load flow — no localStorage value (OS fallback)
// ---------------------------------------------------------------------------

describe("cold-load: no stored theme", () => {
  it("applies paper-light when OS reports a light scheme", () => {
    setMatchMedia(true);
    runBootScript();
    expect(getDataTheme()).toBe(THEME_PAPER_LIGHT);
    expect(getMetaColor()).toBe(THEME_COLOR_HEX[THEME_PAPER_LIGHT]);
  });

  it("applies evergreen when OS reports a dark scheme", () => {
    setMatchMedia(false);
    runBootScript();
    expect(getDataTheme()).toBe(THEME_EVERGREEN);
    expect(getMetaColor()).toBe(THEME_COLOR_HEX[THEME_EVERGREEN]);
  });
});

// ---------------------------------------------------------------------------
// Removed / unknown stored theme
// ---------------------------------------------------------------------------

describe("cold-load: invalid stored theme (removed theme branch)", () => {
  it("falls back to evergreen when the stored value is not in the map", () => {
    seedStorage("old-removed-theme");
    runBootScript();
    expect(getDataTheme()).toBe(BOOT_FALLBACK_THEME);
    expect(getMetaColor()).toBe(BOOT_FALLBACK_HEX);
  });
});

// ---------------------------------------------------------------------------
// Failure modes — never throws
// ---------------------------------------------------------------------------

describe("failure modes — boot script never throws", () => {
  it("falls back to evergreen when localStorage.getItem throws (private mode)", () => {
    const proto = Object.getPrototypeOf(window.localStorage) as { getItem: () => string | null };
    const original = proto.getItem;
    proto.getItem = () => {
      throw new Error("SecurityError");
    };
    try {
      expect(() => runBootScript()).not.toThrow();
      // DOM should stay at fallback (not set by a failed run).
      // The test starts with no data-theme attribute; after a failed run
      // the fallback is still applied if the outer try succeeded past the
      // localStorage call. Here the localStorage throw causes the inner
      // try to catch, so theme/hex stay at FALLBACK — then the outer
      // try still writes them.
      expect(getDataTheme()).toBe(BOOT_FALLBACK_THEME);
      expect(getMetaColor()).toBe(BOOT_FALLBACK_HEX);
    } finally {
      proto.getItem = original;
    }
  });

  it("falls back to evergreen when matchMedia throws", () => {
    // No stored theme → tries OS fallback → matchMedia throws.
    vi.stubGlobal("matchMedia", () => {
      throw new Error("not supported");
    });
    expect(() => runBootScript()).not.toThrow();
    expect(getDataTheme()).toBe(BOOT_FALLBACK_THEME);
    expect(getMetaColor()).toBe(BOOT_FALLBACK_HEX);
  });

  it("creates the meta tag if it is absent from the document", () => {
    // No meta[name="theme-color"] is present (beforeEach removed it).
    seedStorage(THEME_PAPER_LIGHT);
    runBootScript();
    const metas = document.querySelectorAll(`meta[name="${THEME_META_NAME}"]`);
    expect(metas).toHaveLength(1);
    expect(metas[0]?.getAttribute("content")).toBe(THEME_COLOR_HEX[THEME_PAPER_LIGHT]);
  });

  it("updates an existing meta tag in place without duplicating it", () => {
    const existing = document.createElement("meta");
    existing.setAttribute("name", THEME_META_NAME);
    existing.setAttribute("content", "#000000");
    document.head.appendChild(existing);

    seedStorage(THEME_MIDNIGHT_GLASS);
    runBootScript();
    const metas = document.querySelectorAll(`meta[name="${THEME_META_NAME}"]`);
    expect(metas).toHaveLength(1);
    expect(existing.getAttribute("content")).toBe(THEME_COLOR_HEX[THEME_MIDNIGHT_GLASS]);
  });
});
