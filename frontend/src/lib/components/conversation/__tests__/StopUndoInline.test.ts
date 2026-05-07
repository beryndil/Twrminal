/**
 * Component tests for ``StopUndoInline`` (gap-cycle-11-002).
 *
 * Acceptance criteria covered:
 *
 * 1. Arm → countdown ticks down → ``stopSession`` fires once after the
 *    grace window expires; Stop button is restored.
 * 2. Arm → Undo → no ``stopSession`` call; turn continues uninterrupted.
 * 3. Arm → session switch → stop commits for the **old** session
 *    deterministically; no second commit for the new session.
 * 4. Double-click on Stop does not arm the grace window twice; a single
 *    ``stopSession`` call is issued after the window expires.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

// Mock the sessions API module before importing the component so
// ``stopSession`` is always a spy.
vi.mock("../../../api/sessions", () => ({
  stopSession: vi.fn().mockResolvedValue(undefined),
}));

import { STOP_UNDO_GRACE_MS, STOP_UNDO_TICK_MS } from "../../../config";
import StopUndoInline from "../StopUndoInline.svelte";
import { stopSession } from "../../../api/sessions";

const stopMock = stopSession as Mock;

/** Advance the fake clock by ``ms`` and flush Svelte's microtask queue. */
async function advance(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Fake timers must be installed before the component mounts so
  // every setTimeout/setInterval the component queues uses the fake clock.
  vi.useFakeTimers();
  stopMock.mockReset();
  stopMock.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Idle state
// ---------------------------------------------------------------------------

describe("StopUndoInline — idle state", () => {
  it("shows the Stop button and no countdown chip by default", () => {
    const { getByTestId, queryByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    expect(getByTestId("stop-turn-button")).toBeTruthy();
    expect(queryByTestId("stop-undo-countdown")).toBeNull();
    expect(queryByTestId("stop-undo-button")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC1: arm → countdown ticks → commit fires
// ---------------------------------------------------------------------------

describe("StopUndoInline — arm → countdown → commit (AC1)", () => {
  it("replaces the Stop button with a countdown chip and Undo button on click", async () => {
    const { getByTestId, queryByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);

    expect(queryByTestId("stop-turn-button")).toBeNull();
    expect(getByTestId("stop-undo-countdown")).toBeTruthy();
    expect(getByTestId("stop-undo-button")).toBeTruthy();
  });

  it("shows the initial seconds in the countdown chip immediately after arming", async () => {
    const { getByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);

    const initialSeconds = Math.ceil(STOP_UNDO_GRACE_MS / 1000); // 3
    expect(getByTestId("stop-undo-countdown").textContent).toContain(
      `Stopping ${initialSeconds}s`,
    );
  });

  it("decrements the countdown at each tick interval", async () => {
    const { getByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));

    // After 2 ticks: msLeft = GRACE - 2*TICK = 3000 - 1000 = 2000
    // secondsLeft = ceil(2000/1000) = 2
    await advance(2 * STOP_UNDO_TICK_MS);

    expect(getByTestId("stop-undo-countdown").textContent).toContain("Stopping 2s");
  });

  it("fires stopSession once with the correct sessionId after the grace window", async () => {
    const { getByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    expect(stopMock).not.toHaveBeenCalled();

    await advance(STOP_UNDO_GRACE_MS);

    expect(stopMock).toHaveBeenCalledTimes(1);
    expect(stopMock).toHaveBeenCalledWith("ses_1");
  });

  it("restores the Stop button and removes the countdown chip after commit", async () => {
    const { getByTestId, queryByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(STOP_UNDO_GRACE_MS);

    await waitFor(() => {
      expect(getByTestId("stop-turn-button")).toBeTruthy();
      expect(queryByTestId("stop-undo-countdown")).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// AC2: arm → undo → no commit
// ---------------------------------------------------------------------------

describe("StopUndoInline — arm → undo → no commit (AC2)", () => {
  it("restores the Stop button when Undo is clicked", async () => {
    const { getByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);
    fireEvent.click(getByTestId("stop-undo-button"));
    await advance(0);

    expect(getByTestId("stop-turn-button")).toBeTruthy();
  });

  it("removes the countdown chip and Undo button after Undo", async () => {
    const { getByTestId, queryByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);
    fireEvent.click(getByTestId("stop-undo-button"));
    await advance(0);

    expect(queryByTestId("stop-undo-countdown")).toBeNull();
    expect(queryByTestId("stop-undo-button")).toBeNull();
  });

  it("does not fire stopSession even after the original grace window would have expired", async () => {
    const { getByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);
    fireEvent.click(getByTestId("stop-undo-button"));

    // Advance well past where the grace timer would have fired
    await advance(STOP_UNDO_GRACE_MS + 1_000);

    expect(stopMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// AC3: arm → session switch → deterministic commit for old session
// ---------------------------------------------------------------------------

describe("StopUndoInline — session switch commits deterministically (AC3)", () => {
  it("commits stop for the old session when sessionId prop changes mid-window", async () => {
    const { getByTestId, rerender } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(STOP_UNDO_TICK_MS); // partial progress into grace window

    // Switch session — triggers the $effect cleanup for "ses_1"
    rerender({ sessionId: "ses_2" });
    await advance(0); // flush cleanup + async commitStop microtasks

    expect(stopMock).toHaveBeenCalledTimes(1);
    expect(stopMock).toHaveBeenCalledWith("ses_1");
  });

  it("does not issue a second stop for the new session after the original grace window would expire", async () => {
    const { getByTestId, rerender } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(STOP_UNDO_TICK_MS);

    rerender({ sessionId: "ses_2" });
    // Advance well past where the original timer would have fired
    await advance(STOP_UNDO_GRACE_MS + 1_000);

    // Exactly one commit — for "ses_1" only
    expect(stopMock).toHaveBeenCalledTimes(1);
    expect(stopMock).toHaveBeenCalledWith("ses_1");
  });

  it("does not commit if Undo was clicked before the session switch", async () => {
    const { getByTestId, rerender } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);
    fireEvent.click(getByTestId("stop-undo-button"));
    await advance(0);

    // Switch session after undo — no pending stop, nothing to commit
    rerender({ sessionId: "ses_2" });
    await advance(STOP_UNDO_GRACE_MS + 1_000);

    expect(stopMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// AC4: double-click does not arm twice
// ---------------------------------------------------------------------------

describe("StopUndoInline — double-click guard (AC4)", () => {
  it("shows exactly one countdown chip after the Stop button is clicked", async () => {
    const { getByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);

    // Stop button is replaced — structural double-click is impossible.
    // Verify exactly one countdown chip is present.
    expect(document.querySelectorAll('[data-testid="stop-undo-countdown"]').length).toBe(1);
  });

  it("fires stopSession exactly once after the grace window expires", async () => {
    const { getByTestId, queryByTestId } = render(StopUndoInline, {
      props: { sessionId: "ses_1" },
    });

    fireEvent.click(getByTestId("stop-turn-button"));
    await advance(0);

    // Stop button is now absent; further clicks are impossible.
    expect(queryByTestId("stop-turn-button")).toBeNull();

    await advance(STOP_UNDO_GRACE_MS);

    expect(stopMock).toHaveBeenCalledTimes(1);
    expect(stopMock).toHaveBeenCalledWith("ses_1");
  });
});
