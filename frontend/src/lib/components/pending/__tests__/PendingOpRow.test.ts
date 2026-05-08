/**
 * Component tests for ``PendingOpRow`` — stale-target detection via
 * ``pendingOpsStore.ops`` (gap-cycle-15-004).
 *
 * When a sister tab resolves or dismisses a pending-op row between
 * the user pressing the mouse button and the ``contextmenu`` event
 * firing, ``use:contextMenu`` should receive ``stale: true`` so the
 * menu opens with every action greyed and the doc-mandated
 * ``data-testid="context-menu-stale-caption"`` visible.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { flushSync } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  _resetForTests as resetContextMenu,
  contextMenuStore,
} from "../../../context-menu/store.svelte";
import { _resetForTests as resetPending, pendingOpsStore } from "../../../stores/pending.svelte";
import type { PendingOp } from "../../../api/pendingOps";

import PendingOpRow from "../PendingOpRow.svelte";

function op(overrides: Partial<PendingOp> = {}): PendingOp {
  return {
    name: "deploy",
    description: "Deploy to prod",
    started_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  resetPending();
  resetContextMenu();
});

afterEach(() => {
  resetPending();
  resetContextMenu();
  vi.restoreAllMocks();
});

describe("PendingOpRow — stale-target detection (gap-cycle-15-004)", () => {
  it("right-clicking when op is absent from pendingOpsStore passes stale: true", async () => {
    // pendingOpsStore.ops is [] after reset — the op is not present.
    const { getByTestId } = render(PendingOpRow, {
      props: {
        op: op({ name: "deploy" }),
        onResolve: vi.fn(),
        onDismiss: vi.fn(),
      },
    });
    flushSync();
    await fireEvent.contextMenu(getByTestId("pending-op-row"));
    expect(contextMenuStore.open?.stale).toBe(true);
  });

  it("right-clicking when op is present in pendingOpsStore passes stale: false", async () => {
    // Seed the op before mounting so the derived value starts false.
    flushSync(() => {
      pendingOpsStore.ops = [op({ name: "deploy" })];
    });
    const { getByTestId } = render(PendingOpRow, {
      props: {
        op: op({ name: "deploy" }),
        onResolve: vi.fn(),
        onDismiss: vi.fn(),
      },
    });
    flushSync();
    await fireEvent.contextMenu(getByTestId("pending-op-row"));
    expect(contextMenuStore.open?.stale).toBe(false);
  });

  it("stale flag transitions to true when op is removed from the store after mount", async () => {
    // Start with the op present.
    flushSync(() => {
      pendingOpsStore.ops = [op({ name: "deploy" })];
    });
    const { getByTestId } = render(PendingOpRow, {
      props: {
        op: op({ name: "deploy" }),
        onResolve: vi.fn(),
        onDismiss: vi.fn(),
      },
    });
    flushSync();
    // Simulate a sister tab resolving/dismissing the op (store pruned on resolve).
    flushSync(() => {
      pendingOpsStore.ops = [];
    });
    await fireEvent.contextMenu(getByTestId("pending-op-row"));
    expect(contextMenuStore.open?.stale).toBe(true);
  });
});
