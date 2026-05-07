/**
 * Unit tests for ``src/lib/utils/notify.ts`` (gap-cycle-07-001).
 *
 * Acceptance criteria covered:
 *
 * 1. ``supportsNotifications`` returns false when ``Notification`` is absent.
 * 2. ``maybeFireTurnNotification`` is a no-op when ``_notifyOnComplete`` is false.
 * 3. ``maybeFireTurnNotification`` is a no-op when permission is not "granted".
 * 4. ``maybeFireTurnNotification`` is a no-op when the document is visible + focused.
 * 5. ``maybeFireTurnNotification`` fires when opted-in, granted, and tab hidden.
 * 6. ``maybeFireTurnNotification`` fires when opted-in, granted, and tab unfocused.
 * 7. ``setNotifyOnComplete`` / ``getNotifyOnComplete`` round-trip.
 * 8. ``requestNotifyPermission`` returns "denied" when Notification absent.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getNotifyOnComplete,
  maybeFireTurnNotification,
  requestNotifyPermission,
  setNotifyOnComplete,
  supportsNotifications,
  type NotifyPermission,
} from "../notify";

// ---------------------------------------------------------------------------
// Helpers — stub window.Notification
// ---------------------------------------------------------------------------

interface NotificationStub {
  permission: NotifyPermission;
  requestPermission: ReturnType<typeof vi.fn>;
  calls: Array<{ title: string; options?: { body?: string } }>;
}

function stubNotification(
  permission: NotifyPermission,
  hasFocus: boolean,
  visibilityState: "visible" | "hidden",
): NotificationStub {
  const stub: NotificationStub = {
    permission,
    requestPermission: vi.fn().mockResolvedValue(permission),
    calls: [],
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).Notification = function (title: string, options?: { body?: string }) {
    stub.calls.push({ title, options });
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).Notification.permission = permission;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).Notification.requestPermission = stub.requestPermission;

  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibilityState,
  });
  vi.spyOn(document, "hasFocus").mockReturnValue(hasFocus);

  return stub;
}

function clearNotification(): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (globalThis as any).Notification;
}

// Reset module-level state between tests.
afterEach(() => {
  setNotifyOnComplete(false);
  clearNotification();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. supportsNotifications
// ---------------------------------------------------------------------------

describe("supportsNotifications", () => {
  it("returns false when Notification is absent", () => {
    clearNotification();
    expect(supportsNotifications()).toBe(false);
  });

  it("returns true when Notification is present", () => {
    stubNotification("default", true, "visible");
    expect(supportsNotifications()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 2. no-op when opt-in is false
// ---------------------------------------------------------------------------

describe("maybeFireTurnNotification — opt-in false", () => {
  it("does not fire when notifyOnComplete is false", () => {
    const stub = stubNotification("granted", false, "hidden");
    setNotifyOnComplete(false);
    maybeFireTurnNotification();
    expect(stub.calls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 3. no-op when permission is not granted
// ---------------------------------------------------------------------------

describe("maybeFireTurnNotification — permission not granted", () => {
  it("does not fire when permission is 'default'", () => {
    const stub = stubNotification("default", false, "hidden");
    setNotifyOnComplete(true);
    maybeFireTurnNotification();
    expect(stub.calls).toHaveLength(0);
  });

  it("does not fire when permission is 'denied'", () => {
    const stub = stubNotification("denied", false, "hidden");
    setNotifyOnComplete(true);
    maybeFireTurnNotification();
    expect(stub.calls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 4. no-op when tab is visible AND focused
// ---------------------------------------------------------------------------

describe("maybeFireTurnNotification — tab visible and focused", () => {
  it("does not fire when visible + focused", () => {
    const stub = stubNotification("granted", true, "visible");
    setNotifyOnComplete(true);
    maybeFireTurnNotification();
    expect(stub.calls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 5. fires when tab is hidden
// ---------------------------------------------------------------------------

describe("maybeFireTurnNotification — tab hidden", () => {
  it("fires when visibilityState is 'hidden' (even if hasFocus were true)", () => {
    const stub = stubNotification("granted", false, "hidden");
    setNotifyOnComplete(true);
    maybeFireTurnNotification();
    expect(stub.calls).toHaveLength(1);
    expect(stub.calls[0].title).toBe("Bearings");
  });
});

// ---------------------------------------------------------------------------
// 6. fires when tab is unfocused (but visible)
// ---------------------------------------------------------------------------

describe("maybeFireTurnNotification — tab unfocused", () => {
  it("fires when hasFocus() is false and visibilityState is 'visible'", () => {
    const stub = stubNotification("granted", false, "visible");
    setNotifyOnComplete(true);
    maybeFireTurnNotification();
    expect(stub.calls).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 7. setNotifyOnComplete / getNotifyOnComplete round-trip
// ---------------------------------------------------------------------------

describe("setNotifyOnComplete / getNotifyOnComplete", () => {
  it("defaults to false", () => {
    expect(getNotifyOnComplete()).toBe(false);
  });

  it("round-trips true", () => {
    setNotifyOnComplete(true);
    expect(getNotifyOnComplete()).toBe(true);
  });

  it("round-trips false", () => {
    setNotifyOnComplete(true);
    setNotifyOnComplete(false);
    expect(getNotifyOnComplete()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 8. requestNotifyPermission returns "denied" when Notification absent
// ---------------------------------------------------------------------------

describe("requestNotifyPermission — no Notification API", () => {
  it("returns denied immediately", async () => {
    clearNotification();
    const result = await requestNotifyPermission();
    expect(result).toBe("denied");
  });
});

// ---------------------------------------------------------------------------
// Additional: requestNotifyPermission delegates to Notification.requestPermission
// ---------------------------------------------------------------------------

describe("requestNotifyPermission — with Notification API", () => {
  it("calls Notification.requestPermission and returns its result", async () => {
    const stub = stubNotification("granted", true, "visible");
    const result = await requestNotifyPermission();
    expect(stub.requestPermission).toHaveBeenCalled();
    expect(result).toBe("granted");
  });
});
