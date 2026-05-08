/**
 * Unit tests for ``SystemStatusCard`` (gap-cycle-08-006).
 *
 * Acceptance criteria covered:
 *
 * 1. When ``wsConnectionStatus.state`` is ``'open'``: both dots carry
 *    ``bg-accent``; connection label reads "Connected"; Claude label
 *    reads "Reachable".
 * 2. When ``wsConnectionStatus.state`` is ``'closed'``: both dots carry
 *    ``bg-rose-500``; connection label reads "Disconnected"; Claude
 *    label reads "Unreachable".
 * 3. When ``wsConnectionStatus.state`` is ``'error'``: both dots carry
 *    ``bg-rose-500``; connection label reads "Disconnected"; Claude
 *    label reads "Unreachable".
 *
 * ``connectSessionsBroadcast`` is mocked at module level so no real
 * WebSocket is constructed and reconnection timers do not interfere.
 */
import { render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the WS API before any store loads.
vi.mock("../../../api/wsSessions", () => ({
  connectSessionsBroadcast: vi.fn().mockReturnValue(() => {}),
}));

import { _resetWsStatusForTests, _setWsStatusForTests } from "../../../stores/sessions.svelte";
import { SYSTEM_STATUS_CARD_STRINGS } from "../../../config";
import SystemStatusCard from "../SystemStatusCard.svelte";

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
  _resetWsStatusForTests();
});

afterEach(() => {
  _resetWsStatusForTests();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function tick(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SystemStatusCard — open state", () => {
  it("connection dot carries bg-accent when WS is open", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    const dot = getByTestId("system-status-connection-dot");
    expect(dot.classList.contains("bg-accent")).toBe(true);
    expect(dot.classList.contains("bg-rose-500")).toBe(false);
  });

  it("connection label reads 'Connected' when WS is open", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    expect(getByTestId("system-status-connection-label").textContent?.trim()).toBe(
      SYSTEM_STATUS_CARD_STRINGS.connectionConnected,
    );
  });

  it("Claude dot carries bg-accent when WS is open", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    const dot = getByTestId("system-status-claude-dot");
    expect(dot.classList.contains("bg-accent")).toBe(true);
    expect(dot.classList.contains("bg-rose-500")).toBe(false);
  });

  it("Claude label reads 'Reachable' when WS is open", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    expect(getByTestId("system-status-claude-label").textContent?.trim()).toBe(
      SYSTEM_STATUS_CARD_STRINGS.claudeReachable,
    );
  });
});

describe("SystemStatusCard — closed state", () => {
  it("connection dot carries bg-rose-500 when WS is closed", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    const dot = getByTestId("system-status-connection-dot");
    expect(dot.classList.contains("bg-rose-500")).toBe(true);
    expect(dot.classList.contains("bg-accent")).toBe(false);
  });

  it("connection label reads 'Disconnected' when WS is closed", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    expect(getByTestId("system-status-connection-label").textContent?.trim()).toBe(
      SYSTEM_STATUS_CARD_STRINGS.connectionDisconnected,
    );
  });

  it("Claude label reads 'Unreachable' when WS is closed", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    expect(getByTestId("system-status-claude-label").textContent?.trim()).toBe(
      SYSTEM_STATUS_CARD_STRINGS.claudeUnreachable,
    );
  });
});

describe("SystemStatusCard — error state", () => {
  it("connection dot carries bg-rose-500 when WS is in error state", async () => {
    _setWsStatusForTests({ state: "error", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    const dot = getByTestId("system-status-connection-dot");
    expect(dot.classList.contains("bg-rose-500")).toBe(true);
    expect(dot.classList.contains("bg-accent")).toBe(false);
  });

  it("connection label reads 'Disconnected' when WS is in error state", async () => {
    _setWsStatusForTests({ state: "error", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    expect(getByTestId("system-status-connection-label").textContent?.trim()).toBe(
      SYSTEM_STATUS_CARD_STRINGS.connectionDisconnected,
    );
  });

  it("Claude label reads 'Unreachable' when WS is in error state", async () => {
    _setWsStatusForTests({ state: "error", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    expect(getByTestId("system-status-claude-label").textContent?.trim()).toBe(
      SYSTEM_STATUS_CARD_STRINGS.claudeUnreachable,
    );
  });
});

describe("SystemStatusCard — card always mounted", () => {
  it("card container is present regardless of WS state", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(SystemStatusCard);
    await tick();
    expect(getByTestId("system-status-card")).toBeInTheDocument();
  });
});
