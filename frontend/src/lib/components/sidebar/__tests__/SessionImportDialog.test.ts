/**
 * Unit tests for ``SessionImportDialog``.
 *
 * Per ``docs/behavior/sessions.md`` §"Import contract" acceptance criteria:
 *
 * - Dialog submit on paste path: valid JSON in textarea → calls
 *   ``POST /api/sessions/import`` and invokes ``onImported`` on 201.
 * - 409 error is surfaced inline (``data-testid="session-import-error"``).
 * - Dialog dismiss invokes ``onCancel``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SessionImportDialog from "../SessionImportDialog.svelte";
import type { SessionOut } from "../../../api/sessions";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MOCK_SESSION: SessionOut = {
  id: "ses_abc123",
  kind: "chat",
  title: "Imported Session",
  description: null,
  session_instructions: null,
  working_dir: "/wd",
  model: "claude-sonnet-4-5",
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

const VALID_EXPORT = {
  session: MOCK_SESSION,
  messages: [],
  tool_calls: [],
  checkpoints: [],
  attachments: [],
};

// ---------------------------------------------------------------------------
// fetch mock setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockFetch201(): void {
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(JSON.stringify(MOCK_SESSION), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockFetch409(detail: string): void {
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(JSON.stringify({ detail }), {
      status: 409,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SessionImportDialog", () => {
  it("renders the dialog with textarea and buttons", () => {
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    expect(getByTestId("session-import-dialog")).toBeTruthy();
    expect(getByTestId("session-import-textarea")).toBeTruthy();
    expect(getByTestId("session-import-submit")).toBeTruthy();
    expect(getByTestId("session-import-cancel")).toBeTruthy();
  });

  it("calls onCancel when Cancel button is clicked", async () => {
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    await fireEvent.click(getByTestId("session-import-cancel"));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("calls onCancel when Escape is pressed", async () => {
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    await fireEvent.keyDown(getByTestId("session-import-dialog"), {
      key: "Escape",
    });
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("shows inline error when textarea is empty on submit", async () => {
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    await fireEvent.click(getByTestId("session-import-submit"));
    const err = getByTestId("session-import-error");
    expect(err.textContent).toContain("Paste or upload");
  });

  it("shows inline error on invalid JSON", async () => {
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    const textarea = getByTestId("session-import-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "not json {{{" } });
    await fireEvent.click(getByTestId("session-import-submit"));
    const err = getByTestId("session-import-error");
    expect(err.textContent).toContain("Invalid JSON");
  });

  it("calls importSessionJson and invokes onImported on 201 (paste path)", async () => {
    mockFetch201();
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    const textarea = getByTestId("session-import-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, {
      target: { value: JSON.stringify(VALID_EXPORT) },
    });
    await fireEvent.click(getByTestId("session-import-submit"));
    await waitFor(() => {
      expect(onImported).toHaveBeenCalledWith(MOCK_SESSION);
    });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions/import"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("surfaces 409 detail inline without closing the dialog", async () => {
    mockFetch409("session 'ses_abc123' already exists; pass ?force=true to overwrite");
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId, queryByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    const textarea = getByTestId("session-import-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, {
      target: { value: JSON.stringify(VALID_EXPORT) },
    });
    await fireEvent.click(getByTestId("session-import-submit"));
    await waitFor(() => {
      const err = getByTestId("session-import-error");
      expect(err.textContent).toContain("already exists");
    });
    // Dialog still open — onImported not called, onCancel not called
    expect(onImported).not.toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    expect(queryByTestId("session-import-dialog")).toBeTruthy();
  });

  it("dismisses on backdrop click", async () => {
    const onImported = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionImportDialog, {
      props: { onImported, onCancel },
    });
    await fireEvent.click(getByTestId("session-import-dialog-backdrop"));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
