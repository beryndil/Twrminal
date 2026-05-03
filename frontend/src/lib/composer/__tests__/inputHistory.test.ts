/**
 * Unit tests for :class:`InputHistory` — Up/Down navigation, dedup,
 * savedDraft restore, and session-reset behaviour.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { InputHistory } from "../inputHistory";

let h: InputHistory;

beforeEach(() => {
  h = new InputHistory();
});

describe("InputHistory — push", () => {
  it("ignores empty and whitespace-only strings", () => {
    h.push("");
    h.push("   ");
    h.push("\n");
    expect(h.up("")).toBeNull();
  });

  it("deduplicates consecutive identical sends", () => {
    h.push("hello");
    h.push("hello");
    // Only one entry — up returns it, second up clamps.
    expect(h.up("")).toBe("hello");
    expect(h.up("hello")).toBe("hello");
  });

  it("does NOT deduplicate non-consecutive repeats", () => {
    h.push("a");
    h.push("b");
    h.push("a");
    // ring: ["a", "b", "a"]
    h.up(""); // → "a" (index 2)
    h.up("a"); // → "b" (index 1)
    expect(h.up("b")).toBe("a"); // index 0
  });

  it("resets cursor after push so next up starts from newest", () => {
    h.push("first");
    h.up(""); // enter history
    h.push("second"); // cursor reset
    expect(h.up("")).toBe("second");
  });
});

describe("InputHistory — up", () => {
  it("returns null when history is empty", () => {
    expect(h.up("anything")).toBeNull();
  });

  it("returns the most-recent entry on the first press", () => {
    h.push("one");
    h.push("two");
    expect(h.up("draft")).toBe("two");
  });

  it("walks back on each successive press", () => {
    h.push("first");
    h.push("second");
    h.push("third");
    expect(h.up("live")).toBe("third");
    expect(h.up("third")).toBe("second");
    expect(h.up("second")).toBe("first");
  });

  it("clamps at the oldest entry", () => {
    h.push("only");
    h.up("live");
    expect(h.up("only")).toBe("only");
    expect(h.up("only")).toBe("only");
  });

  it("saves the live draft and restores it on down past the newest entry", () => {
    h.push("older");
    h.push("sent");
    h.up("my live draft"); // cursor → "sent" (index 1, newest)
    h.up("sent"); // cursor → "older" (index 0)
    expect(h.down()).toBe("sent"); // forward one step
    expect(h.down()).toBe("my live draft"); // past newest — live draft restored
  });
});

describe("InputHistory — down", () => {
  it("returns savedDraft immediately if not in history mode", () => {
    expect(h.down()).toBe("");
  });

  it("walks forward after walking back", () => {
    h.push("alpha");
    h.push("beta");
    h.up("live"); // cursor → "beta"
    h.up("beta"); // cursor → "alpha"
    expect(h.down()).toBe("beta");
    expect(h.down()).toBe("live"); // past newest — restores live draft
  });

  it("after restoring live draft, inHistory is false", () => {
    h.push("msg");
    h.up("live");
    h.down(); // restore
    expect(h.inHistory).toBe(false);
  });

  it("subsequent down calls after restoration return empty string (savedDraft cleared on exit)", () => {
    h.push("msg");
    h.up("live"); // savedDraft = "live"
    h.down(); // exits history; savedDraft cleared, returns "live"
    // cursor is now -1, savedDraft was cleared on exit.
    expect(h.down()).toBe("");
  });
});

describe("InputHistory — inHistory", () => {
  it("is false when no navigation has occurred", () => {
    expect(h.inHistory).toBe(false);
  });

  it("is true after the first up press (with entries)", () => {
    h.push("x");
    h.up("");
    expect(h.inHistory).toBe(true);
  });

  it("is false after down past the newest entry", () => {
    h.push("x");
    h.up("draft");
    h.down();
    expect(h.inHistory).toBe(false);
  });
});

describe("InputHistory — reset", () => {
  it("exits history mode without clearing entries", () => {
    h.push("a");
    h.push("b");
    h.up("live");
    h.reset();
    expect(h.inHistory).toBe(false);
    // Entries still present — up works again.
    expect(h.up("")).toBe("b");
  });

  it("savedDraft is cleared on reset", () => {
    h.push("a");
    h.up("original draft");
    h.reset();
    // Enter history again with an empty current draft.
    h.up("");
    // down past newest should restore the empty draft, not "original draft".
    h.down();
    expect(h.down()).toBe("");
  });
});

describe("InputHistory — clear", () => {
  it("removes all entries and resets the cursor", () => {
    h.push("a");
    h.push("b");
    h.clear();
    expect(h.up("")).toBeNull();
    expect(h.inHistory).toBe(false);
  });
});
