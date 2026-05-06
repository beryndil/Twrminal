/**
 * Tests for :mod:`stores/pending.svelte.ts` — pending-operations store.
 *
 * Acceptance criteria covered:
 * - Chord toggle: toggleCard() flips open flag (used by Ctrl+Shift+O handler).
 * - Badge visibility: ops.length drives the badge (badge hidden at 0).
 * - Age tick: started_at parses correctly for the age label.
 * - Right-click action surface: action ids are wired through context-menu
 *   registry (verified via import check of PENDING_OPERATION_ACTIONS).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  _resetForTests,
  closeCard,
  openCard,
  pendingOpsStore,
  refreshOps,
  toggleCard,
} from "../pending.svelte";
import { parsePendingToml } from "../../api/pendingOps";
import {
  MENU_ACTION_PENDING_OPERATION_COPY_COMMAND,
  MENU_ACTION_PENDING_OPERATION_COPY_NAME,
  MENU_ACTION_PENDING_OPERATION_DISMISS,
  MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR,
  MENU_ACTION_PENDING_OPERATION_RESOLVE,
  MENU_TARGET_PENDING_OPERATION,
} from "../../config";
import { actionsForTarget } from "../../context-menu/registry";

beforeEach(() => {
  _resetForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---- Chord toggle -----------------------------------------------------------

describe("toggleCard", () => {
  it("opens the card when closed", () => {
    expect(pendingOpsStore.open).toBe(false);
    toggleCard();
    expect(pendingOpsStore.open).toBe(true);
  });

  it("closes the card when open", () => {
    openCard();
    toggleCard();
    expect(pendingOpsStore.open).toBe(false);
  });

  it("openCard / closeCard set state directly", () => {
    openCard();
    expect(pendingOpsStore.open).toBe(true);
    closeCard();
    expect(pendingOpsStore.open).toBe(false);
  });
});

// ---- Badge visibility -------------------------------------------------------

describe("badge visibility (ops count)", () => {
  it("ops is empty on boot — badge would be hidden", () => {
    expect(pendingOpsStore.ops).toHaveLength(0);
  });

  it("ops reflects parsed pending operations after refresh", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          path: "/proj/.bearings/pending.toml",
          content: `[ops.my-task]\ndescription = "test"\nstarted_at = "2024-01-01T00:00:00Z"\n`,
          size: 100,
          truncated: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    await refreshOps("/proj");
    expect(pendingOpsStore.ops).toHaveLength(1);
    expect(pendingOpsStore.ops[0].name).toBe("my-task");
  });

  it("404 from fs/read yields empty ops (no pending.toml)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    await refreshOps("/proj");
    expect(pendingOpsStore.ops).toHaveLength(0);
    expect(pendingOpsStore.error).toBeNull();
  });

  it("null workingDir clears ops without fetching", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await refreshOps(null);
    expect(pendingOpsStore.ops).toHaveLength(0);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

// ---- Age tick (TOML parsing) ------------------------------------------------

describe("parsePendingToml — age / started_at", () => {
  it("parses a single op with started_at", () => {
    const content = `
[ops.deploy-frontend]
description = "Deploy to production"
started_at = "2024-06-01T10:00:00Z"
`;
    const ops = parsePendingToml(content);
    expect(ops).toHaveLength(1);
    expect(ops[0].started_at).toBe("2024-06-01T10:00:00Z");
    // started_at must be parseable by Date
    expect(isNaN(new Date(ops[0].started_at).getTime())).toBe(false);
  });

  it("parses optional command and dir fields", () => {
    const content = `
[ops.run-tests]
description = "Run the full test suite"
started_at = "2024-06-01T10:00:00Z"
command = "uv run pytest"
dir = "/home/user/project"
`;
    const ops = parsePendingToml(content);
    expect(ops[0].command).toBe("uv run pytest");
    expect(ops[0].dir).toBe("/home/user/project");
  });

  it("handles ops with hyphened names", () => {
    const content = `
[ops.my-long-op-name]
description = "Long running task"
started_at = "2024-06-01T00:00:00Z"
`;
    const ops = parsePendingToml(content);
    expect(ops[0].name).toBe("my-long-op-name");
  });

  it("handles quoted op names", () => {
    const content = `
[ops."name with spaces"]
description = "A named op"
started_at = "2024-06-01T00:00:00Z"
`;
    const ops = parsePendingToml(content);
    expect(ops[0].name).toBe("name with spaces");
  });

  it("returns empty array for empty content", () => {
    expect(parsePendingToml("")).toHaveLength(0);
    expect(parsePendingToml("# just a comment")).toHaveLength(0);
  });

  it("sorts oldest-first by started_at", () => {
    const content = `
[ops.newer]
description = "newer op"
started_at = "2024-06-02T00:00:00Z"

[ops.older]
description = "older op"
started_at = "2024-06-01T00:00:00Z"
`;
    const ops = parsePendingToml(content);
    expect(ops[0].name).toBe("older");
    expect(ops[1].name).toBe("newer");
  });

  it("skips entries missing started_at", () => {
    const content = `
[ops.incomplete]
description = "No timestamp"
`;
    const ops = parsePendingToml(content);
    expect(ops).toHaveLength(0);
  });
});

// ---- Right-click action surface ---------------------------------------------

describe("pending_operation context-menu actions", () => {
  it("registry exposes all five action ids for MENU_TARGET_PENDING_OPERATION", () => {
    const actions = actionsForTarget(MENU_TARGET_PENDING_OPERATION);
    const ids = actions.map((a) => a.id);
    expect(ids).toContain(MENU_ACTION_PENDING_OPERATION_RESOLVE);
    expect(ids).toContain(MENU_ACTION_PENDING_OPERATION_DISMISS);
    expect(ids).toContain(MENU_ACTION_PENDING_OPERATION_COPY_NAME);
    expect(ids).toContain(MENU_ACTION_PENDING_OPERATION_COPY_COMMAND);
    expect(ids).toContain(MENU_ACTION_PENDING_OPERATION_OPEN_IN_EDITOR);
  });

  it("resolve is in the primary section, dismiss in destructive", () => {
    const actions = actionsForTarget(MENU_TARGET_PENDING_OPERATION);
    const resolve = actions.find((a) => a.id === MENU_ACTION_PENDING_OPERATION_RESOLVE);
    const dismiss = actions.find((a) => a.id === MENU_ACTION_PENDING_OPERATION_DISMISS);
    expect(resolve?.section).toBe("primary");
    expect(dismiss?.section).toBe("destructive");
    expect(dismiss?.destructive).toBe(true);
  });
});
