/**
 * Unit tests for ``ConfirmDialog`` — focus management on open.
 *
 * Covers gap-cycle-10-005 acceptance criteria:
 *
 * - ``destructive=true`` (default): Cancel button receives focus on
 *   first paint so a stray Enter cancels rather than confirming.
 * - ``destructive=false``: Confirm button receives focus so the user
 *   can keyboard-confirm without mouse travel.
 *
 * Behavior anchor: ``docs/behavior/modals.md`` §"ConfirmDialog focus".
 */
import { cleanup, render } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConfirmDialog from "../ConfirmDialog.svelte";

afterEach(() => {
  cleanup();
});

describe("ConfirmDialog — focus management on open (gap-cycle-10-005)", () => {
  it("destructive=true: Cancel button receives focus on open", async () => {
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session? This cannot be undone.",
        destructive: true,
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    const cancelBtn = getByTestId("confirm-dialog-cancel");
    // queueMicrotask fires after the current task; one Promise tick is
    // sufficient to drain it in jsdom.
    await new Promise<void>((resolve) => queueMicrotask(resolve));
    expect(document.activeElement).toBe(cancelBtn);
  });

  it("destructive=false: Confirm button receives focus on open", async () => {
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Apply this change?",
        destructive: false,
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    const confirmBtn = getByTestId("confirm-dialog-confirm");
    await new Promise<void>((resolve) => queueMicrotask(resolve));
    expect(document.activeElement).toBe(confirmBtn);
  });

  it("destructive defaults to true when prop is omitted: Cancel focused", async () => {
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "This cannot be undone.",
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    const cancelBtn = getByTestId("confirm-dialog-cancel");
    await new Promise<void>((resolve) => queueMicrotask(resolve));
    expect(document.activeElement).toBe(cancelBtn);
  });
});
