/**
 * Unit tests for ``ConfirmDialog`` — focus management on open,
 * async pending state, accessible name, and per-session suppression.
 *
 * Covers gap-cycle-10-005 acceptance criteria:
 *
 * - ``destructive=true`` (default): Cancel button receives focus on
 *   first paint so a stray Enter cancels rather than confirming.
 * - ``destructive=false``: Confirm button receives focus so the user
 *   can keyboard-confirm without mouse travel.
 *
 * Covers gap-cycle-10-006 acceptance criteria:
 *
 * - Synchronous ``onConfirm`` still fires correctly and doesn't linger
 *   in pending state.
 * - Async ``onConfirm`` disables both buttons and shows "…" while in
 *   flight; re-enables after the promise resolves.
 * - Rejected promise surfaces the error message inline and re-enables
 *   buttons without closing the dialog.
 *
 * Covers gap-cycle-12-001 acceptance criteria:
 *
 * - The ``<div role="alertdialog">`` uses ``aria-labelledby`` referencing
 *   the message element's id so the dialog's accessible name is the
 *   operator-supplied ``message`` prop verbatim — not a generic literal.
 *
 * Covers F9-rt-25 acceptance criteria:
 *
 * - ``showSuppressCheckbox=false`` (default): no checkbox rendered.
 * - ``showSuppressCheckbox=true``: checkbox + label render in the dialog.
 * - Confirming without ticking calls ``onConfirm``, not
 *   ``onConfirmAndSuppress``.
 * - Confirming WITH the checkbox ticked calls ``onConfirmAndSuppress``
 *   when provided; falls back to ``onConfirm`` when it is not.
 * - Cancelling (with or without the box ticked) calls ``onCancel`` only;
 *   never triggers a confirm path.
 *
 * Behavior anchor: ``docs/behavior/context-menus.md`` §"Common behavior
 * — Destructive entries" and ``docs/behavior/modals.md``.
 */
import { cleanup, fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CONTEXT_MENU_STRINGS } from "../../../config";

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

