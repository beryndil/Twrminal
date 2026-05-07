/**
 * Unit tests for ``src/lib/utils/datetime.ts`` (gap-cycle-07-006).
 *
 * Covers:
 * 1. ``formatBuildMtime(null)`` returns ``"dev build"``.
 * 2. ``formatBuildMtime(NaN)`` returns ``"dev build"``.
 * 3. ``formatBuildMtime(±Infinity)`` returns ``"dev build"``.
 * 4. ``formatBuildMtime`` with a valid timestamp returns a non-empty string.
 * 5. ``formatAbsolute`` passes ``timeZone`` to ``toLocaleString`` when the
 *    store has an active timezone.
 * 6. ``formatAbsolute`` omits ``timeZone`` when the store is in Auto (null).
 * 7. ``formatAbsolute`` caller-supplied ``timeZone`` opts take precedence
 *    over the store value.
 * 8. ``formatAbsolute`` accepts Date objects, ISO strings, and ms numbers.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { _resetForTests, setTimezone } from "../../stores/displaySettings.svelte";
import { formatAbsolute, formatBuildMtime } from "../datetime";

beforeEach(() => {
  window.localStorage.clear();
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1–3. formatBuildMtime — null / non-finite guards
// ---------------------------------------------------------------------------

describe("formatBuildMtime — null / non-finite", () => {
  it("returns 'dev build' for null", () => {
    expect(formatBuildMtime(null)).toBe("dev build");
  });

  it("returns 'dev build' for NaN", () => {
    expect(formatBuildMtime(NaN)).toBe("dev build");
  });

  it("returns 'dev build' for +Infinity", () => {
    expect(formatBuildMtime(Infinity)).toBe("dev build");
  });

  it("returns 'dev build' for -Infinity", () => {
    expect(formatBuildMtime(-Infinity)).toBe("dev build");
  });
});

// ---------------------------------------------------------------------------
// 4. formatBuildMtime — valid timestamp
// ---------------------------------------------------------------------------

describe("formatBuildMtime — valid timestamp", () => {
  it("returns a non-empty string for a valid Unix-seconds timestamp", () => {
    // 2026-01-15T12:00:00Z as Unix seconds.
    const ts = 1768478400;
    const result = formatBuildMtime(ts);
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
    expect(result).not.toBe("dev build");
  });
});

// ---------------------------------------------------------------------------
// 5. formatAbsolute — active timezone injected into toLocaleString
// ---------------------------------------------------------------------------

describe("formatAbsolute — active timezone", () => {
  it("passes timeZone to toLocaleString when store has a non-null timezone", () => {
    setTimezone("UTC");
    const spy = vi.spyOn(Date.prototype, "toLocaleString");
    formatAbsolute(new Date("2024-01-01T00:00:00Z"));
    expect(spy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ timeZone: "UTC" }),
    );
  });

  it("passes the chosen IANA zone, not a hardcoded value", () => {
    setTimezone("Asia/Tokyo");
    const spy = vi.spyOn(Date.prototype, "toLocaleString");
    formatAbsolute(new Date("2024-06-01T00:00:00Z"));
    expect(spy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ timeZone: "Asia/Tokyo" }),
    );
  });
});

// ---------------------------------------------------------------------------
// 6. formatAbsolute — Auto (null) omits timeZone
// ---------------------------------------------------------------------------

describe("formatAbsolute — Auto / null timezone", () => {
  it("omits timeZone from the options when store is null (Auto)", () => {
    // _resetForTests already set timezone to null.
    const spy = vi.spyOn(Date.prototype, "toLocaleString");
    formatAbsolute(new Date("2024-01-01T00:00:00Z"));
    const calls = spy.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const opts = calls[0][1] as Intl.DateTimeFormatOptions | undefined;
    // Either opts is undefined/empty or does not have a timeZone key.
    expect(opts?.timeZone).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 7. formatAbsolute — caller opts.timeZone takes precedence over store
// ---------------------------------------------------------------------------

describe("formatAbsolute — caller timeZone overrides store", () => {
  it("uses caller-supplied timeZone over the store value", () => {
    setTimezone("UTC");
    const spy = vi.spyOn(Date.prototype, "toLocaleString");
    formatAbsolute(new Date("2024-01-01T00:00:00Z"), { timeZone: "America/New_York" });
    expect(spy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ timeZone: "America/New_York" }),
    );
  });
});

// ---------------------------------------------------------------------------
// 8. formatAbsolute — accepts Date, ISO string, and ms number
// ---------------------------------------------------------------------------

describe("formatAbsolute — input types", () => {
  it("accepts a Date object", () => {
    expect(() => formatAbsolute(new Date("2024-01-01T00:00:00Z"))).not.toThrow();
  });

  it("accepts an ISO string", () => {
    expect(() => formatAbsolute("2024-01-01T00:00:00Z")).not.toThrow();
  });

  it("accepts a Unix-ms number", () => {
    expect(() => formatAbsolute(1704067200000)).not.toThrow();
  });

  it("produces consistent output across input types for the same moment", () => {
    const isoString = "2024-06-15T12:00:00Z";
    const ms = new Date(isoString).getTime();
    const dateObj = new Date(isoString);
    expect(formatAbsolute(isoString)).toBe(formatAbsolute(ms));
    expect(formatAbsolute(isoString)).toBe(formatAbsolute(dateObj));
  });
});
