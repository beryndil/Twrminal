/**
 * Unit tests for ``BackendStatusBanner`` (gap-cycle-01-006).
 *
 * Acceptance criteria covered:
 *
 * 1. Banner hidden while WS state is ``'open'``.
 * 2. Banner remains hidden during the first 5 s of a disconnect.
 * 3. Banner becomes visible once disconnect persists past 5 s.
 * 4. Banner clears immediately on reconnect.
 * 5. Banner suppressed when ``lastCloseCode === 4401``.
 * 6. State-transition: banner hides when close code becomes 4401
 *    mid-disconnect.
 *
 * ``connectSessionsBroadcast`` is mocked at module level so no real
 * WebSocket is created and its reconnection timers do not interfere
 * with ``vi.useFakeTimers()``.
 */
import { render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the WS API before the sessions store module loads so no real
// WebSocket is constructed and no reconnection setTimeout is queued.
vi.mock("../../../api/wsSessions", () => ({
  connectSessionsBroadcast: vi.fn().mockReturnValue(() => {}),
}));

import {
  _resetWsStatusForTests,
  _setWsStatusForTests,
} from "../../../stores/sessions.svelte";
import { BACKEND_UNREACHABLE_THRESHOLD_MS } from "../../../config";
import BackendStatusBanner from "../BackendStatusBanner.svelte";

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Fake timers must be installed before the component mounts so any
  // setTimeout the $effect issues uses the fake clock.
  vi.useFakeTimers();
  // Start every test with a healthy connection; individual tests
  // transition from there.
  _setWsStatusForTests({ state: "open", lastCloseCode: null });
});

afterEach(() => {
  _resetWsStatusForTests();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Advance the fake clock and flush Svelte's microtask queue. */
async function advance(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BackendStatusBanner — state transitions", () => {
  it("is hidden while WS state is open", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { queryByTestId } = render(BackendStatusBanner);
    await advance(0);
    expect(queryByTestId("backend-status-banner")).toBeNull();
  });

  it("remains hidden for the full threshold duration of a disconnect", async () => {
    const { queryByTestId } = render(BackendStatusBanner);

    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    await advance(BACKEND_UNREACHABLE_THRESHOLD_MS - 1);

    expect(queryByTestId("backend-status-banner")).toBeNull();
  });

  it("becomes visible once disconnect persists past the threshold", async () => {
    const { queryByTestId } = render(BackendStatusBanner);

    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    await advance(BACKEND_UNREACHABLE_THRESHOLD_MS);

    expect(queryByTestId("backend-status-banner")).not.toBeNull();
    expect(queryByTestId("backend-status-banner")).toBeInTheDocument();
  });

  it("clears immediately on reconnect after threshold fires", async () => {
    const { queryByTestId } = render(BackendStatusBanner);

    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    await advance(BACKEND_UNREACHABLE_THRESHOLD_MS);
    expect(queryByTestId("backend-status-banner")).toBeInTheDocument();

    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    await advance(0);

    expect(queryByTestId("backend-status-banner")).toBeNull();
  });

  it("cancels the pending timer and stays hidden when reconnect beats the threshold", async () => {
    const { queryByTestId } = render(BackendStatusBanner);

    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    await advance(BACKEND_UNREACHABLE_THRESHOLD_MS - 100);

    // Reconnect before threshold fires
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    await advance(200); // well past where the timer would have fired

    expect(queryByTestId("backend-status-banner")).toBeNull();
  });
});

describe("BackendStatusBanner — auth-failure suppression", () => {
  it("suppresses the banner when lastCloseCode is 4401", async () => {
    const { queryByTestId } = render(BackendStatusBanner);

    _setWsStatusForTests({ state: "closed", lastCloseCode: 4401 });
    await advance(BACKEND_UNREACHABLE_THRESHOLD_MS);

    expect(queryByTestId("backend-status-banner")).toBeNull();
  });

  it("hides an already-visible banner when close code becomes 4401", async () => {
    const { queryByTestId } = render(BackendStatusBanner);

    // Let the banner become visible first
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    await advance(BACKEND_UNREACHABLE_THRESHOLD_MS);
    expect(queryByTestId("backend-status-banner")).toBeInTheDocument();

    // Auth-failure close arrives (server re-closes with 4401)
    _setWsStatusForTests({ state: "closed", lastCloseCode: 4401 });
    await advance(0);

    expect(queryByTestId("backend-status-banner")).toBeNull();
  });

  it("remains suppressed for the error state when lastCloseCode is 4401", async () => {
    const { queryByTestId } = render(BackendStatusBanner);

    _setWsStatusForTests({ state: "error", lastCloseCode: 4401 });
    await advance(BACKEND_UNREACHABLE_THRESHOLD_MS);

    expect(queryByTestId("backend-status-banner")).toBeNull();
  });
});
