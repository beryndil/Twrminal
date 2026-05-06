/**
 * Component tests for TemplatePicker — covers open-on-t (via prop),
 * list ordering (newest-first), delete row flow, instantiate happy
 * path, and instantiate-without-working_dir 422 error surfaces inline.
 *
 * ``$app/navigation`` is mocked so ``goto`` doesn't require a
 * SvelteKit harness. The templates store is exercised through the real
 * store with fetch intercepted via ``vi.spyOn``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$app/navigation", () => ({
  goto: vi.fn().mockResolvedValue(undefined),
}));

// Import after mock so the component picks up the stub.
import { goto } from "$app/navigation";
import TemplatePicker from "../TemplatePicker.svelte";
import { _resetForTests } from "../../../stores/templates.svelte";
import type { TemplateOut } from "../../../api/templates";
import type { SessionOut } from "../../../api/sessions";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const makeTemplate = (overrides: Partial<TemplateOut> = {}): TemplateOut => ({
  id: 1,
  name: "Alpha",
  description: null,
  model: "sonnet",
  advisor_model: null,
  advisor_max_uses: 0,
  effort_level: "normal",
  permission_profile: "default",
  system_prompt_baseline: null,
  working_dir_default: "/wd",
  tag_names: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

const makeSession = (overrides: Partial<SessionOut> = {}): SessionOut => ({
  id: "ses_xyz",
  kind: "chat",
  title: "Alpha",
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
  ...overrides,
});

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function noContentResp(): Response {
  return new Response(null, { status: 204 });
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  _resetForTests();
  vi.mocked(goto).mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TemplatePicker — closed state", () => {
  it("renders nothing when open=false", () => {
    const { queryByTestId } = render(TemplatePicker, {
      props: { open: false, onClose: vi.fn() },
    });
    expect(queryByTestId("template-picker")).toBeNull();
  });
});

describe("TemplatePicker — open state", () => {
  it("renders the panel when open=true (even before fetch resolves)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([]));
    const { getByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });
    expect(getByTestId("template-picker")).toBeInTheDocument();
  });

  it("shows loading state initially then empty message when no templates", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([]));
    const { queryByTestId, findByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });
    // Eventually the empty state appears.
    const empty = await findByTestId("template-picker-empty");
    expect(empty).toBeInTheDocument();
    expect(queryByTestId("template-picker-list")).toBeNull();
  });

  it("lists templates with each row's name visible", async () => {
    const t = makeTemplate({ id: 1, name: "My Template" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([t]));
    const { findAllByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });
    const rows = await findAllByTestId("template-picker-row-name");
    expect(rows).toHaveLength(1);
    expect(rows[0]?.textContent?.trim()).toBe("My Template");
  });

  it("orders rows newest-first", async () => {
    const old = makeTemplate({ id: 1, name: "Old", created_at: "2026-01-01T00:00:00Z" });
    const newer = makeTemplate({ id: 2, name: "Newer", created_at: "2026-06-01T00:00:00Z" });
    // API returns old first (alphabetical); store sorts newest-first.
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([old, newer]));
    const { findAllByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });
    const rows = await findAllByTestId("template-picker-row-name");
    expect(rows[0]?.textContent?.trim()).toBe("Newer");
    expect(rows[1]?.textContent?.trim()).toBe("Old");
  });

  it("calls onClose and goto when clicking a row (instantiate happy path)", async () => {
    const t = makeTemplate({ id: 3, name: "Alpha" });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResp([t])) // list
      .mockResolvedValueOnce(jsonResp(makeSession({ id: "ses_new" }), 201)); // create session

    const onClose = vi.fn();
    const { findByTestId } = render(TemplatePicker, {
      props: { open: true, onClose },
    });

    const nameBtn = await findByTestId("template-picker-row-name");
    await fireEvent.click(nameBtn);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
      expect(goto).toHaveBeenCalledWith("/sessions/ses_new");
    });
  });

  it("surfaces an inline error when instantiate fails (422)", async () => {
    const t = makeTemplate({ id: 4, working_dir_default: null });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResp([t])) // list
      .mockResolvedValueOnce(jsonResp({ detail: "no working_dir" }, 422)); // create fail

    const onClose = vi.fn();
    const { findByTestId } = render(TemplatePicker, {
      props: { open: true, onClose },
    });

    const nameBtn = await findByTestId("template-picker-row-name");
    await fireEvent.click(nameBtn);

    const errEl = await findByTestId("template-picker-instantiate-error");
    expect(errEl.textContent).toContain("Couldn't create session");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("shows per-row confirm UI when × delete is clicked", async () => {
    const t = makeTemplate({ id: 5, name: "ToDelete" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([t]));

    const { findByTestId, queryByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });

    const deleteBtn = await findByTestId("template-picker-row-delete");
    await fireEvent.click(deleteBtn);

    // Confirm + cancel buttons appear; row name button is gone.
    expect(queryByTestId("template-picker-delete-confirm")).toBeInTheDocument();
    expect(queryByTestId("template-picker-delete-cancel")).toBeInTheDocument();
    expect(queryByTestId("template-picker-confirm-msg")).toBeInTheDocument();
  });

  it("cancelling delete confirm restores the normal row", async () => {
    const t = makeTemplate({ id: 6 });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([t]));

    const { findByTestId, queryByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });

    await fireEvent.click(await findByTestId("template-picker-row-delete"));
    await fireEvent.click(await findByTestId("template-picker-delete-cancel"));

    expect(queryByTestId("template-picker-row-name")).toBeInTheDocument();
    expect(queryByTestId("template-picker-delete-confirm")).toBeNull();
  });

  it("confirming delete removes the row from the list", async () => {
    const t = makeTemplate({ id: 7 });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResp([t])) // list
      .mockResolvedValueOnce(noContentResp()) // DELETE
      .mockResolvedValueOnce(jsonResp([])); // refresh after delete

    const { findByTestId, queryByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });

    await fireEvent.click(await findByTestId("template-picker-row-delete"));
    await fireEvent.click(await findByTestId("template-picker-delete-confirm"));

    await waitFor(() => {
      expect(queryByTestId("template-picker-row-name")).toBeNull();
      expect(queryByTestId("template-picker-empty")).toBeInTheDocument();
    });
  });

  it("close button fires onClose", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResp([]));
    const onClose = vi.fn();
    const { findByTestId } = render(TemplatePicker, {
      props: { open: true, onClose },
    });
    await fireEvent.click(await findByTestId("template-picker-close"));
    expect(onClose).toHaveBeenCalled();
  });

  it("shows load-error message when the fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("net fail"));
    const { findByTestId } = render(TemplatePicker, {
      props: { open: true, onClose: vi.fn() },
    });
    const errEl = await findByTestId("template-picker-load-error");
    expect(errEl).toBeInTheDocument();
  });
});