describe("ConfirmDialog — accessible name via aria-labelledby (gap-cycle-12-001)", () => {
  it("alertdialog accessible name is the message prop verbatim", () => {
    const message = 'Delete "foo"?';
    const { getByRole } = render(ConfirmDialog, {
      props: {
        message,
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    const dialog = getByRole("alertdialog");
    expect(dialog).toHaveAccessibleName(message);
  });

  it("accessible name updates when message prop changes between renders", () => {
    const { getByRole, rerender } = render(ConfirmDialog, {
      props: {
        message: "Delete session 'alpha'?",
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    expect(getByRole("alertdialog")).toHaveAccessibleName("Delete session 'alpha'?");

    rerender({
      message: "Dismiss 'pending op X'?",
      onConfirm: vi.fn(),
      onCancel: vi.fn(),
    });
    expect(getByRole("alertdialog")).toHaveAccessibleName("Dismiss 'pending op X'?");
  });
});

describe("ConfirmDialog — async pending state (gap-cycle-10-006)", () => {
  it("synchronous onConfirm fires once and buttons re-enable immediately after", async () => {
    const onConfirm = vi.fn();
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session?",
        onConfirm,
        onCancel: vi.fn(),
      },
    });
    fireEvent.click(getByTestId("confirm-dialog-confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    // After sync confirm, pending clears — buttons must be enabled.
    await waitFor(() => {
      expect(getByTestId("confirm-dialog-confirm")).not.toBeDisabled();
      expect(getByTestId("confirm-dialog-cancel")).not.toBeDisabled();
    });
  });

  it("async onConfirm disables both buttons and shows '…' while in flight, re-enables on resolve", async () => {
    let resolveFn!: () => void;
    const deferred = new Promise<void>((r) => {
      resolveFn = r;
    });
    const onConfirm = vi.fn(() => deferred);

    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session?",
        onConfirm,
        onCancel: vi.fn(),
      },
    });

    fireEvent.click(getByTestId("confirm-dialog-confirm"));

    // pending = true is set synchronously before the first await inside
    // handleConfirm, so the DOM update is observable here.
    const confirmBtn = getByTestId("confirm-dialog-confirm");
    const cancelBtn = getByTestId("confirm-dialog-cancel");
    await waitFor(() => {
      expect(confirmBtn).toBeDisabled();
      expect(cancelBtn).toBeDisabled();
      expect(confirmBtn).toHaveTextContent("…");
    });

    // Resolve; buttons must re-enable.
    resolveFn();
    await waitFor(() => {
      expect(confirmBtn).not.toBeDisabled();
      expect(cancelBtn).not.toBeDisabled();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("async onConfirm rejection surfaces error inline and re-enables buttons", async () => {
    let rejectFn!: (err: Error) => void;
    const deferred = new Promise<void>((_, r) => {
      rejectFn = r;
    });
    const onConfirm = vi.fn(() => deferred);

    const { getByTestId, queryByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session?",
        onConfirm,
        onCancel: vi.fn(),
      },
    });

    fireEvent.click(getByTestId("confirm-dialog-confirm"));

    rejectFn(new Error("Network error"));

    await waitFor(() => {
      expect(queryByTestId("confirm-dialog-error")).not.toBeNull();
    });
    expect(getByTestId("confirm-dialog-error")).toHaveTextContent("Network error");
    // Buttons re-enabled after rejection — dialog stays open.
    expect(getByTestId("confirm-dialog-confirm")).not.toBeDisabled();
    expect(getByTestId("confirm-dialog-cancel")).not.toBeDisabled();
  });
});

describe("ConfirmDialog — per-session suppression checkbox (F9-rt-25)", () => {
  it("showSuppressCheckbox=false (default): no checkbox rendered", () => {
    const { queryByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session? This cannot be undone.",
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    expect(queryByTestId("confirm-dialog-suppress-checkbox")).toBeNull();
    expect(queryByTestId("confirm-dialog-suppress-label")).toBeNull();
  });

  it("showSuppressCheckbox=true: checkbox + label render inside the dialog", () => {
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session? This cannot be undone.",
        showSuppressCheckbox: true,
        onConfirm: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    const checkbox = getByTestId("confirm-dialog-suppress-checkbox");
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).toHaveAttribute("type", "checkbox");
    expect(checkbox).not.toBeChecked();
    const label = getByTestId("confirm-dialog-suppress-label");
    expect(label).toHaveTextContent(CONTEXT_MENU_STRINGS.confirmSuppressCheckboxLabel);
  });

  it("confirm WITHOUT ticking calls onConfirm, not onConfirmAndSuppress", async () => {
    const onConfirm = vi.fn();
    const onConfirmAndSuppress = vi.fn();
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session? This cannot be undone.",
        showSuppressCheckbox: true,
        onConfirm,
        onConfirmAndSuppress,
        onCancel: vi.fn(),
      },
    });
    fireEvent.click(getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
    expect(onConfirmAndSuppress).not.toHaveBeenCalled();
  });

  it("confirm WITH checkbox ticked calls onConfirmAndSuppress when provided", async () => {
    const onConfirm = vi.fn();
    const onConfirmAndSuppress = vi.fn();
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session? This cannot be undone.",
        showSuppressCheckbox: true,
        onConfirm,
        onConfirmAndSuppress,
        onCancel: vi.fn(),
      },
    });
    fireEvent.click(getByTestId("confirm-dialog-suppress-checkbox"));
    fireEvent.click(getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(onConfirmAndSuppress).toHaveBeenCalledTimes(1));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("confirm WITH checkbox ticked falls back to onConfirm when onConfirmAndSuppress absent", async () => {
    const onConfirm = vi.fn();
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session? This cannot be undone.",
        showSuppressCheckbox: true,
        onConfirm,
        onCancel: vi.fn(),
      },
    });
    fireEvent.click(getByTestId("confirm-dialog-suppress-checkbox"));
    fireEvent.click(getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
  });

  it("Cancel with checkbox ticked calls onCancel only; never confirms", async () => {
    const onConfirm = vi.fn();
    const onConfirmAndSuppress = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(ConfirmDialog, {
      props: {
        message: "Delete this session? This cannot be undone.",
        showSuppressCheckbox: true,
        onConfirm,
        onConfirmAndSuppress,
        onCancel,
      },
    });
    fireEvent.click(getByTestId("confirm-dialog-suppress-checkbox"));
    fireEvent.click(getByTestId("confirm-dialog-cancel"));
    await waitFor(() => expect(onCancel).toHaveBeenCalledTimes(1));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onConfirmAndSuppress).not.toHaveBeenCalled();
  });
});
