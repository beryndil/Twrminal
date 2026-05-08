/**
 * Unit tests for ``StatusBar`` (gap-cycle-01-018).
 *
 * Acceptance criteria covered:
 *
 * 1. Version string updates when the versionWatcher store changes
 *    (simulates a "tick" by calling ``_setVersionForTests``).
 * 2. Recovery and auto-save dots carry ``bg-accent`` while WS is open
 *    and switch to ``bg-slate-500`` when WS closes.
 * 3. Working-dir slot is hidden when ``sessionId`` is ``null``; visible
 *    when a session is active.
 * 4. Strip persists (remains mounted) when no session is selected.
 * 5. Connection label reads "connected" when WS open, "disconnected"
 *    otherwise.
 *
 * ``connectSessionsBroadcast`` is mocked at module level so no real
 * WebSocket is constructed and the reconnection timers do not interfere
 * with ``vi.useFakeTimers()``.
 *
 * ``getJson`` (used by ``versionWatcher``) is mocked so no real HTTP
 * request is issued during tests. The top-level ``void refreshVersion()``
 * call inside the module fires on import — the mock absorbs it.
 */
import { render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the WS API before any store loads.
vi.mock("../../../api/wsSessions", () => ({
  connectSessionsBroadcast: vi.fn().mockReturnValue(() => {}),
}));

// Mock the HTTP client so the versionWatcher module-level fetch and poll
// do not issue real requests.
vi.mock("../../../api/client", () => ({
  getJson: vi.fn().mockResolvedValue({ version: "0.0.0-test" }),
}));

import { _resetWsStatusForTests, _setWsStatusForTests } from "../../../stores/sessions.svelte";
import {
  _resetVersionWatcherForTests,
  _setVersionForTests,
  _startVersionPollForTests,
} from "../../../stores/versionWatcher.svelte";
import { STATUS_BAR_STRINGS, STATUS_BAR_VERSION_POLL_INTERVAL_MS } from "../../../config";
import StatusBar from "../StatusBar.svelte";

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
  _setWsStatusForTests({ state: "open", lastCloseCode: null });
  _resetVersionWatcherForTests();
});

afterEach(() => {
  _resetWsStatusForTests();
  _resetVersionWatcherForTests();
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

describe("StatusBar — version display", () => {
  it("shows the loading placeholder before the first fetch resolves", async () => {
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();
    expect(getByTestId("status-bar-version").textContent).toBe(STATUS_BAR_STRINGS.versionLoading);
  });

  it("updates the displayed version when the versionWatcher store is set", async () => {
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    _setVersionForTests("1.2.3");
    await tick();
    expect(getByTestId("status-bar-version").textContent).toBe("1.2.3");
  });

  it("reflects a second version update (simulates a poll tick)", async () => {
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });

    _setVersionForTests("1.0.0");
    await tick();
    expect(getByTestId("status-bar-version").textContent).toBe("1.0.0");

    _setVersionForTests("1.1.0");
    await tick();
    expect(getByTestId("status-bar-version").textContent).toBe("1.1.0");
  });

  it("polls getJson on the configured interval", async () => {
    const { getJson } = await import("../../../api/client");
    const mockGetJson = vi.mocked(getJson);
    mockGetJson.mockResolvedValue({ version: "2.0.0" });

    _startVersionPollForTests();
    await vi.advanceTimersByTimeAsync(STATUS_BAR_VERSION_POLL_INTERVAL_MS);

    // At least one poll call should have fired.
    expect(mockGetJson).toHaveBeenCalled();
  });
});

describe("StatusBar — WS connection dots", () => {
  it("recovery dot carries bg-accent when WS is open", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();
    const dot = getByTestId("status-bar-recovery-dot").querySelector("span[aria-hidden]");
    expect(dot?.classList.contains("bg-accent")).toBe(true);
    expect(dot?.classList.contains("bg-slate-500")).toBe(false);
  });

  it("recovery dot dims to bg-slate-500 when WS closes", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();

    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    await tick();

    const dot = getByTestId("status-bar-recovery-dot").querySelector("span[aria-hidden]");
    expect(dot?.classList.contains("bg-slate-500")).toBe(true);
    expect(dot?.classList.contains("bg-accent")).toBe(false);
  });

  it("auto-save dot dims to bg-slate-500 when WS closes", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();

    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    await tick();

    const dot = getByTestId("status-bar-autosave-dot").querySelector("span[aria-hidden]");
    expect(dot?.classList.contains("bg-slate-500")).toBe(true);
    expect(dot?.classList.contains("bg-accent")).toBe(false);
  });

  it("dots re-light to bg-accent when WS reconnects", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();

    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    await tick();

    const recoveryDot = getByTestId("status-bar-recovery-dot").querySelector("span[aria-hidden]");
    expect(recoveryDot?.classList.contains("bg-accent")).toBe(true);
  });
});

describe("StatusBar — connection label", () => {
  it("shows 'connected' when WS is open", async () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();
    expect(getByTestId("status-bar-connection").textContent).toBe(
      STATUS_BAR_STRINGS.connectionConnected,
    );
  });

  it("shows 'disconnected' when WS is closed", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();
    expect(getByTestId("status-bar-connection").textContent).toBe(
      STATUS_BAR_STRINGS.connectionDisconnected,
    );
  });

  it("shows 'disconnected' when WS is in error state", async () => {
    _setWsStatusForTests({ state: "error", lastCloseCode: null });
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();
    expect(getByTestId("status-bar-connection").textContent).toBe(
      STATUS_BAR_STRINGS.connectionDisconnected,
    );
  });
});

describe("StatusBar — working-dir slot", () => {
  it("hides the working-dir slot when sessionId is null", async () => {
    const { queryByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();
    expect(queryByTestId("status-bar-workdir")).toBeNull();
  });

  it("hides the working-dir slot when sessionId is set but workingDir is null", async () => {
    const { queryByTestId } = render(StatusBar, {
      props: { workingDir: null, sessionId: "abc-123" },
    });
    await tick();
    expect(queryByTestId("status-bar-workdir")).toBeNull();
  });

  it("shows the working-dir slot when sessionId and workingDir are both set", async () => {
    const { getByTestId } = render(StatusBar, {
      props: { workingDir: "/home/beryndil/Projects/active/bearings", sessionId: "abc-123" },
    });
    await tick();
    expect(getByTestId("status-bar-workdir").textContent).toBe(
      "/home/beryndil/Projects/active/bearings",
    );
  });
});

describe("StatusBar — persistence", () => {
  it("remains mounted when no session is selected (strip persists)", async () => {
    const { getByTestId } = render(StatusBar, { props: { workingDir: null, sessionId: null } });
    await tick();
    // The content wrapper should always be present regardless of session state.
    expect(getByTestId("status-bar-content")).toBeInTheDocument();
  });
});
