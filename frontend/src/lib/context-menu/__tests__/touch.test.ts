/**
 * Unit tests for the long-press FSM (reduceLongPress) and the longpress
 * Svelte action (gap-cycle-15-001).
 *
 * Four required acceptance-criteria cases:
 * (i)  reduceLongPress happy path — down → timer → fire (via longpress action).
 * (ii) Movement > 8 px cancels the long-press.
 * (iii) Pointer-up before the timer cancels.
 * (iv) pointerType !== 'touch' | 'pen' does not arm the FSM.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LONG_PRESS_IDLE, reduceLongPress, longpress, isCoarsePointer } from "../touch";

// ---------------------------------------------------------------------------
// reduceLongPress — pure FSM tests (no timers, no DOM)
// ---------------------------------------------------------------------------

describe("reduceLongPress", () => {
  describe("pointerdown", () => {
    it("(iv) mouse pointerType does not arm the FSM", () => {
      const next = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "mouse",
      });
      expect(next.phase).toBe("idle");
    });

    it("(iv) unknown pointerType does not arm the FSM", () => {
      const next = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "stylus-unknown",
      });
      expect(next.phase).toBe("idle");
    });

    it("touch pointerType arms the FSM and records start coords", () => {
      const next = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 120,
        y: 340,
        pointerType: "touch",
      });
      expect(next.phase).toBe("armed");
      expect(next.startX).toBe(120);
      expect(next.startY).toBe(340);
    });

    it("pen pointerType arms the FSM", () => {
      const next = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "pen",
      });
      expect(next.phase).toBe("armed");
    });

    it("a second pointerdown while already armed re-arms with new coords", () => {
      const armed = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "touch",
      });
      const rearmed = reduceLongPress(armed, {
        type: "pointerdown",
        x: 50,
        y: 60,
        pointerType: "touch",
      });
      expect(rearmed.phase).toBe("armed");
      expect(rearmed.startX).toBe(50);
      expect(rearmed.startY).toBe(60);
    });
  });

  describe("pointermove", () => {
    it("(ii) movement exactly at threshold (8 px) does NOT cancel", () => {
      const armed = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "touch",
      });
      // Exactly 8 px on the X axis — should stay armed.
      const next = reduceLongPress(armed, { type: "pointermove", x: 8, y: 0 });
      expect(next.phase).toBe("armed");
    });

    it("(ii) movement just above threshold (9 px) cancels", () => {
      const armed = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "touch",
      });
      const next = reduceLongPress(armed, { type: "pointermove", x: 9, y: 0 });
      expect(next.phase).toBe("idle");
    });

    it("(ii) diagonal movement > 8 px cancels", () => {
      const armed = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "touch",
      });
      // 6² + 6² = 72 → √72 ≈ 8.49 > 8 → should cancel.
      const next = reduceLongPress(armed, { type: "pointermove", x: 6, y: 6 });
      expect(next.phase).toBe("idle");
    });

    it("pointermove while idle is a no-op", () => {
      const next = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointermove",
        x: 100,
        y: 100,
      });
      expect(next).toBe(LONG_PRESS_IDLE);
    });

    it("custom thresholdPx override is respected", () => {
      const armed = reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "touch",
      });
      // Threshold set to 4 px; 5 px move should cancel.
      const next = reduceLongPress(armed, { type: "pointermove", x: 5, y: 0 }, { thresholdPx: 4 });
      expect(next.phase).toBe("idle");
    });
  });

  describe("(iii) cancellation events", () => {
    function armed(): ReturnType<typeof reduceLongPress> {
      return reduceLongPress(LONG_PRESS_IDLE, {
        type: "pointerdown",
        x: 0,
        y: 0,
        pointerType: "touch",
      });
    }

    it("pointerup while armed → idle", () => {
      expect(reduceLongPress(armed(), { type: "pointerup" }).phase).toBe("idle");
    });

    it("pointercancel while armed → idle", () => {
      expect(reduceLongPress(armed(), { type: "pointercancel" }).phase).toBe("idle");
    });

    it("pointerleave while armed → idle", () => {
      expect(reduceLongPress(armed(), { type: "pointerleave" }).phase).toBe("idle");
    });

    it("cancellation events while already idle are no-ops", () => {
      expect(reduceLongPress(LONG_PRESS_IDLE, { type: "pointerup" })).toBe(LONG_PRESS_IDLE);
      expect(reduceLongPress(LONG_PRESS_IDLE, { type: "pointercancel" })).toBe(LONG_PRESS_IDLE);
      expect(reduceLongPress(LONG_PRESS_IDLE, { type: "pointerleave" })).toBe(LONG_PRESS_IDLE);
    });
  });
});

// ---------------------------------------------------------------------------
// isCoarsePointer
// ---------------------------------------------------------------------------

describe("isCoarsePointer", () => {
  it("returns false when window.matchMedia is not configured (default jsdom)", () => {
    // jsdom does not implement matchMedia; our try/catch returns false.
    expect(isCoarsePointer()).toBe(false);
  });

  it("returns true when matchMedia reports (pointer: coarse)", () => {
    const restore = window.matchMedia;
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({ matches: query === "(pointer: coarse)" }),
    });
    expect(isCoarsePointer()).toBe(true);
    Object.defineProperty(window, "matchMedia", { writable: true, value: restore });
  });

  it("returns false when matchMedia reports (pointer: fine)", () => {
    const restore = window.matchMedia;
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (_query: string) => ({ matches: false }),
    });
    expect(isCoarsePointer()).toBe(false);
    Object.defineProperty(window, "matchMedia", { writable: true, value: restore });
  });
});

// ---------------------------------------------------------------------------
// longpress action — timer and event-wiring tests
// ---------------------------------------------------------------------------

describe("longpress action", () => {
  let node: HTMLDivElement;

  beforeEach(() => {
    vi.useFakeTimers();
    // Stub matchMedia to report coarse so longpress actually arms.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({ matches: query === "(pointer: coarse)" }),
    });
    node = document.createElement("div");
    document.body.appendChild(node);
  });

  afterEach(() => {
    node.remove();
    vi.useRealTimers();
    // Remove matchMedia stub — next test starts fresh.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: undefined,
    });
  });

  /** Dispatch a PointerEvent on node with the given init options. */
  function fire(type: string, init: Record<string, unknown> = {}): void {
    node.dispatchEvent(new PointerEvent(type, { bubbles: true, ...init }));
  }

  it("(i) happy path: fires onLongPress(x, y) exactly at 500 ms", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 100, clientY: 200, pointerType: "touch" });

    vi.advanceTimersByTime(499);
    expect(cb).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1); // 500 ms total
    expect(cb).toHaveBeenCalledOnce();
    expect(cb).toHaveBeenCalledWith(100, 200);

    destroy();
  });

  it("(i) pen pointerType also fires onLongPress", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 50, clientY: 50, pointerType: "pen" });
    vi.advanceTimersByTime(500);

    expect(cb).toHaveBeenCalledOnce();
    expect(cb).toHaveBeenCalledWith(50, 50);

    destroy();
  });

  it("(ii) movement > 8 px before timer cancels the long-press", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "touch" });
    fire("pointermove", { clientX: 9, clientY: 0 }); // > 8 px
    vi.advanceTimersByTime(500);

    expect(cb).not.toHaveBeenCalled();

    destroy();
  });

  it("(iii) pointerup before timer cancels the long-press", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "touch" });
    fire("pointerup");
    vi.advanceTimersByTime(500);

    expect(cb).not.toHaveBeenCalled();

    destroy();
  });

  it("(iii) pointercancel before timer cancels the long-press", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "touch" });
    fire("pointercancel");
    vi.advanceTimersByTime(500);

    expect(cb).not.toHaveBeenCalled();

    destroy();
  });

  it("(iii) pointerleave before timer cancels the long-press", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "touch" });
    fire("pointerleave");
    vi.advanceTimersByTime(500);

    expect(cb).not.toHaveBeenCalled();

    destroy();
  });

  it("(iv) mouse pointerType does not arm — no fire after 500 ms", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "mouse" });
    vi.advanceTimersByTime(500);

    expect(cb).not.toHaveBeenCalled();

    destroy();
  });

  it("destroy cleans up listeners and cancels any pending timer", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "touch" });
    destroy(); // destroys mid-arm

    vi.advanceTimersByTime(500);
    expect(cb).not.toHaveBeenCalled();
  });

  it("returns a no-op destroy when the pointer is fine (non-coarse)", () => {
    // Override to fine pointer for this one test.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (_query: string) => ({ matches: false }),
    });

    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "touch" });
    vi.advanceTimersByTime(500);

    expect(cb).not.toHaveBeenCalled();
    expect(() => destroy()).not.toThrow();
  });

  it("durationMs override is respected", () => {
    const cb = vi.fn();
    const { destroy } = longpress(node, { onLongPress: cb, durationMs: 200 });

    fire("pointerdown", { clientX: 0, clientY: 0, pointerType: "touch" });
    vi.advanceTimersByTime(199);
    expect(cb).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(cb).toHaveBeenCalledOnce();

    destroy();
  });
});
