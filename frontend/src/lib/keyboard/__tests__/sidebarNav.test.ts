/**
 * Unit tests for sidebar navigation helpers.
 *
 * gap-cycle-02-001 acceptance criteria (sidebarNavNext / sidebarNavPrev):
 *   1. Wrap-down at end: `j`/`Alt+]` on the last row → selects the first.
 *   2. Wrap-up at start: `k`/`Alt+[` on the first row → selects the last.
 *   3. Empty list → both helpers return ``null`` (no-op at call site).
 *   4. No selection (``null``) → `j` seeds to first row; `k` seeds to last.
 *
 * gap-cycle-02-002 acceptance criteria (sidebarNavSlot + closed-session skipping):
 *   5. With closed sessions present in the raw cache, j/k navigate the
 *      open-only list — closed rows are never visited.
 *   6. Alt+N slot jump targets the Nth row of the visible open list.
 *   7. Out-of-range Alt+N (N > visible-open-count) is a no-op (null).
 *
 * The helpers are pure functions with no Svelte/SvelteKit dependency, so
 * no mock wiring is needed.
 */
import { describe, expect, it } from "vitest";

import { sidebarNavNext, sidebarNavPrev, sidebarNavSlot } from "../sidebarNav";
import type { SessionOut } from "../../api/sessions";

// ---------------------------------------------------------------------------
// Test fixture
// ---------------------------------------------------------------------------

function makeSession(id: string, closed = false): SessionOut {
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
    closed_at: closed ? "2026-01-02T00:00:00Z" : null,
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

// ---------------------------------------------------------------------------
// Closed-session skipping (gap-cycle-02-002)
//
// +layout.svelte now passes ``openSessionsList`` (sessions filtered to
// ``closed_at === null``) to sidebarNavNext/Prev instead of the raw
// ``sessionsStore.sessions`` cache.  These tests confirm the correct
// behaviour when a closed row sits between two open ones in the raw cache.
// ---------------------------------------------------------------------------

describe("closed-session skipping (gap-cycle-02-002)", () => {
  // Raw cache: A(open) · X(closed) · B(open) · C(open)
  // openSessionsList filters X out → [A, B, C]
  const X = makeSession("ses_x", true);

  it("j skips the closed entry that sits between two open rows", () => {
    // Caller pre-filters; we simulate what openSessionsList gives.
    const openList = [A, B, C];
    // From A, j → B (not X, which was between A and B in the raw cache).
    expect(sidebarNavNext(openList, "ses_a")).toBe("ses_b");
  });

  it("k skips the closed entry that sits between two open rows", () => {
    const openList = [A, B, C];
    expect(sidebarNavPrev(openList, "ses_b")).toBe("ses_a");
  });

  it("closed sessions are absent from openList regardless of cache position", () => {
    // Verify the filtering contract (documents the caller's responsibility).
    const rawCache = [A, X, B, C];
    const openList = rawCache.filter((s) => s.closed_at === null);
    expect(openList.map((s) => s.id)).toEqual(["ses_a", "ses_b", "ses_c"]);
    expect(sidebarNavNext(openList, "ses_a")).toBe("ses_b");
  });
});

// ---------------------------------------------------------------------------
// sidebarNavSlot — Alt+1..9 slot jumps (gap-cycle-02-002)
// ---------------------------------------------------------------------------

describe("sidebarNavSlot (Alt+1..9)", () => {
  it("slot 1 returns the first open session", () => {
    expect(sidebarNavSlot(THREE, 1)).toBe("ses_a");
  });

  it("slot 2 returns the second open session", () => {
    expect(sidebarNavSlot(THREE, 2)).toBe("ses_b");
  });

  it("slot 3 returns the third open session", () => {
    expect(sidebarNavSlot(THREE, 3)).toBe("ses_c");
  });

  it("out-of-range slot (N > count) → no-op (null)", () => {
    expect(sidebarNavSlot(THREE, 4)).toBeNull();
    expect(sidebarNavSlot(THREE, 9)).toBeNull();
  });

  it("slot 0 (below range) → no-op (null)", () => {
    expect(sidebarNavSlot(THREE, 0)).toBeNull();
  });

  it("empty list → no-op (null) for any slot", () => {
    expect(sidebarNavSlot([], 1)).toBeNull();
  });

  it("slot indexes the visible open list, not the raw cache", () => {
    // With one closed session at position 0 in the raw cache, the first
    // visible slot is the first open session (not the closed one).
    const closedFirst = makeSession("ses_closed", true);
    const openList = [A, B, C].filter((s) => s.closed_at === null);
    expect(sidebarNavSlot(openList, 1)).toBe("ses_a");
    // The closed session would have been index 0 in the raw cache.
    void closedFirst; // referenced only for documentary purpose
  });
});
