/**
 * Tests for the sidebar drag-and-drop batch import flow
 * (gap-cycle-08-005).
 *
 * Coverage required by acceptance criteria:
 *
 * 1. Drop event with two valid files calls ``importSessionJson`` twice
 *    and emits progress callbacks.
 * 2. Drop event with one invalid file surfaces the error inline without
 *    aborting remaining imports.
 *
 * The batch loop lives in ``$lib/utils/batchImport.ts``; tests target
 * that module directly so no full app-shell mount is needed.
 * ``importSessionJson`` is vi.mock'd at the module level so we control
 * success/failure without depending on fetch plumbing.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

import { importFromFiles } from "$lib/utils/batchImport";
import type { SessionOut } from "$lib/api/sessions";
import { ApiError } from "$lib/api/client";

// ---------------------------------------------------------------------------
// Mock importSessionJson so tests don't depend on fetch internals
// ---------------------------------------------------------------------------

vi.mock("$lib/api/sessions", () => ({
  importSessionJson: vi.fn(),
}));

// Import the mock AFTER vi.mock is hoisted so we get the mock reference
import { importSessionJson } from "$lib/api/sessions";
const mockImportSessionJson = vi.mocked(importSessionJson);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MOCK_SESSION_A: SessionOut = {
  id: "ses_drag_a",
  kind: "chat",
  title: "Drag Import A",
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

const MOCK_SESSION_B: SessionOut = {
  ...MOCK_SESSION_A,
  id: "ses_drag_b",
  title: "Drag Import B",
};

const VALID_EXPORT_A = JSON.stringify({
  session: MOCK_SESSION_A,
  messages: [],
  tool_calls: [],
  checkpoints: [],
  attachments: [],
});

const VALID_EXPORT_B = JSON.stringify({
  session: MOCK_SESSION_B,
  messages: [],
  tool_calls: [],
  checkpoints: [],
  attachments: [],
});

/** Construct a minimal ``File`` object backed by the given text content. */
function makeJsonFile(name: string, content: string): File {
  return new File([content], name, { type: "application/json" });
}

beforeEach(() => {
  mockImportSessionJson.mockReset();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("importFromFiles — drag-and-drop batch import", () => {
  it("calls importSessionJson once per file when both files are valid", async () => {
    mockImportSessionJson
      .mockResolvedValueOnce(MOCK_SESSION_A)
      .mockResolvedValueOnce(MOCK_SESSION_B);

    const progressCalls: Array<{ current: number; total: number }> = [];
    const result = await importFromFiles(
      [makeJsonFile("a.json", VALID_EXPORT_A), makeJsonFile("b.json", VALID_EXPORT_B)],
      (p) => {
        progressCalls.push({ current: p.current, total: p.total });
      },
    );

    // Both sessions imported, no errors
    expect(result.imported).toHaveLength(2);
    expect(result.imported[0].id).toBe("ses_drag_a");
    expect(result.imported[1].id).toBe("ses_drag_b");
    expect(result.errors).toHaveLength(0);

    // importSessionJson called exactly twice
    expect(mockImportSessionJson).toHaveBeenCalledTimes(2);
  });

  it("emits progress callback before each file import", async () => {
    mockImportSessionJson
      .mockResolvedValueOnce(MOCK_SESSION_A)
      .mockResolvedValueOnce(MOCK_SESSION_B);

    const progressSnapshots: Array<{ current: number; total: number }> = [];
    await importFromFiles(
      [makeJsonFile("a.json", VALID_EXPORT_A), makeJsonFile("b.json", VALID_EXPORT_B)],
      (p) => {
        progressSnapshots.push({ current: p.current, total: p.total });
      },
    );

    expect(progressSnapshots).toEqual([
      { current: 1, total: 2 },
      { current: 2, total: 2 },
    ]);
  });

  it("surfaces the error inline without aborting remaining imports (one invalid file)", async () => {
    // Only called for file 2 (file 1 is invalid JSON, never reaches the API)
    mockImportSessionJson.mockResolvedValueOnce(MOCK_SESSION_B);

    const result = await importFromFiles(
      [
        makeJsonFile("bad.json", "this is not json {{{"),
        makeJsonFile("b.json", VALID_EXPORT_B),
      ],
      () => {
        /* progress ignored */
      },
    );

    // Second file still imports despite first file failing
    expect(result.imported).toHaveLength(1);
    expect(result.imported[0].id).toBe("ses_drag_b");

    // Error recorded for the bad file
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0].name).toBe("bad.json");
    expect(result.errors[0].detail).toMatch(/Invalid JSON/i);

    // importSessionJson called exactly once (for the valid file only)
    expect(mockImportSessionJson).toHaveBeenCalledTimes(1);
  });

  it("surfaces a 409-style ApiError inline without aborting remaining imports", async () => {
    mockImportSessionJson
      .mockRejectedValueOnce(
        new ApiError(409, { detail: "session 'ses_drag_a' already exists" }, "POST /api/sessions/import → 409"),
      )
      .mockResolvedValueOnce(MOCK_SESSION_B);

    const result = await importFromFiles(
      [makeJsonFile("a.json", VALID_EXPORT_A), makeJsonFile("b.json", VALID_EXPORT_B)],
      () => {
        /* progress ignored */
      },
    );

    // Second file still imports after the first 409
    expect(result.imported).toHaveLength(1);
    expect(result.imported[0].id).toBe("ses_drag_b");

    // Error recorded for the conflicting file
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0].name).toBe("a.json");
    expect(result.errors[0].detail).toContain("already exists");
  });

  it("returns empty imported/errors arrays when given an empty file list", async () => {
    const result = await importFromFiles([], () => {
      /* never called */
    });
    expect(result.imported).toHaveLength(0);
    expect(result.errors).toHaveLength(0);
    expect(mockImportSessionJson).not.toHaveBeenCalled();
  });
});
