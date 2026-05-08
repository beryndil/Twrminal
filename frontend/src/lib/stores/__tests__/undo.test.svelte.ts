/**
 * Unit tests for :mod:`stores/undo.svelte.ts` — general-purpose undo store.
 *
 * Acceptance criteria covered (gap-cycle-05-002):
 * - Store push + auto-dismiss timeout (``windowMs`` / ``DEFAULT_UNDO_WINDOW_MS``).
 * - Undo button click invokes ``inverse`` and dismisses the entry.
 * - Stack cap drops the oldest entry when UNDO_STACK_CAP is exceeded.
 * - Archive flow end-to-end (mocked): push → stack non-empty → dismiss → stack empty.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_UNDO_WINDOW_MS, UNDO_STACK_CAP, _resetForTests, undoStore } from "../undo.svelte";

beforeEach(() => {
  _resetForTests();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// push — basic state
// ---------------------------------------------------------------------------

describe("undoStore.push", () => {
  it("adds an entry to the stack", () => {
    undoStore.push({ message: "Session archived", inverse: vi.fn() });
    expect(undoStore.stack.length).toBe(1);
    expect(undoStore.stack[0].message).toBe("Session archived");
  });

  it("most-recent entry is at index 0", () => {
    undoStore.push({ message: "First", inverse: vi.fn() });
    undoStore.push({ message: "Second", inverse: vi.fn() });
    expect(undoStore.stack[0].message).toBe("Second");
    expect(undoStore.stack[1].message).toBe("First");
  });

  it("uses DEFAULT_UNDO_WINDOW_MS when windowMs is omitted", () => {
    undoStore.push({ message: "x", inverse: vi.fn() });
    expect(undoStore.stack[0].windowMs).toBe(DEFAULT_UNDO_WINDOW_MS);
  });

  it("honours a custom windowMs", () => {
    undoStore.push({ message: "x", inverse: vi.fn(), windowMs: 2_000 });
    expect(undoStore.stack[0].windowMs).toBe(2_000);
  });
});

// ---------------------------------------------------------------------------
// Auto-dismiss timer
// ---------------------------------------------------------------------------

describe("auto-dismiss timer", () => {
  it("removes the entry after windowMs elapses", () => {
    undoStore.push({ message: "Session archived", inverse: vi.fn(), windowMs: 5_000 });
    expect(undoStore.stack.length).toBe(1);

    vi.advanceTimersByTime(5_000);

    expect(undoStore.stack.length).toBe(0);
  });

  it("does NOT remove the entry before windowMs elapses", () => {
    undoStore.push({ message: "Session archived", inverse: vi.fn(), windowMs: 5_000 });
    vi.advanceTimersByTime(4_999);
    expect(undoStore.stack.length).toBe(1);
  });

  it("restarts the timer when a new entry is pushed (top entry timer wins)", () => {
    undoStore.push({ message: "First", inverse: vi.fn(), windowMs: 10_000 });
    // Advance 4 s — first entry still alive.
    vi.advanceTimersByTime(4_000);
    expect(undoStore.stack.length).toBe(1);

    // Push a second entry with a shorter window.
    undoStore.push({ message: "Second", inverse: vi.fn(), windowMs: 3_000 });
    expect(undoStore.stack.length).toBe(2);

    // 3 s later: the new top (Second) auto-dismisses.
    vi.advanceTimersByTime(3_000);
    expect(undoStore.stack.length).toBe(1);
    expect(undoStore.stack[0].message).toBe("First");

    // The old first entry is now the top; its timer restarts from here.
    vi.advanceTimersByTime(10_000);
    expect(undoStore.stack.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Stack cap
// ---------------------------------------------------------------------------

describe("stack cap (UNDO_STACK_CAP = 3)", () => {
  it("does not exceed the cap when more entries are pushed", () => {
    for (let i = 0; i < UNDO_STACK_CAP + 2; i += 1) {
      undoStore.push({ message: `Entry ${i}`, inverse: vi.fn() });
    }
    expect(undoStore.stack.length).toBe(UNDO_STACK_CAP);
  });

  it("drops the oldest (highest-index) entry when at cap", () => {
    undoStore.push({ message: "A", inverse: vi.fn() });
    undoStore.push({ message: "B", inverse: vi.fn() });
    undoStore.push({ message: "C", inverse: vi.fn() }); // stack full: C B A
    undoStore.push({ message: "D", inverse: vi.fn() }); // evicts A → D C B

    const messages = undoStore.stack.map((e) => e.message);
    expect(messages).toEqual(["D", "C", "B"]);
  });
});

// ---------------------------------------------------------------------------
// dismiss
// ---------------------------------------------------------------------------

describe("undoStore.dismiss", () => {
  it("removes the matching entry by id", () => {
    undoStore.push({ message: "X", inverse: vi.fn() });
    const { id } = undoStore.stack[0];
    undoStore.dismiss(id);
    expect(undoStore.stack.length).toBe(0);
  });

  it("is a no-op for an unknown id", () => {
    undoStore.push({ message: "X", inverse: vi.fn() });
    undoStore.dismiss("nonexistent-id");
    expect(undoStore.stack.length).toBe(1);
  });

  it("starts the timer for the next entry after the top is dismissed", () => {
    undoStore.push({ message: "First", inverse: vi.fn(), windowMs: 5_000 });
    undoStore.push({ message: "Second", inverse: vi.fn(), windowMs: 99_999 });

    // Dismiss the top (Second) manually — First should now auto-dismiss in 5 s.
    undoStore.dismiss(undoStore.stack[0].id);
    expect(undoStore.stack[0].message).toBe("First");

    vi.advanceTimersByTime(5_000);
    expect(undoStore.stack.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// inverse() invocation
// ---------------------------------------------------------------------------

describe("inverse() invocation", () => {
  it("inverse is retained on the entry and is callable", async () => {
    const inverseFn = vi.fn().mockResolvedValue(undefined);
    undoStore.push({ message: "Session archived", inverse: inverseFn });

    const { inverse } = undoStore.stack[0];
    await inverse();

    expect(inverseFn).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// Archive flow end-to-end (mocked API)
// ---------------------------------------------------------------------------

describe("archive flow end-to-end", () => {
  it("push → stack non-empty; after dismiss → stack empty", () => {
    const reopenMock = vi.fn().mockResolvedValue(undefined);

    // Simulate what SessionRow.svelte does after closeSession() resolves.
    undoStore.push({
      message: "Session archived",
      inverse: reopenMock,
    });

    expect(undoStore.stack.length).toBe(1);
    expect(undoStore.stack[0].message).toBe("Session archived");

    // Simulate the user clicking Dismiss.
    undoStore.dismiss(undoStore.stack[0].id);
    expect(undoStore.stack.length).toBe(0);
  });

  it("auto-dismisses after the default window", () => {
    undoStore.push({
      message: "Session archived",
      inverse: vi.fn().mockResolvedValue(undefined),
    });

    vi.advanceTimersByTime(DEFAULT_UNDO_WINDOW_MS);
    expect(undoStore.stack.length).toBe(0);
  });
});
