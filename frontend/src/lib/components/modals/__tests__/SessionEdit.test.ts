/**
 * SessionEdit modal tests — gap-cycle-10-001.
 *
 * Covers the eight acceptance criteria:
 *  1. Modal opens seeded with the session's current field values.
 *  2. Editing fields and saving fires patchSession with the new values.
 *  3. Cancel closes without firing patchSession.
 *  4. Esc closes without firing patchSession.
 *  5. Backdrop click closes without firing patchSession.
 *  6. Inline tag creation — Enter on a non-existent name calls createTag.
 *  7. 422 / network error surfaces inline error message.
 *  8. Empty title is rejected client-side without a network call.
 *
 * AI-title-suggestion (✨) is intentionally out of scope per gap entry.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { flushSync } from "svelte";
import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";

import SessionEdit from "../SessionEdit.svelte";
import type { SessionOut } from "../../../api/sessions";
import type { TagOut } from "../../../api/tags";
import { _resetForTests, contextMenuStore } from "../../../context-menu/store.svelte";
import {
  MENU_ACTION_TAG_CHIP_COPY_NAME,
  MENU_ACTION_TAG_CHIP_DETACH,
  MENU_TARGET_TAG_CHIP,
} from "../../../config";

// ---- mock API surface ------------------------------------------------------

vi.mock("../../../api/sessions", () => ({
  patchSession: vi.fn(),
}));

vi.mock("../../../api/tags", () => ({
  listTags: vi.fn().mockResolvedValue([]),
  createTag: vi.fn(),
  attachTagToSession: vi.fn(),
}));

vi.mock("../../../stores/undo.svelte", () => ({
  undoStore: { push: vi.fn() },
}));

import { patchSession } from "../../../api/sessions";
import { createTag } from "../../../api/tags";

beforeEach(() => {
  _resetForTests();
});

afterEach(() => {
  _resetForTests();
  vi.clearAllMocks();
});

// ---- fixtures --------------------------------------------------------------

function fakeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "Test session",
    description: "A description",
    session_instructions: "Do things carefully.",
    working_dir: "/wd",
    model: "sonnet",
    permission_mode: null,
    max_budget_usd: 5.0,
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
  };
}

function fakeTag(id: number, name: string): TagOut {
  return {
    id,
    name,
    color: null,
    default_model: null,
    working_dir: null,
    pinned: false,
    class_: "general",
    sort_order: 0,
    group: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    open_session_count: 0,
    session_count: 0,
  };
}

const noop = (): void => {};

// ---- tests -----------------------------------------------------------------

describe("SessionEdit", () => {
  it("renders with fields seeded from the session", () => {
    const session = fakeSession();
    const { getByTestId } = render(SessionEdit, {
      props: {
        session,
        currentTags: [],
        allTags: [],
        onSave: noop,
        onCancel: noop,
      },
    });

    expect((getByTestId("session-edit-title-input") as HTMLInputElement).value).toBe(
      session.title,
    );
    expect((getByTestId("session-edit-description-input") as HTMLTextAreaElement).value).toBe(
      session.description,
    );
    expect((getByTestId("session-edit-budget-input") as HTMLInputElement).value).toBe("5");
    expect((getByTestId("session-edit-instructions-input") as HTMLTextAreaElement).value).toBe(
      session.session_instructions,
    );
  });

  it("calls patchSession and onSave when Save is clicked", async () => {
    const session = fakeSession();
    const updatedSession = fakeSession({ title: "Updated" });
    vi.mocked(patchSession).mockResolvedValueOnce(updatedSession);

    const onSave = vi.fn();
    const { getByTestId } = render(SessionEdit, {
      props: {
        session,
        currentTags: [],
        allTags: [],
        onSave,
        onCancel: noop,
      },
    });

    // Change the title — set DOM value then dispatch input + flushSync so
    // Svelte's bind:value state update is flushed before the save click.
    const titleInput = getByTestId("session-edit-title-input") as HTMLInputElement;
    titleInput.value = "Updated";
    await fireEvent.input(titleInput);
    flushSync();

    fireEvent.click(getByTestId("session-edit-save"));

    await waitFor(() => {
      expect(patchSession).toHaveBeenCalledWith(
        session.id,
        expect.objectContaining({ title: "Updated" }),
      );
      expect(onSave).toHaveBeenCalledWith(updatedSession);
    });
  });

  it("calls onCancel when Cancel is clicked without calling patchSession", () => {
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [],
        allTags: [],
        onSave: noop,
        onCancel,
      },
    });

    fireEvent.click(getByTestId("session-edit-cancel"));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(patchSession).not.toHaveBeenCalled();
  });

  it("calls onCancel on Esc keydown without calling patchSession", () => {
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [],
        allTags: [],
        onSave: noop,
        onCancel,
      },
    });

    // Esc on the backdrop triggers onCancel.
    fireEvent.keyDown(getByTestId("session-edit-backdrop"), { key: "Escape" });

    expect(onCancel).toHaveBeenCalledOnce();
    expect(patchSession).not.toHaveBeenCalled();
  });

  it("calls onCancel on backdrop click without calling patchSession", () => {
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [],
        allTags: [],
        onSave: noop,
        onCancel,
      },
    });

    fireEvent.click(getByTestId("session-edit-backdrop"));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(patchSession).not.toHaveBeenCalled();
  });

  it("rejects an empty title client-side and does not call patchSession", async () => {
    const { getByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [],
        allTags: [],
        onSave: noop,
        onCancel: noop,
      },
    });

    // Clear the title.
    const titleInput = getByTestId("session-edit-title-input") as HTMLInputElement;
    titleInput.value = "   ";
    await fireEvent.input(titleInput);

    fireEvent.click(getByTestId("session-edit-save"));

    await waitFor(() => {
      expect(getByTestId("session-edit-error")).toBeInTheDocument();
    });
    expect(patchSession).not.toHaveBeenCalled();
  });

  it("calls createTag on Enter with a non-existent tag name", async () => {
    const newTag = fakeTag(42, "new-tag");
    vi.mocked(createTag).mockResolvedValueOnce(newTag);

    const { getByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [],
        allTags: [],
        onSave: noop,
        onCancel: noop,
      },
    });

    const tagInput = getByTestId("session-edit-tag-input") as HTMLInputElement;
    tagInput.value = "new-tag";
    await fireEvent.input(tagInput);
    await fireEvent.keyDown(tagInput, { key: "Enter" });

    await waitFor(() => {
      expect(createTag).toHaveBeenCalledWith({ name: "new-tag" });
    });

    // Chip should appear after creation.
    await waitFor(() => {
      expect(getByTestId("session-edit-tags").textContent).toContain("new-tag");
    });
  });

  it("surfaces an inline error on patchSession 422", async () => {
    vi.mocked(patchSession).mockRejectedValueOnce(new Error("422: unknown tag_ids: [999]"));

    const { getByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [],
        allTags: [],
        onSave: noop,
        onCancel: noop,
      },
    });

    fireEvent.click(getByTestId("session-edit-save"));

    await waitFor(() => {
      const errorEl = getByTestId("session-edit-error");
      expect(errorEl).toBeInTheDocument();
      expect(errorEl.textContent).toContain("422");
    });
  });

  it("renders existing tag chips from currentTags with remove buttons", () => {
    const tag = fakeTag(1, "bearings");
    const { getAllByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [tag],
        allTags: [tag],
        onSave: noop,
        onCancel: noop,
      },
    });

    const chips = getAllByTestId("session-edit-tag-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0].textContent).toContain("bearings");

    // Remove button should be present.
    const removeBtn = getAllByTestId("session-edit-tag-remove");
    expect(removeBtn).toHaveLength(1);
  });
});

// ---- tag chip context menu (gap-cycle-20-001) --------------------------------

describe("SessionEdit tag chip context menu", () => {
  it("renders chip with data-tag-id bound to the tag id", () => {
    const tag = fakeTag(7, "alpha");
    const { getAllByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [tag],
        allTags: [tag],
        onSave: noop,
        onCancel: noop,
      },
    });

    const chips = getAllByTestId("session-edit-tag-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0].getAttribute("data-tag-id")).toBe("7");
  });

  it("right-click opens context menu with copy and detach entries", () => {
    const tag = fakeTag(3, "bearings");
    const { getAllByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [tag],
        allTags: [tag],
        onSave: noop,
        onCancel: noop,
      },
    });

    const chip = getAllByTestId("session-edit-tag-chip")[0];
    fireEvent(chip, new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

    const open = contextMenuStore.open;
    expect(open).not.toBeNull();
    expect(open?.target).toBe(MENU_TARGET_TAG_CHIP);
    expect(open?.handlers).toHaveProperty(MENU_ACTION_TAG_CHIP_COPY_NAME);
    expect(open?.handlers).toHaveProperty(MENU_ACTION_TAG_CHIP_DETACH);
    expect(open?.data).toMatchObject({ tagId: 3 });
  });

  it("detach entry carries confirmMessage for ConfirmDialog routing", () => {
    const tag = fakeTag(5, "my-tag");
    const { getAllByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [tag],
        allTags: [tag],
        onSave: noop,
        onCancel: noop,
      },
    });

    const chip = getAllByTestId("session-edit-tag-chip")[0];
    fireEvent(chip, new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

    const open = contextMenuStore.open;
    const detachEntry = open?.handlers[MENU_ACTION_TAG_CHIP_DETACH];
    expect(detachEntry).toBeDefined();
    expect(typeof detachEntry).toBe("object");
    // Must have confirmMessage (routes through central confirm bridge).
    expect((detachEntry as { confirmMessage: string }).confirmMessage).toContain("my-tag");
    // And a handler function.
    expect(typeof (detachEntry as { handler: unknown }).handler).toBe("function");
  });

  it("copy-name handler writes the tag name to clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    const tag = fakeTag(9, "clipboard-tag");
    const { getAllByTestId } = render(SessionEdit, {
      props: {
        session: fakeSession(),
        currentTags: [tag],
        allTags: [tag],
        onSave: noop,
        onCancel: noop,
      },
    });

    const chip = getAllByTestId("session-edit-tag-chip")[0];
    fireEvent(chip, new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));

    const open = contextMenuStore.open;
    const copyHandler = open?.handlers[MENU_ACTION_TAG_CHIP_COPY_NAME];
    expect(typeof copyHandler).toBe("function");
    (copyHandler as () => void)();

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("clipboard-tag");
    });
  });
});
