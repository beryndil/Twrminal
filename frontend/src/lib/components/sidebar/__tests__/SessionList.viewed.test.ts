/**
 * Tests for the unviewed-dot ``visibilitychange`` wiring in
 * :class:`SessionList`.
 *
 * When the browser tab becomes visible while a session row is already
 * selected, ``SessionList`` fires ``POST /api/sessions/{id}/viewed`` so
 * the amber dot clears on all open tabs/windows via the sessions-broadcast
 * WebSocket. This test covers that contract without spinning up a real
 * backend: it spies on ``markSessionViewed`` and simulates the browser
 * ``visibilitychange`` event.
 */
import { render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SessionList from "../SessionList.svelte";
import { _resetForTests as resetSessionsStore } from "../../../stores/sessions.svelte";
import { _resetForTests as resetTagsStore } from "../../../stores/tags.svelte";

// Keep the sessions API mock self-contained so it doesn't pollute
// other test files in this directory.
vi.mock("../../../api/sessions", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../../api/sessions")>();
  return {
    ...mod,
    markSessionViewed: vi.fn().mockResolvedValue({}),
    listSessions: vi.fn().mockResolvedValue([]),
    reopenSession: vi.fn().mockResolvedValue({}),
  };
});

vi.mock("../../../api/tags", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../../api/tags")>();
  return { ...mod, listTags: vi.fn().mockResolvedValue([]) };
});

beforeEach(() => {
  resetSessionsStore();
  resetTagsStore();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("SessionList — visibilitychange marks selected session viewed", () => {
  it("fires markSessionViewed when the tab becomes visible and a session is selected", async () => {
    const { markSessionViewed } = await import("../../../api/sessions");

    // Mount with a selected session id.
    render(SessionList, { props: { selectedSessionId: "ses_xyz" } });

    // Simulate tab becoming visible.
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));

    await waitFor(() => {
      expect(markSessionViewed).toHaveBeenCalledWith("ses_xyz");
    });
  });

  it("does NOT fire markSessionViewed when no session is selected", async () => {
    const { markSessionViewed } = await import("../../../api/sessions");

    render(SessionList, { props: { selectedSessionId: null } });

    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));

    // Give any async work a tick to settle.
    await new Promise((r) => setTimeout(r, 0));
    expect(markSessionViewed).not.toHaveBeenCalled();
  });
});
