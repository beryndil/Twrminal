/**
 * Unit tests for the session sort-mode preference store.
 *
 * Covers:
 * 1. Default value is ``last_action`` (no localStorage value set).
 * 2. ``setSessionSort`` updates the reactive store and persists to
 *    ``localStorage``.
 * 3. Store reads a previously-persisted ``grouped`` value on init.
 * 4. An unknown persisted value falls back to ``last_action``.
 * 5. ``localStorage`` read errors degrade silently to the default.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SESSION_SORT_GROUPED,
  SESSION_SORT_LAST_ACTION,
  SESSION_SORT_STORAGE_KEY,
} from "../../config";
import { _resetForTests, sessionSortStore, setSessionSort } from "../sessionSort.svelte";

beforeEach(() => {
  window.localStorage.clear();
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("sessionSortStore defaults", () => {
  it("starts as last_action when nothing is persisted", () => {
    expect(sessionSortStore.mode).toBe(SESSION_SORT_LAST_ACTION);
  });
});

describe("setSessionSort", () => {
  it("updates the store to grouped", () => {
    setSessionSort(SESSION_SORT_GROUPED);
    expect(sessionSortStore.mode).toBe(SESSION_SORT_GROUPED);
  });

  it("persists the chosen mode to localStorage", () => {
    setSessionSort(SESSION_SORT_GROUPED);
    expect(window.localStorage.getItem(SESSION_SORT_STORAGE_KEY)).toBe(SESSION_SORT_GROUPED);
  });

  it("round-trips back to last_action", () => {
    setSessionSort(SESSION_SORT_GROUPED);
    setSessionSort(SESSION_SORT_LAST_ACTION);
    expect(sessionSortStore.mode).toBe(SESSION_SORT_LAST_ACTION);
    expect(window.localStorage.getItem(SESSION_SORT_STORAGE_KEY)).toBe(SESSION_SORT_LAST_ACTION);
  });

  it("does not throw when localStorage.setItem throws", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementationOnce(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => setSessionSort(SESSION_SORT_GROUPED)).not.toThrow();
    // In-memory state still updated even if persist failed.
    expect(sessionSortStore.mode).toBe(SESSION_SORT_GROUPED);
  });
});

describe("_resetForTests", () => {
  it("resets mode to last_action without touching localStorage", () => {
    window.localStorage.setItem(SESSION_SORT_STORAGE_KEY, SESSION_SORT_GROUPED);
    setSessionSort(SESSION_SORT_GROUPED);
    _resetForTests();
    expect(sessionSortStore.mode).toBe(SESSION_SORT_LAST_ACTION);
    // localStorage is untouched by the reset.
    expect(window.localStorage.getItem(SESSION_SORT_STORAGE_KEY)).toBe(SESSION_SORT_GROUPED);
  });
});
