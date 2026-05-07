/**
 * Unit tests for sidebar wrap-around navigation helpers (gap-cycle-02-001).
 *
 * Acceptance criteria:
 *   1. Wrap-down at end: `j`/`Alt+]` on the last row → selects the first.
 *   2. Wrap-up at start: `k`/`Alt+[` on the first row → selects the last.
 *   3. Empty list → both helpers return ``null`` (no-op at call site).
 *   4. No selection (``null``) → `j` seeds to first row; `k` seeds to last.
 *
 * The helpers are pure functions with no Svelte/SvelteKit dependency, so
 * no mock wiring is needed.
 */
import { describe, expect, it } from "vitest";

import { sidebarNavNext, sidebarNavPrev } from "../sidebarNav";
import type { SessionOut } from "../../api/sessions";

// ---------------------------------------------------------------------------
// Test fixture
// ---------------------------------------------------------------------------

function makeSession(id: string): SessionOut {
  return {
    id,
    kind: "chat",
    title: id,
    description: null,
    session_instructions: null,
    working_dir: "/wd",
    model: "sonnet",
    permission_mode: null,
    max_budget_usd: null,
    total_cost_usd: 0,
    message_count: 0,
    last_context_pct: null,
    last_context_tokens: null,
    last_context_max: null,
    pinned: false,
    error_pending: false,
    checklist_item_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_viewed_at: null,
    last_completed_at: null,
    closed_at: null,
    closing_summary: null,
  };
}

const A = makeSession("ses_a");
const B = makeSession("ses_b");
const C = makeSession("ses_c");
const THREE = [A, B, C] as const;

// ---------------------------------------------------------------------------
// sidebarNavNext — j / Alt+]
// ---------------------------------------------------------------------------

describe("sidebarNavNext (j / Alt+])", () => {
  it("wrap-down at end: last row wraps to first row", () => {
    expect(sidebarNavNext(THREE, "ses_c")).toBe("ses_a");
  });

  it("normal advance: first row → second row", () => {
    expect(sidebarNavNext(THREE, "ses_a")).toBe("ses_b");
  });

  it("normal advance: second row → third row", () => {
    expect(sidebarNavNext(THREE, "ses_b")).toBe("ses_c");
  });

  it("empty list → no-op (null) regardless of currentId", () => {
    expect(sidebarNavNext([], null)).toBeNull();
    expect(sidebarNavNext([], "ses_a")).toBeNull();
  });

  it("no selection (null) → seeds to first row", () => {
    expect(sidebarNavNext(THREE, null)).toBe("ses_a");
  });

  it("single-item list wraps to itself", () => {
    expect(sidebarNavNext([A], "ses_a")).toBe("ses_a");
  });
});

// ---------------------------------------------------------------------------
// sidebarNavPrev — k / Alt+[
// ---------------------------------------------------------------------------

describe("sidebarNavPrev (k / Alt+[)", () => {
  it("wrap-up at start: first row wraps to last row", () => {
    expect(sidebarNavPrev(THREE, "ses_a")).toBe("ses_c");
  });

  it("normal retreat: third row → second row", () => {
    expect(sidebarNavPrev(THREE, "ses_c")).toBe("ses_b");
  });

  it("normal retreat: second row → first row", () => {
    expect(sidebarNavPrev(THREE, "ses_b")).toBe("ses_a");
  });

  it("empty list → no-op (null) regardless of currentId", () => {
    expect(sidebarNavPrev([], null)).toBeNull();
    expect(sidebarNavPrev([], "ses_a")).toBeNull();
  });

  it("no selection (null) → seeds to last row", () => {
    expect(sidebarNavPrev(THREE, null)).toBe("ses_c");
  });

  it("single-item list wraps to itself", () => {
    expect(sidebarNavPrev([A], "ses_a")).toBe("ses_a");
  });
});
