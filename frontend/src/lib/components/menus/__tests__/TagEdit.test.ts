/**
 * Unit tests for ``TagEdit.svelte`` — the tag-edit modal opened by
 * the ``tag.edit`` context-menu action (gap-cycle-01-016).
 *
 * Covers the three acceptance criteria that require vitest:
 *
 * 1. Switching to ``severity`` disables and clears the inheritance
 *    fields (``default_model`` / ``working_dir``).
 * 2. A backend 422 on the PATCH is surfaced inline (not swallowed).
 * 3. Submit happy path — calls ``updateTag`` and fires ``onSaved`` /
 *    ``onClose``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi, beforeEach } from "vitest";

import TagEdit from "../TagEdit.svelte";
import type { TagOut } from "../../../api/tags";
import { ApiError } from "../../../api/client";

// Mock the tags API module so tests don't make real HTTP calls.
vi.mock("../../../api/tags", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/tags")>();
  return {
    ...actual,
    updateTag: vi.fn(),
  };
});

import { updateTag } from "../../../api/tags";

const mockUpdateTag = updateTag as ReturnType<typeof vi.fn>;

/** Factory for a minimal TagOut fixture. */
function makeTag(overrides: Partial<TagOut> = {}): TagOut {
  return {
    id: 1,
    name: "bearings",
    color: null,
    default_model: "sonnet",
    working_dir: "/home/user/Projects",
    pinned: false,
    class_: "project",
    sort_order: 0,
    group: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    open_session_count: 0,
    session_count: 0,
    ...overrides,
  };
}

describe("TagEdit — class switch disables inheritance", () => {
  it("default_model and working_dir inputs are enabled for non-severity class", () => {
    const { getByTestId } = render(TagEdit, {
      props: {
        tag: makeTag({ class_: "project" }),
        onClose: vi.fn(),
        onSaved: vi.fn(),
      },
    });

    const modelInput = getByTestId("tag-edit-model") as HTMLInputElement;
    const wdInput = getByTestId("tag-edit-wd") as HTMLInputElement;

    expect(modelInput.disabled).toBe(false);
    expect(wdInput.disabled).toBe(false);
  });

  it("switching class to severity disables and clears default_model + working_dir", async () => {
    const { getByTestId, queryByTestId } = render(TagEdit, {
      props: {
        tag: makeTag({ class_: "project", default_model: "sonnet", working_dir: "/home/user" }),
        onClose: vi.fn(),
        onSaved: vi.fn(),
      },
    });

    const classSelect = getByTestId("tag-edit-class") as HTMLSelectElement;
    const modelInput = getByTestId("tag-edit-model") as HTMLInputElement;
    const wdInput = getByTestId("tag-edit-wd") as HTMLInputElement;

    // Fields start populated.
    expect(modelInput.value).toBe("sonnet");
    expect(wdInput.value).toBe("/home/user");

    // Switch to severity.
    await fireEvent.change(classSelect, { target: { value: "severity" } });

    await waitFor(() => {
      expect(modelInput.disabled).toBe(true);
      expect(wdInput.disabled).toBe(true);
      expect(modelInput.value).toBe("");
      expect(wdInput.value).toBe("");
    });

    // Hint text appears.
    expect(queryByTestId("tag-edit-severity-hint")).toBeInTheDocument();
  });

  it("switching back from severity to project re-enables the fields", async () => {
    const { getByTestId } = render(TagEdit, {
      props: {
        tag: makeTag({ class_: "severity", default_model: null, working_dir: null }),
        onClose: vi.fn(),
        onSaved: vi.fn(),
      },
    });

    const classSelect = getByTestId("tag-edit-class") as HTMLSelectElement;
    const modelInput = getByTestId("tag-edit-model") as HTMLInputElement;

    // Fields start disabled (severity).
    expect(modelInput.disabled).toBe(true);

    await fireEvent.change(classSelect, { target: { value: "project" } });

    await waitFor(() => {
      expect(modelInput.disabled).toBe(false);
    });
  });
});

describe("TagEdit — severity 422 surfaces inline", () => {
  beforeEach(() => {
    mockUpdateTag.mockReset();
  });

  it("surfaces a backend 422 detail message inline without closing", async () => {
    const apiErr = new ApiError(422, { detail: "severity tags cannot have inheritance fields" }, "PATCH /api/tags/1 → 422");
    mockUpdateTag.mockRejectedValueOnce(apiErr);

    const onClose = vi.fn();
    const onSaved = vi.fn();

    const { getByTestId } = render(TagEdit, {
      props: {
        tag: makeTag({ class_: "project" }),
        onClose,
        onSaved,
      },
    });

    await fireEvent.click(getByTestId("tag-edit-save"));

    await waitFor(() => {
      const err = getByTestId("tag-edit-error");
      expect(err).toBeInTheDocument();
      expect(err.textContent).toContain("severity tags cannot have inheritance fields");
    });

    // Modal stays open.
    expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("surfaces a generic Error message when ApiError body has no detail string", async () => {
    const apiErr = new ApiError(422, null, "PATCH /api/tags/1 → 422");
    mockUpdateTag.mockRejectedValueOnce(apiErr);

    const { getByTestId } = render(TagEdit, {
      props: {
        tag: makeTag(),
        onClose: vi.fn(),
        onSaved: vi.fn(),
      },
    });

    await fireEvent.click(getByTestId("tag-edit-save"));

    await waitFor(() => {
      expect(getByTestId("tag-edit-error")).toBeInTheDocument();
    });
  });
});

describe("TagEdit — submit happy path", () => {
  beforeEach(() => {
    mockUpdateTag.mockReset();
  });

  it("calls updateTag with patched values then fires onSaved and onClose", async () => {
    // Start with a tag that has no model/wd so no need to clear them — this
    // test focuses on the class switch and the PATCH + callback chain.
    const updated = makeTag({ class_: "general", default_model: null, working_dir: null });
    mockUpdateTag.mockResolvedValueOnce(updated);

    const onClose = vi.fn();
    const onSaved = vi.fn();

    const { getByTestId } = render(TagEdit, {
      props: {
        tag: makeTag({ class_: "project", default_model: null, working_dir: null }),
        onClose,
        onSaved,
      },
    });

    // Switch class to general.
    await fireEvent.change(getByTestId("tag-edit-class"), { target: { value: "general" } });

    await fireEvent.click(getByTestId("tag-edit-save"));

    await waitFor(() => {
      expect(mockUpdateTag).toHaveBeenCalledOnce();
      expect(mockUpdateTag).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ class_: "general", default_model: null }),
      );
      expect(onSaved).toHaveBeenCalledWith(updated);
      expect(onClose).toHaveBeenCalledOnce();
    });
  });

  it("does not show the error region on successful save", async () => {
    const updated = makeTag();
    mockUpdateTag.mockResolvedValueOnce(updated);

    const { queryByTestId } = render(TagEdit, {
      props: {
        tag: makeTag(),
        onClose: vi.fn(),
        onSaved: vi.fn(),
      },
    });

    await fireEvent.click(queryByTestId("tag-edit-save")!);

    await waitFor(() => {
      expect(queryByTestId("tag-edit-error")).not.toBeInTheDocument();
    });
  });
});
