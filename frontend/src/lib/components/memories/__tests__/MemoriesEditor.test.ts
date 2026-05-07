/**
 * Component tests for :class:`MemoriesEditor` (item 2.10).
 *
 * Done-when criteria covered:
 *
 * * Memories scoped per tag (selecting a tag refetches).
 * * CRUD: create, edit, delete, toggle enabled.
 * * Validation rejects empty title / empty body / over-cap inputs.
 * * Per-tag list ordering: rendered order matches the API response
 *   order (the backend's :func:`memories_db.list_for_tag` is the
 *   ordering source of truth).
 *
 * The store is stubbed at the prop seam to keep the surface
 * deterministic. Validation helpers are exercised directly.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MemoriesEditor from "../MemoriesEditor.svelte";
import {
  isFormValid,
  validateMemoryForm,
  type MemoryFormErrors,
  type MemoryFormValues,
} from "../validation";
import type { TagMemoryOut } from "../../../api/memories";
import type { TagOut } from "../../../api/tags";
import { TAG_MEMORY_BODY_MAX_LENGTH, TAG_MEMORY_TITLE_MAX_LENGTH } from "../../../config";

function fakeMemory(overrides: Partial<TagMemoryOut> = {}): TagMemoryOut {
  return {
    id: 1,
    tag_id: 7,
    title: "Memory A",
    body: "Body A",
    enabled: true,
    created_at: "2026-04-29T00:00:00Z",
    updated_at: "2026-04-29T00:00:00Z",
    ...overrides,
  };
}

function fakeTag(overrides: Partial<TagOut> = {}): TagOut {
  return {
    id: 7,
    name: "bearings/architect",
    color: null,
    default_model: null,
    working_dir: null,
    pinned: false,
    class_: "general" as const,
    sort_order: 0,
    group: "bearings",
    created_at: "2026-04-29T00:00:00Z",
    updated_at: "2026-04-29T00:00:00Z",
    open_session_count: 0,
    session_count: 0,
    ...overrides,
  };
}

interface StubMemoriesStore {
  tagId: number | null;
  memories: TagMemoryOut[];
  loading: boolean;
  error: Error | null;
}

interface StubTagsStore {
  all: TagOut[];
  selectedProjectIds: ReadonlySet<number>;
  selectedSeverityIds: ReadonlySet<number>;
  selectedOtherIds: ReadonlySet<number>;
  loading: boolean;
  error: Error | null;
}

function makeStubStores(
  memories: TagMemoryOut[] = [],
  tagId: number | null = 7,
  tags: TagOut[] = [fakeTag()],
): { memoriesStore: StubMemoriesStore; tagsStore: StubTagsStore } {
  return {
    memoriesStore: {
      tagId,
      memories,
      loading: false,
      error: null,
    },
    tagsStore: {
      all: tags,
      selectedProjectIds: new Set<number>(),
      selectedSeverityIds: new Set<number>(),
      selectedOtherIds: new Set<number>(),
      loading: false,
      error: null,
    },
  };
}

beforeEach(() => {
  // Memories editor uses window.confirm for delete; default to "yes".
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("validateMemoryForm (helper)", () => {
  it("rejects an empty title", () => {
    const values: MemoryFormValues = { title: "", body: "ok" };
    const errors: MemoryFormErrors = validateMemoryForm(values);
    expect(errors.title).not.toBeNull();
    expect(errors.body).toBeNull();
  });

  it("rejects an empty body", () => {
    const errors = validateMemoryForm({ title: "ok", body: "  " });
    expect(errors.body).not.toBeNull();
  });

  it("rejects a too-long title", () => {
    const errors = validateMemoryForm({
      title: "x".repeat(TAG_MEMORY_TITLE_MAX_LENGTH + 1),
      body: "ok",
    });
    expect(errors.title).not.toBeNull();
  });

  it("rejects a too-long body", () => {
    const errors = validateMemoryForm({
      title: "ok",
      body: "y".repeat(TAG_MEMORY_BODY_MAX_LENGTH + 1),
    });
    expect(errors.body).not.toBeNull();
  });

  it("accepts trimmed title + body within bounds", () => {
    const errors = validateMemoryForm({ title: "  T  ", body: "  body  " });
    expect(errors.title).toBeNull();
    expect(errors.body).toBeNull();
    expect(isFormValid(errors)).toBe(true);
  });
});

describe("MemoriesEditor — render branches", () => {
  it("renders the empty-for-tag copy when the tag has no memories", () => {
    const { memoriesStore, tagsStore } = makeStubStores([], 7);
    const { getByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
        createMemoryFor: vi.fn(),
        updateMemoryFor: vi.fn(),
        deleteMemoryFor: vi.fn(),
      },
    });
    expect(getByTestId("memories-editor-empty")).toBeInTheDocument();
  });

  it("renders the pick-tag prompt when no tag is active", () => {
    const { memoriesStore, tagsStore } = makeStubStores([], null);
    const { getByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
      },
    });
    expect(getByTestId("memories-editor-pick-tag")).toBeInTheDocument();
  });

  it("renders one row per memory in the API order", () => {
    const memories = [
      fakeMemory({ id: 1, title: "First" }),
      fakeMemory({ id: 2, title: "Second" }),
    ];
    const { memoriesStore, tagsStore } = makeStubStores(memories);
    const { getAllByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
      },
    });
    const rows = getAllByTestId("memories-editor-row");
    expect(rows.map((r) => r.dataset.memoryId)).toEqual(["1", "2"]);
  });
});

describe("MemoriesEditor — tag selector", () => {
  it("calls setActiveTag when the user picks a different tag", async () => {
    const setActiveTag = vi.fn();
    const tags = [fakeTag({ id: 7 }), fakeTag({ id: 9, name: "bearings/exec" })];
    const { memoriesStore, tagsStore } = makeStubStores([], 7, tags);
    const { getByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag,
      },
    });
    const select = getByTestId("memories-editor-tag-select") as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "9" } });
    expect(setActiveTag).toHaveBeenCalledWith(9);
  });

  it("clears the active tag when the user picks the placeholder", async () => {
    const setActiveTag = vi.fn();
    const { memoriesStore, tagsStore } = makeStubStores([], 7);
    const { getByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag,
      },
    });
    const select = getByTestId("memories-editor-tag-select") as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "" } });
    expect(setActiveTag).toHaveBeenCalledWith(null);
  });
});

describe("MemoriesEditor — CRUD wiring", () => {
  it("create: clicking +New, filling the form, and Save calls createMemoryFor", async () => {
    const createMemoryFor = vi.fn().mockResolvedValue(fakeMemory());
    const { memoriesStore, tagsStore } = makeStubStores([], 7);
    const { getByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
        createMemoryFor,
        updateMemoryFor: vi.fn(),
        deleteMemoryFor: vi.fn(),
      },
    });
    await fireEvent.click(getByTestId("memories-editor-new"));
    const titleInput = getByTestId("memories-editor-title-input") as HTMLInputElement;
    const bodyInput = getByTestId("memories-editor-body-input") as HTMLTextAreaElement;
    await fireEvent.input(titleInput, { target: { value: "T" } });
    await fireEvent.input(bodyInput, { target: { value: "B" } });
    await fireEvent.click(getByTestId("memories-editor-save"));
    await waitFor(() =>
      expect(createMemoryFor).toHaveBeenCalledWith(7, {
        title: "T",
        body: "B",
        enabled: true,
      }),
    );
  });

  it("edit: clicking Edit pre-fills the form and Save calls updateMemoryFor", async () => {
    const updateMemoryFor = vi.fn().mockResolvedValue(fakeMemory());
    const memory = fakeMemory({ id: 42, title: "Old", body: "Old body" });
    const { memoriesStore, tagsStore } = makeStubStores([memory]);
    const { getByTestId, getAllByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
        createMemoryFor: vi.fn(),
        updateMemoryFor,
        deleteMemoryFor: vi.fn(),
      },
    });
    const editButtons = getAllByTestId("memories-editor-edit");
    await fireEvent.click(editButtons[0]);
    const titleInput = getByTestId("memories-editor-title-input") as HTMLInputElement;
    expect(titleInput.value).toBe("Old");
    await fireEvent.input(titleInput, { target: { value: "New" } });
    await fireEvent.click(getByTestId("memories-editor-save"));
    await waitFor(() =>
      expect(updateMemoryFor).toHaveBeenCalledWith(42, {
        title: "New",
        body: "Old body",
        enabled: true,
      }),
    );
  });

  it("delete: confirms via window.confirm then calls deleteMemoryFor", async () => {
    const deleteMemoryFor = vi.fn().mockResolvedValue(undefined);
    const memory = fakeMemory({ id: 99 });
    const { memoriesStore, tagsStore } = makeStubStores([memory]);
    const { getAllByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
        createMemoryFor: vi.fn(),
        updateMemoryFor: vi.fn(),
        deleteMemoryFor,
      },
    });
    const deleteButtons = getAllByTestId("memories-editor-delete");
    await fireEvent.click(deleteButtons[0]);
    await waitFor(() => expect(deleteMemoryFor).toHaveBeenCalledWith(99));
  });

  it("delete: bails out when the user dismisses the confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const deleteMemoryFor = vi.fn().mockResolvedValue(undefined);
    const memory = fakeMemory({ id: 99 });
    const { memoriesStore, tagsStore } = makeStubStores([memory]);
    const { getAllByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
        createMemoryFor: vi.fn(),
        updateMemoryFor: vi.fn(),
        deleteMemoryFor,
      },
    });
    await fireEvent.click(getAllByTestId("memories-editor-delete")[0]);
    expect(deleteMemoryFor).not.toHaveBeenCalled();
  });

  it("enabled toggle: flipping calls updateMemoryFor with !enabled", async () => {
    const updateMemoryFor = vi.fn().mockResolvedValue(fakeMemory());
    const memory = fakeMemory({ id: 5, enabled: true, title: "T", body: "B" });
    const { memoriesStore, tagsStore } = makeStubStores([memory]);
    const { getAllByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
        createMemoryFor: vi.fn(),
        updateMemoryFor,
        deleteMemoryFor: vi.fn(),
      },
    });
    const toggle = getAllByTestId("memories-editor-enabled-toggle")[0] as HTMLInputElement;
    await fireEvent.click(toggle);
    await waitFor(() =>
      expect(updateMemoryFor).toHaveBeenCalledWith(5, {
        title: "T",
        body: "B",
        enabled: false,
      }),
    );
  });
});

describe("MemoriesEditor — validation gates", () => {
  it("disables Save while the form has an error", async () => {
    const { memoriesStore, tagsStore } = makeStubStores([], 7);
    const { getByTestId } = render(MemoriesEditor, {
      props: {
        memoriesStore,
        tagsStore,
        refreshTags: vi.fn().mockResolvedValue(undefined),
        setActiveTag: vi.fn(),
      },
    });
    await fireEvent.click(getByTestId("memories-editor-new"));
    const save = getByTestId("memories-editor-save") as HTMLButtonElement;
    // Empty title + empty body — Save must be disabled.
    expect(save.disabled).toBe(true);
    // Surface the error messages for the two empty fields.
    expect(getByTestId("memories-editor-title-error")).toBeInTheDocument();
    expect(getByTestId("memories-editor-body-error")).toBeInTheDocument();
  });
});
