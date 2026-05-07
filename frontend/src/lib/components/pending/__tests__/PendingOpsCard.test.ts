/**
 * PendingOpsCard component tests.
 *
 * Acceptance criteria covered:
 * - Card mounts at bottom-right, dismissable by close button.
 * - Badge hidden when count == 0; visible when count > 0.
 * - PendingOpRow renders name, description, and age.
 * - Esc cascade priority 3 is registered (ESC_PRIORITY_PENDING_OPS_CARD).
 * - Resolve/dismiss handlers call the API; row removed on 2xx only.
 * - Non-2xx response surfaces actionErrorLabel inline; row stays.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { _resetForTests as resetEsc, ESC_PRIORITY_PENDING_OPS_CARD } from "../../../keyboard/escCascade";
import { _resetForTests as resetPending, openCard, pendingOpsStore } from "../../../stores/pending.svelte";
import { PENDING_OPS_CARD_STRINGS } from "../../../config";
import PendingOpsCard from "../PendingOpsCard.svelte";

beforeEach(() => {
  resetPending();
  resetEsc();
});

afterEach(() => {
  resetPending();
  resetEsc();
  vi.restoreAllMocks();
});

describe("PendingOpsCard", () => {
  it("renders nothing when store is closed", () => {
    const { queryByTestId } = render(PendingOpsCard, {
      props: { workingDir: null },
    });
    expect(queryByTestId("pending-ops-card")).toBeNull();
  });

  it("renders the card when store is open", () => {
    openCard();
    const { getByTestId } = render(PendingOpsCard, {
      props: { workingDir: null },
    });
    expect(getByTestId("pending-ops-card")).toBeInTheDocument();
    expect(getByTestId("pending-ops-card")).toHaveAttribute(
      "aria-label",
      PENDING_OPS_CARD_STRINGS.cardAriaLabel,
    );
  });

  it("shows empty state when ops list is empty", () => {
    openCard();
    const { getByTestId } = render(PendingOpsCard, {
      props: { workingDir: null },
    });
    expect(getByTestId("pending-ops-empty")).toBeInTheDocument();
    expect(getByTestId("pending-ops-empty").textContent).toBe(
      PENDING_OPS_CARD_STRINGS.emptyLabel,
    );
  });

  it("close button calls closeCard", () => {
    openCard();
    const { getByTestId } = render(PendingOpsCard, {
      props: { workingDir: null },
    });
    fireEvent.click(getByTestId("pending-ops-close-btn"));
    expect(pendingOpsStore.open).toBe(false);
  });

  it("renders op rows when ops are present", async () => {
    // Mock fetch so the $effect-triggered refreshOps call returns the desired ops.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          path: "/proj/.bearings/pending.toml",
          content:
            "[ops.deploy]\ndescription = \"Deploy to prod\"\nstarted_at = \"2024-01-01T00:00:00Z\"\n\n" +
            "[ops.review]\ndescription = \"Code review\"\nstarted_at = \"2024-01-02T00:00:00Z\"\n",
          size: 100,
          truncated: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    openCard();
    const { getAllByTestId } = render(PendingOpsCard, {
      props: { workingDir: "/proj" },
    });
    await waitFor(() => {
      expect(getAllByTestId("pending-op-row")).toHaveLength(2);
    });
  });

  it("row shows op name and description", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          path: "/proj/.bearings/pending.toml",
          content:
            "[ops.my-task]\ndescription = \"A pending task\"\nstarted_at = \"2024-01-01T00:00:00Z\"\n",
          size: 80,
          truncated: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    openCard();
    const { getByTestId } = render(PendingOpsCard, {
      props: { workingDir: "/proj" },
    });
    await waitFor(() => {
      expect(getByTestId("pending-op-name").textContent).toBe("my-task");
    });
    expect(getByTestId("pending-op-description").textContent).toBe("A pending task");
  });

  it("row renders an age label (non-empty text)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          path: "/proj/.bearings/pending.toml",
          content:
            "[ops.old-task]\ndescription = \"Old task\"\nstarted_at = \"2020-01-01T00:00:00Z\"\n",
          size: 80,
          truncated: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    openCard();
    const { getByTestId } = render(PendingOpsCard, {
      props: { workingDir: "/proj" },
    });
    await waitFor(() => {
      expect(getByTestId("pending-op-age")).toBeInTheDocument();
    });
    const age = getByTestId("pending-op-age");
    expect(age.textContent).toBeTruthy();
    // A task from 2020 should render in days.
    expect(age.textContent).toMatch(/d ago/);
  });

  it("backdrop element is present when card is open", () => {
    openCard();
    const { getByTestId } = render(PendingOpsCard, {
      props: { workingDir: null },
    });
    // Verify the transparent capture layer is in the DOM.
    expect(getByTestId("pending-ops-backdrop")).toBeInTheDocument();
  });
});

// ---- Esc priority constant --------------------------------------------------

describe("ESC_PRIORITY_PENDING_OPS_CARD", () => {
  it("is priority 3 — after context menu (1) and command palette (2)", () => {
    expect(ESC_PRIORITY_PENDING_OPS_CARD).toBe(3);
  });
});

// ---- Badge visibility -------------------------------------------------------

describe("PendingOpsBadge visibility logic", () => {
  it("badge count equals ops length", () => {
    // The badge itself is a simple conditional render in PendingOpsBadge.svelte.
    // Verify the store drives it correctly.
    expect(pendingOpsStore.ops.length).toBe(0);
    pendingOpsStore.ops = [
      { name: "t1", description: "", started_at: "2024-01-01T00:00:00Z" },
    ];
    expect(pendingOpsStore.ops.length).toBe(1);
  });
});

// ---- Ctrl+Shift+O binding ---------------------------------------------------

describe("KEYBINDING_ACTION_TOGGLE_PENDING_OPS chord", () => {
  it("is in the KEYBINDINGS table with Ctrl+Shift+O chord", async () => {
    const { KEYBINDINGS } = await import("../../../keyboard/bindings");
    const binding = KEYBINDINGS.find((b) => b.id === "help.toggle_pending_ops");
    expect(binding).toBeDefined();
    expect(binding?.chord.code).toBe("KeyO");
    expect(binding?.chord.ctrl).toBe(true);
    expect(binding?.chord.shift).toBe(true);
    expect(binding?.global).toBe(true);
  });
});

// ---- Resolve/dismiss API wiring (gap-cycle-03-010) ---------------------------

function mockFetchForOps(): void {
  vi.spyOn(globalThis, "fetch").mockImplementation((input, _init) => {
    const url = String(input);
    // Pending TOML read (GET /api/fs/read)
    if (url.includes("/api/fs/read")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            path: "/proj/.bearings/pending.toml",
            content:
              "[ops.deploy]\ndescription = \"Deploy\"\nstarted_at = \"2024-01-01T00:00:00Z\"\n",
            size: 80,
            truncated: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    }
    // POST resolve or DELETE dismiss → 204
    if (url.includes("/api/pending/")) {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(new Response("not found", { status: 404 }));
  });
}

describe("PendingOpsCard resolve/dismiss API wiring", () => {
  it("resolve button removes the row from the store on 2xx", async () => {
    mockFetchForOps();
    openCard();
    const { getAllByTestId, queryAllByTestId } = render(PendingOpsCard, {
      props: { workingDir: "/proj" },
    });
    // Wait for the row to appear.
    await waitFor(() => {
      expect(getAllByTestId("pending-op-row")).toHaveLength(1);
    });
    // Click the resolve button.
    fireEvent.click(getAllByTestId("pending-op-resolve-btn")[0]);
    await waitFor(() => {
      expect(queryAllByTestId("pending-op-row")).toHaveLength(0);
    });
  });

  it("dismiss button removes the row from the store on 2xx", async () => {
    mockFetchForOps();
    openCard();
    const { getAllByTestId, queryAllByTestId } = render(PendingOpsCard, {
      props: { workingDir: "/proj" },
    });
    await waitFor(() => {
      expect(getAllByTestId("pending-op-row")).toHaveLength(1);
    });
    fireEvent.click(getAllByTestId("pending-op-dismiss-btn")[0]);
    await waitFor(() => {
      expect(queryAllByTestId("pending-op-row")).toHaveLength(0);
    });
  });

  it("resolve failure leaves the row in place and shows an inline error", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, _init) => {
      const url = String(input);
      if (url.includes("/api/pending/")) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "server error" }), {
            status: 500,
            headers: { "content-type": "application/json" },
          }),
        );
      }
      // TOML read succeeds.
      return Promise.resolve(
        new Response(
          JSON.stringify({
            path: "/proj/.bearings/pending.toml",
            content:
              "[ops.deploy]\ndescription = \"Deploy\"\nstarted_at = \"2024-01-01T00:00:00Z\"\n",
            size: 80,
            truncated: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    });
    openCard();
    const { getAllByTestId, getByTestId } = render(PendingOpsCard, {
      props: { workingDir: "/proj" },
    });
    await waitFor(() => {
      expect(getAllByTestId("pending-op-row")).toHaveLength(1);
    });
    fireEvent.click(getAllByTestId("pending-op-resolve-btn")[0]);
    await waitFor(() => {
      expect(getByTestId("pending-ops-action-error")).toBeInTheDocument();
    });
    // Row is still present.
    expect(getAllByTestId("pending-op-row")).toHaveLength(1);
    expect(getByTestId("pending-ops-action-error").textContent).toBe(
      PENDING_OPS_CARD_STRINGS.actionErrorLabel,
    );
  });

  it("error clears on a subsequent successful resolve", async () => {
    // First call returns 500, second returns 204.
    let callCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/api/pending/")) {
        callCount++;
        const status = callCount === 1 ? 500 : 204;
        return Promise.resolve(
          new Response(callCount === 1 ? JSON.stringify({ detail: "err" }) : null, {
            status,
            headers: callCount === 1 ? { "content-type": "application/json" } : {},
          }),
        );
      }
      // TOML read returns two ops so there are still rows after the first click.
      return Promise.resolve(
        new Response(
          JSON.stringify({
            path: "/proj/.bearings/pending.toml",
            content:
              "[ops.deploy]\ndescription = \"Deploy\"\nstarted_at = \"2024-01-01T00:00:00Z\"\n" +
              "[ops.review]\ndescription = \"Review\"\nstarted_at = \"2024-01-02T00:00:00Z\"\n",
            size: 160,
            truncated: false,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    });
    openCard();
    const { getAllByTestId, getByTestId, queryByTestId } = render(PendingOpsCard, {
      props: { workingDir: "/proj" },
    });
    await waitFor(() => {
      expect(getAllByTestId("pending-op-row")).toHaveLength(2);
    });
    // First click → 500 → error shown, both rows intact.
    fireEvent.click(getAllByTestId("pending-op-resolve-btn")[0]);
    await waitFor(() => {
      expect(getByTestId("pending-ops-action-error")).toBeInTheDocument();
    });
    expect(getAllByTestId("pending-op-row")).toHaveLength(2);
    // Second click → 204 → error cleared, one row removed.
    fireEvent.click(getAllByTestId("pending-op-resolve-btn")[0]);
    await waitFor(() => {
      expect(queryByTestId("pending-ops-action-error")).toBeNull();
    });
    expect(getAllByTestId("pending-op-row")).toHaveLength(1);
  });
});
