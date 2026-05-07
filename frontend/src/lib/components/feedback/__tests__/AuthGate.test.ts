/**
 * Unit tests for ``AuthGate`` (gap-cycle-01-007).
 *
 * Acceptance criteria covered:
 *
 * 1. When ``auth.blocking`` is ``true``, a centered modal renders over
 *    the app shell.
 * 2. Modal contains a labeled input for the token and a Submit button.
 * 3. Submit calls ``saveToken(value)`` and (on success) clears blocking.
 * 4. Modal auto-focuses the input on open.
 * 5. Modal cannot be dismissed without supplying a token (Submit is
 *    disabled when the input is empty).
 *
 * ``connectSessionsBroadcast`` is mocked at module level so no real
 * WebSocket is constructed and its reconnection timers do not interfere
 * with fake timers.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the WS API before any store loads so no real socket is opened.
vi.mock("../../../api/wsSessions", () => ({
  connectSessionsBroadcast: vi.fn().mockReturnValue(() => {}),
}));

import {
  _resetForTests as resetAuth,
  _setBlockingForTests,
  authStore,
} from "../../../stores/auth.svelte";
import {
  _resetWsStatusForTests,
  _setWsStatusForTests,
} from "../../../stores/sessions.svelte";
import AuthGate from "../AuthGate.svelte";

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
  // Start each test with a healthy connection and no blocking state.
  _setWsStatusForTests({ state: "open", lastCloseCode: null });
  resetAuth();
  window.localStorage.clear();
});

afterEach(() => {
  resetAuth();
  _resetWsStatusForTests();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Flush Svelte's microtask queue and any fake-timer callbacks. */
async function flush(ms = 0): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
}

// ---------------------------------------------------------------------------
// Visibility (AC 1 + AC 5)
// ---------------------------------------------------------------------------

describe("AuthGate — visibility", () => {
  it("is hidden when auth.blocking is false", async () => {
    const { queryByTestId } = render(AuthGate);
    await flush();
    expect(queryByTestId("auth-gate-overlay")).toBeNull();
  });

  it("renders the modal when auth.blocking is true", async () => {
    _setBlockingForTests(true);
    const { queryByTestId } = render(AuthGate);
    await flush();
    expect(queryByTestId("auth-gate-overlay")).toBeInTheDocument();
  });

  it("modal contains a labeled input and a Submit button (AC 2)", async () => {
    _setBlockingForTests(true);
    const { getByTestId } = render(AuthGate);
    await flush();
    expect(getByTestId("auth-gate-input")).toBeInTheDocument();
    expect(getByTestId("auth-gate-label")).toBeInTheDocument();
    expect(getByTestId("auth-gate-submit")).toBeInTheDocument();
  });

  it("Submit is disabled when the input is empty (AC 5)", async () => {
    _setBlockingForTests(true);
    const { getByTestId } = render(AuthGate);
    await flush();
    expect(getByTestId("auth-gate-submit")).toBeDisabled();
  });

  it("modal disappears after blocking is cleared", async () => {
    _setBlockingForTests(true);
    const { queryByTestId } = render(AuthGate);
    await flush();
    expect(queryByTestId("auth-gate-overlay")).toBeInTheDocument();

    // Simulate token save clearing the blocking flag
    _setBlockingForTests(false);
    await flush();
    expect(queryByTestId("auth-gate-overlay")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// WS trigger (auth.blocking set by 4401 close code)
// ---------------------------------------------------------------------------

describe("AuthGate — WS 4401 trigger", () => {
  it("becomes visible when WS closes with code 4401", async () => {
    const { queryByTestId } = render(AuthGate);
    await flush();
    expect(queryByTestId("auth-gate-overlay")).toBeNull();

    _setWsStatusForTests({ state: "closed", lastCloseCode: 4401 });
    await flush();

    expect(queryByTestId("auth-gate-overlay")).toBeInTheDocument();
    expect(authStore.blocking).toBe(true);
  });

  it("does NOT become visible for non-4401 close codes", async () => {
    const { queryByTestId } = render(AuthGate);
    _setWsStatusForTests({ state: "closed", lastCloseCode: 1006 });
    await flush();
    expect(queryByTestId("auth-gate-overlay")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Submit path (AC 3)
// ---------------------------------------------------------------------------

describe("AuthGate — submit path", () => {
  it("Submit button enables once the input has a non-empty value", async () => {
    _setBlockingForTests(true);
    const { getByTestId } = render(AuthGate);
    await flush();

    const input = getByTestId("auth-gate-input") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "sk-ant-abc123" } });
    await flush();

    expect(getByTestId("auth-gate-submit")).not.toBeDisabled();
  });

  it("clicking Submit clears auth.blocking (AC 3)", async () => {
    _setBlockingForTests(true);
    const { getByTestId, queryByTestId } = render(AuthGate);
    await flush();

    const input = getByTestId("auth-gate-input") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "sk-ant-abc123" } });
    await flush();

    await fireEvent.click(getByTestId("auth-gate-submit"));
    await waitFor(() => {
      expect(authStore.blocking).toBe(false);
    });
    expect(queryByTestId("auth-gate-overlay")).toBeNull();
  });

  it("saveToken persists the token to localStorage", async () => {
    _setBlockingForTests(true);
    const { getByTestId } = render(AuthGate);
    await flush();

    const input = getByTestId("auth-gate-input") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "sk-ant-abc123" } });
    await fireEvent.click(getByTestId("auth-gate-submit"));
    await waitFor(() => expect(authStore.blocking).toBe(false));

    expect(window.localStorage.getItem("bearings-v1:auth-token")).toBe("sk-ant-abc123");
  });

  it("Enter key in the input submits the form", async () => {
    _setBlockingForTests(true);
    const { getByTestId } = render(AuthGate);
    await flush();

    const input = getByTestId("auth-gate-input") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "sk-ant-enter-key" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(authStore.blocking).toBe(false));
  });
});

// ---------------------------------------------------------------------------
// Auto-focus (AC 4)
// ---------------------------------------------------------------------------

describe("AuthGate — auto-focus", () => {
  it("focuses the input when the gate opens (AC 4)", async () => {
    const focusSpy = vi.spyOn(HTMLElement.prototype, "focus");
    _setBlockingForTests(true);
    render(AuthGate);
    // tick() defers the focus via a microtask; advance to let it fire.
    await flush(0);
    expect(focusSpy).toHaveBeenCalled();
  });
});
