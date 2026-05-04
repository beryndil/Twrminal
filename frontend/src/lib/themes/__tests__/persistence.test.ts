/**
 * Unit tests for theme persistence + OS-fallback resolution.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  THEME_DEFAULT,
  THEME_EVERGREEN,
  THEME_MIDNIGHT_GLASS,
  THEME_PAPER_LIGHT,
  THEME_STORAGE_KEY,
} from "../../config";
import {
  isThemeId,
  loadStoredTheme,
  resolveBootTheme,
  resolveOsFallbackTheme,
  saveStoredTheme,
} from "../persistence";

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
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("isThemeId", () => {
  it("accepts every theme in the alphabet", () => {
    expect(isThemeId(THEME_EVERGREEN)).toBe(true);
    expect(isThemeId(THEME_MIDNIGHT_GLASS)).toBe(true);
    expect(isThemeId(THEME_DEFAULT)).toBe(true);
    expect(isThemeId(THEME_PAPER_LIGHT)).toBe(true);
  });

  it("rejects non-strings, empty, and unknown ids", () => {
    expect(isThemeId(null)).toBe(false);
    expect(isThemeId(undefined)).toBe(false);
    expect(isThemeId(42)).toBe(false);
    expect(isThemeId("")).toBe(false);
    expect(isThemeId("removed-theme")).toBe(false);
  });
});

describe("resolveOsFallbackTheme", () => {
  it("returns paper-light when the OS reports a light scheme", () => {
    setMatchMedia(true);
    expect(resolveOsFallbackTheme()).toBe(THEME_PAPER_LIGHT);
  });

  it("returns evergreen otherwise", () => {
    setMatchMedia(false);
    expect(resolveOsFallbackTheme()).toBe(THEME_EVERGREEN);
  });
});

describe("loadStoredTheme + saveStoredTheme", () => {
  it("round-trips a valid theme id", () => {
    expect(saveStoredTheme(THEME_DEFAULT)).toBe(true);
    expect(loadStoredTheme()).toBe(THEME_DEFAULT);
  });

  it("returns null when no theme is persisted", () => {
    expect(loadStoredTheme()).toBe(null);
  });

  it("returns null when the persisted value is not in the alphabet (removed-theme branch)", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "old-removed-theme");
    expect(loadStoredTheme()).toBe(null);
  });

  it("returns false on storage write failure (quota / private mode)", () => {
    const proto = Object.getPrototypeOf(window.localStorage) as { setItem: () => void };
    const original = proto.setItem;
    proto.setItem = () => {
      throw new Error("quota");
    };
    try {
      expect(saveStoredTheme(THEME_PAPER_LIGHT)).toBe(false);
    } finally {
      proto.setItem = original;
    }
  });
});

describe("resolveBootTheme", () => {
  it("prefers the persisted value over the OS fallback", () => {
    setMatchMedia(true); // light
    saveStoredTheme(THEME_MIDNIGHT_GLASS);
    expect(resolveBootTheme()).toBe(THEME_MIDNIGHT_GLASS);
  });

  it("falls back to OS scheme when no value is persisted", () => {
    setMatchMedia(true);
    expect(resolveBootTheme()).toBe(THEME_PAPER_LIGHT);
  });

  it("persists the OS fallback on first boot so subsequent loads skip the fallback", () => {
    setMatchMedia(true); // light
    // No stored value yet.
    expect(loadStoredTheme()).toBeNull();
    resolveBootTheme();
    // After first boot the OS choice is written to storage.
    expect(loadStoredTheme()).toBe(THEME_PAPER_LIGHT);
  });

  it("returns evergreen OS fallback when OS scheme is dark and nothing is persisted", () => {
    setMatchMedia(false);
    expect(resolveBootTheme()).toBe(THEME_EVERGREEN);
    expect(loadStoredTheme()).toBe(THEME_EVERGREEN);
  });
});
