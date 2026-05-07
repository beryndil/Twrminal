/**
 * Inspector store tests — pin the boot defaults, the imperative API,
 * the unknown-id ignore behaviour, and localStorage persistence
 * (gap-cycle-09-002).
 *
 * localStorage coverage:
 * 1. Default value is ``DEFAULT_INSPECTOR_TAB`` (no localStorage value set).
 * 2. ``setInspectorTab`` persists the chosen id to ``localStorage``.
 * 3. ``_resetForTests`` re-hydrates from localStorage (round-trip proof:
 *    "pick tab → reload → same tab active").
 * 4. An unknown persisted value falls back to ``DEFAULT_INSPECTOR_TAB``.
 * 5. ``localStorage`` read errors degrade silently to the default.
 * 6. ``localStorage`` write errors degrade silently — in-memory still flips.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_INSPECTOR_TAB,
  INSPECTOR_TAB_AGENT,
  INSPECTOR_TAB_CONTEXT,
  INSPECTOR_TAB_INSTRUCTIONS,
  INSPECTOR_TAB_ROUTING,
  INSPECTOR_TAB_STORAGE_KEY,
  type InspectorTabId,
} from "../../config";
import {
  _resetForTests,
  inspectorStore,
  setActiveSession,
  setInspectorTab,
} from "../inspector.svelte";

beforeEach(() => {
  window.localStorage.clear();
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("inspectorStore — boot defaults", () => {
  it("starts on the documented default tab", () => {
    expect(inspectorStore.activeTabId).toBe(DEFAULT_INSPECTOR_TAB);
    // Pin the default's identity so a future ``DEFAULT_INSPECTOR_TAB``
    // re-aliasing is caught here rather than as a UI regression.
    expect(DEFAULT_INSPECTOR_TAB).toBe(INSPECTOR_TAB_AGENT);
  });

  it("starts with no active session", () => {
    expect(inspectorStore.activeSessionId).toBeNull();
  });
});

describe("setInspectorTab", () => {
  it("switches the active tab to a known id", () => {
    setInspectorTab(INSPECTOR_TAB_CONTEXT);
    expect(inspectorStore.activeTabId).toBe(INSPECTOR_TAB_CONTEXT);
    setInspectorTab(INSPECTOR_TAB_INSTRUCTIONS);
    expect(inspectorStore.activeTabId).toBe(INSPECTOR_TAB_INSTRUCTIONS);
  });

  it("ignores ids outside the documented alphabet", () => {
    setInspectorTab(INSPECTOR_TAB_CONTEXT);
    // Cast through ``unknown`` rather than ``any`` — the cast is the
    // explicit defense-in-depth check for a stale persisted id.
    setInspectorTab("not-a-tab" as unknown as InspectorTabId);
    expect(inspectorStore.activeTabId).toBe(INSPECTOR_TAB_CONTEXT);
  });
});

describe("setActiveSession", () => {
  it("records the supplied session id", () => {
    setActiveSession("ses_a");
    expect(inspectorStore.activeSessionId).toBe("ses_a");
  });

  it("clears the active session when called with null", () => {
    setActiveSession("ses_a");
    setActiveSession(null);
    expect(inspectorStore.activeSessionId).toBeNull();
  });
});

describe("_resetForTests", () => {
  it("restores activeSessionId to null and re-hydrates activeTabId from localStorage", () => {
    setInspectorTab(INSPECTOR_TAB_INSTRUCTIONS);
    setActiveSession("ses_a");
    // localStorage was written by setInspectorTab above; clear it so we
    // confirm the reset lands on the default, not the written value.
    window.localStorage.clear();
    _resetForTests();
    expect(inspectorStore.activeTabId).toBe(DEFAULT_INSPECTOR_TAB);
    expect(inspectorStore.activeSessionId).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// localStorage persistence (gap-cycle-09-002)
// ---------------------------------------------------------------------------

describe("localStorage — setInspectorTab persists", () => {
  it("writes the tab id to INSPECTOR_TAB_STORAGE_KEY on every call", () => {
    setInspectorTab(INSPECTOR_TAB_ROUTING);
    expect(window.localStorage.getItem(INSPECTOR_TAB_STORAGE_KEY)).toBe(INSPECTOR_TAB_ROUTING);
    setInspectorTab(INSPECTOR_TAB_CONTEXT);
    expect(window.localStorage.getItem(INSPECTOR_TAB_STORAGE_KEY)).toBe(INSPECTOR_TAB_CONTEXT);
  });
});

describe("localStorage — round-trip (reload simulation)", () => {
  it("re-hydrates a previously persisted tab id via _resetForTests", () => {
    // Pick a non-default tab — this writes to localStorage.
    setInspectorTab(INSPECTOR_TAB_ROUTING);

    // Simulate a page reload: _resetForTests() mirrors the module initialiser,
    // calling loadTabPref() which reads the stored value.
    _resetForTests();
    expect(inspectorStore.activeTabId).toBe(INSPECTOR_TAB_ROUTING);
  });

  it("re-hydrates from a key seeded before _resetForTests", () => {
    window.localStorage.setItem(INSPECTOR_TAB_STORAGE_KEY, INSPECTOR_TAB_INSTRUCTIONS);
    _resetForTests();
    expect(inspectorStore.activeTabId).toBe(INSPECTOR_TAB_INSTRUCTIONS);
  });
});

describe("localStorage — unknown / malformed persisted value", () => {
  it("falls back to DEFAULT_INSPECTOR_TAB for an unrecognised stored string", () => {
    window.localStorage.setItem(INSPECTOR_TAB_STORAGE_KEY, "not-a-real-tab");
    _resetForTests();
    expect(inspectorStore.activeTabId).toBe(DEFAULT_INSPECTOR_TAB);
  });

  it("falls back to DEFAULT_INSPECTOR_TAB when the stored value is an empty string", () => {
    window.localStorage.setItem(INSPECTOR_TAB_STORAGE_KEY, "");
    _resetForTests();
    expect(inspectorStore.activeTabId).toBe(DEFAULT_INSPECTOR_TAB);
  });
});

describe("localStorage — read error degrades silently", () => {
  it("does not throw when localStorage.getItem throws; falls back to default", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementationOnce(() => {
      throw new Error("SecurityError");
    });
    expect(() => _resetForTests()).not.toThrow();
    expect(inspectorStore.activeTabId).toBe(DEFAULT_INSPECTOR_TAB);
  });
});

describe("localStorage — write error degrades silently", () => {
  it("does not throw when localStorage.setItem throws", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementationOnce(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => setInspectorTab(INSPECTOR_TAB_CONTEXT)).not.toThrow();
    // In-memory state still updated even though persist failed.
    expect(inspectorStore.activeTabId).toBe(INSPECTOR_TAB_CONTEXT);
  });
});
