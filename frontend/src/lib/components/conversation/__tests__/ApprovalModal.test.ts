/**
 * Component tests for ``ApprovalModal`` covering WebSocket-aware button
 * disabling (gap-cycle-10-009).
 *
 * Acceptance criteria covered:
 *
 * 1. When the sessions-broadcast WS is ``'open'`` Allow and Deny are enabled.
 * 2. When the WS is not ``'open'`` Allow and Deny are disabled and the
 *    "Reconnecting…" banner renders inside the modal body.
 * 3. When the WS reconnects Allow and Deny re-enable without dismissing the
 *    modal.
 * 4. Clicking Allow/Deny while disconnected does not invoke ``postApproval``
 *    (the guard inside ``resolve()`` returns early).
 *
 * ``connectSessionsBroadcast`` is mocked at module level so no real
 * WebSocket is created and no reconnection timers interfere with the tests.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Hoist the postApproval spy so the mock factory can reference it.
const { postApprovalMock } = vi.hoisted(() => ({ postApprovalMock: vi.fn() }));

vi.mock("../../../api/approvals", () => ({
  postApproval: postApprovalMock,
}));

// Mock the sessions-broadcast WS so no real socket is opened and
// reconnect timers do not interfere.
vi.mock("../../../api/wsSessions", () => ({
  connectSessionsBroadcast: vi.fn().mockReturnValue(() => {}),
}));

import {
  _resetWsStatusForTests,
  _setWsStatusForTests,
} from "../../../stores/sessions.svelte";
import ApprovalModal from "../ApprovalModal.svelte";
import type { PendingApproval } from "../../../stores/conversation.svelte";

function makeApproval(): PendingApproval {
  return {
    requestId: "req_approval",
    toolName: "Bash",
    toolInputJson: JSON.stringify({ command: "ls -la" }),
  };
}

beforeEach(() => {
  postApprovalMock.mockReset();
  postApprovalMock.mockResolvedValue(undefined);
  // Default to connected so unrelated tests do not need to set status.
  _setWsStatusForTests({ state: "open", lastCloseCode: null });
});

afterEach(() => {
  _resetWsStatusForTests();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------

describe("ApprovalModal — WS connected: buttons enabled", () => {
  it("Allow and Deny are enabled when wsConnectionStatus.state is 'open'", () => {
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    const { getByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    expect((getByTestId("approval-allow") as HTMLButtonElement).disabled).toBe(false);
    expect((getByTestId("approval-deny") as HTMLButtonElement).disabled).toBe(false);
    expect(getByTestId("approval-modal").querySelector("[data-testid='approval-reconnect-banner']")).toBeNull();
  });
});

describe("ApprovalModal — WS disconnected: buttons disabled + banner", () => {
  it("Allow and Deny are disabled and reconnect banner renders when state is 'closed'", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId, queryByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    await Promise.resolve(); // flush reactivity
    expect((getByTestId("approval-allow") as HTMLButtonElement).disabled).toBe(true);
    expect((getByTestId("approval-deny") as HTMLButtonElement).disabled).toBe(true);
    expect(queryByTestId("approval-reconnect-banner")).not.toBeNull();
    expect(queryByTestId("approval-reconnect-banner")?.textContent).toContain("Reconnecting");
  });

  it("buttons are disabled and banner renders when state is 'error'", async () => {
    _setWsStatusForTests({ state: "error", lastCloseCode: null });
    const { getByTestId, queryByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    await Promise.resolve();
    expect((getByTestId("approval-allow") as HTMLButtonElement).disabled).toBe(true);
    expect((getByTestId("approval-deny") as HTMLButtonElement).disabled).toBe(true);
    expect(queryByTestId("approval-reconnect-banner")).not.toBeNull();
  });
});

describe("ApprovalModal — WS reconnect: buttons re-enable without dismissing", () => {
  it("Allow and Deny re-enable and banner disappears when state transitions to 'open'", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId, queryByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    await Promise.resolve();
    // Confirm disconnected state
    expect((getByTestId("approval-allow") as HTMLButtonElement).disabled).toBe(true);
    expect(queryByTestId("approval-reconnect-banner")).not.toBeNull();
    // Simulate reconnect
    _setWsStatusForTests({ state: "open", lastCloseCode: null });
    await Promise.resolve();
    // Modal still open but buttons re-enabled
    expect(getByTestId("approval-modal")).toBeTruthy();
    expect((getByTestId("approval-allow") as HTMLButtonElement).disabled).toBe(false);
    expect((getByTestId("approval-deny") as HTMLButtonElement).disabled).toBe(false);
    expect(queryByTestId("approval-reconnect-banner")).toBeNull();
  });
});

describe("ApprovalModal — Esc is blocked while the gate is up (gap-cycle-10-010)", () => {
  it("Esc keypress is a no-op — modal stays open and postApproval is not called", async () => {
    const { getByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    // Dispatch on the modal element so capture phase runs from window → target.
    await fireEvent.keyDown(getByTestId("approval-modal"), { key: "Escape" });
    // Modal element still in the DOM.
    expect(getByTestId("approval-modal")).toBeTruthy();
    // No resolution POST was triggered.
    expect(postApprovalMock).not.toHaveBeenCalled();
  });

  it("Esc does not propagate to bubble-phase handlers (e.g. the Esc cascade)", async () => {
    // Register a bubble-phase listener on window before and after render;
    // neither should fire because the modal's capture-phase listener calls
    // stopPropagation before the event reaches the bubble phase.
    const outerHandler = vi.fn();
    window.addEventListener("keydown", outerHandler);
    const { getByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    await fireEvent.keyDown(getByTestId("approval-modal"), { key: "Escape" });
    expect(outerHandler).not.toHaveBeenCalled();
    window.removeEventListener("keydown", outerHandler);
  });
});

describe("ApprovalModal — submit while disconnected blocked", () => {
  it("clicking Allow while disconnected does not call postApproval", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    await Promise.resolve();
    // Button is disabled; click should not invoke postApproval.
    await fireEvent.click(getByTestId("approval-allow"));
    await waitFor(() => {
      expect(postApprovalMock).not.toHaveBeenCalled();
    });
  });

  it("clicking Deny while disconnected does not call postApproval", async () => {
    _setWsStatusForTests({ state: "closed", lastCloseCode: null });
    const { getByTestId } = render(ApprovalModal, {
      props: { sessionId: "ses_x", approval: makeApproval() },
    });
    await Promise.resolve();
    await fireEvent.click(getByTestId("approval-deny"));
    await waitFor(() => {
      expect(postApprovalMock).not.toHaveBeenCalled();
    });
  });
});
