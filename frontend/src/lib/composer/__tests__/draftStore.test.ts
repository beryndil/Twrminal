/**
 * Unit tests for :mod:`composer/draftStore.svelte` — load, save, clear,
 * and localStorage failure-mode degradation.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COMPOSER_DRAFT_KEY_PREFIX } from "../../config";
import { clearDraft, loadDraft, saveDraft } from "../draftStore.svelte";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function key(sessionId: string): string {
  return `${COMPOSER_DRAFT_KEY_PREFIX}${sessionId}`;
}

describe("loadDraft", () => {
  it("returns empty string when no draft is stored", () => {
    expect(loadDraft("ses_a")).toBe("");
  });

  it("returns the stored draft when one exists", () => {
    window.localStorage.setItem(key("ses_b"), "hello world");
    expect(loadDraft("ses_b")).toBe("hello world");
  });

  it("returns empty string on localStorage read error", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementationOnce(() => {
      throw new Error("quota");
    });
    expect(loadDraft("ses_c")).toBe("");
  });
});

describe("saveDraft", () => {
  it("writes the draft to localStorage", () => {
    saveDraft("ses_a", "my draft");
    expect(window.localStorage.getItem(key("ses_a"))).toBe("my draft");
  });

  it("removes the key when saving an empty string", () => {
    window.localStorage.setItem(key("ses_a"), "stale");
    saveDraft("ses_a", "");
    expect(window.localStorage.getItem(key("ses_a"))).toBeNull();
  });

  it("does not throw on localStorage write error", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementationOnce(() => {
      throw new Error("quota");
    });
    expect(() => saveDraft("ses_a", "data")).not.toThrow();
  });

  it("does not throw on localStorage removeItem error", () => {
    vi.spyOn(window.localStorage, "removeItem").mockImplementationOnce(() => {
      throw new Error("security");
    });
    expect(() => saveDraft("ses_a", "")).not.toThrow();
  });
});

describe("clearDraft", () => {
  it("removes the stored draft", () => {
    window.localStorage.setItem(key("ses_a"), "pending");
    clearDraft("ses_a");
    expect(window.localStorage.getItem(key("ses_a"))).toBeNull();
  });

  it("is a no-op when no draft exists", () => {
    expect(() => clearDraft("ses_a")).not.toThrow();
  });
});

describe("isolation — different sessions have independent drafts", () => {
  it("saves and loads drafts per session without cross-contamination", () => {
    saveDraft("ses_1", "draft one");
    saveDraft("ses_2", "draft two");
    expect(loadDraft("ses_1")).toBe("draft one");
    expect(loadDraft("ses_2")).toBe("draft two");
    clearDraft("ses_1");
    expect(loadDraft("ses_1")).toBe("");
    expect(loadDraft("ses_2")).toBe("draft two");
  });
});
