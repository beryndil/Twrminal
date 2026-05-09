/**
 * Component tests for :class:`VaultPanel` (item 2.10).
 *
 * Done-when criteria covered:
 *
 * * Listing renders bucketed plans + todos.
 * * Search input runs the search after the debounce window.
 * * Paste-into-message integration writes to the composer bridge.
 * * NO write affordances render (vault is read-only per
 *   ``docs/behavior/vault.md`` §"CRUD flow").
 * * Redaction toggles flip the mask state per-range.
 * * Empty state names the configured plan_roots / todo_globs.
 * * F7-RT-00: row metadata — parent-dir + relative mtime rendered.
 * * F7-RT-02: "Open against this session" affordance present + functional.
 *
 * The store is stubbed at the prop seam to keep the surface
 * deterministic — the singleton store is exercised in
 * ``stores/__tests__/vault.test.svelte.ts``.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

import VaultPanel, {
  formatEmptyConfigCopy,
  formatRelativeTime,
  parentDirName,
  segmentBody,
} from "../VaultPanel.svelte";
import type { SearchResultOut, VaultDocOut, VaultEntryOut, VaultListOut } from "../../../api/vault";
import { VAULT_KIND_PLAN, VAULT_KIND_TODO, VAULT_SEARCH_DEBOUNCE_MS } from "../../../config";

function fakeEntry(overrides: Partial<VaultEntryOut> = {}): VaultEntryOut {
  return {
    id: 1,
    path: "/abs/x.md",
    slug: "x",
    title: "Title X",
    kind: VAULT_KIND_PLAN,
    mtime: 0,
    size: 12,
    last_indexed_at: 0,
    markdown_link: "[Title X](file:///abs/x.md)",
    ...overrides,
  };
}

function fakeList(): VaultListOut {
  return {
    plans: [fakeEntry({ id: 1, title: "Plan A" })],
    todos: [fakeEntry({ id: 2, title: "Todo Z", kind: VAULT_KIND_TODO })],
    plan_roots: ["/home/u/.claude/plans"],
    todo_globs: ["/home/u/Projects/**/TODO.md"],
  };
}

interface StubStore {
  list: VaultListOut | null;
  selected: VaultDocOut | null;
  searchQuery: string;
  searchResult: SearchResultOut | null;
  loading: boolean;
  selectedLoading: boolean;
  error: Error | null;
}

function makeStubStore(overrides: Partial<StubStore> = {}): StubStore {
  return {
    list: fakeList(),
    selected: null,
    searchQuery: "",
    searchResult: null,
    loading: false,
    selectedLoading: false,
    error: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

describe("segmentBody (helper)", () => {
  it("returns one text segment when no redactions", () => {
    expect(segmentBody("hello", [])).toEqual([
      { kind: "text", text: "hello", redactionIndex: null },
    ]);
  });

  it("interleaves text + redaction segments by offset order", () => {
    const segs = segmentBody("hello world", [{ offset: 6, length: 5, pattern: "key=value" }]);
    expect(segs).toEqual([
      { kind: "text", text: "hello ", redactionIndex: null },
      { kind: "redaction", text: "world", redactionIndex: 0 },
    ]);
  });

  it("handles a redaction at the start of the body", () => {
    const segs = segmentBody("secret end", [{ offset: 0, length: 6, pattern: "k" }]);
    expect(segs[0].kind).toBe("redaction");
    expect(segs[1]).toEqual({ kind: "text", text: " end", redactionIndex: null });
  });
});

describe("formatEmptyConfigCopy (helper)", () => {
  it("substitutes both placeholders", () => {
    const out = formatEmptyConfigCopy(
      "No plans found under {plan_roots}. No TODO.md files match {todo_globs}.",
      ["/a", "/b"],
      ["**/T.md"],
    );
    expect(out).toContain("/a, /b");
    expect(out).toContain("**/T.md");
  });

  it("replaces empty arrays with '(none)'", () => {
    const out = formatEmptyConfigCopy("{plan_roots} | {todo_globs}", [], []);
    expect(out).toBe("(none) | (none)");
  });
});

describe("VaultPanel — listing", () => {
  it("renders plans + todos buckets", () => {
    const stubStore = makeStubStore();
    const { getAllByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        selectVaultDoc: vi.fn(),
        clearVaultSelection: vi.fn(),
        setVaultSearchQuery: vi.fn().mockResolvedValue(undefined),
        pasteIntoComposer: vi.fn(),
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
        writeClipboard: vi.fn().mockResolvedValue(undefined),
      },
    });
    const rows = getAllByTestId("vault-panel-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].dataset.vaultKind).toBe(VAULT_KIND_PLAN);
    expect(rows[1].dataset.vaultKind).toBe(VAULT_KIND_TODO);
  });

  it("renders empty-state copy with configured roots when fully empty", () => {
    const stubStore = makeStubStore({
      list: {
        plans: [],
        todos: [],
        plan_roots: ["/configured/plans"],
        todo_globs: ["/configured/todos/**/T.md"],
      },
    });
    const { getByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
      },
    });
    const empty = getByTestId("vault-panel-empty");
    expect(empty.textContent).toContain("/configured/plans");
    expect(empty.textContent).toContain("/configured/todos/**/T.md");
  });
});

describe("VaultPanel — read-only semantic (vault.md §CRUD flow)", () => {
  it("renders NO Create / Update / Delete affordances on entries", () => {
    const stubStore = makeStubStore();
    const { container, queryByText } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
      },
    });
    // Defensive: scan the rendered DOM for any "delete", "edit",
    // "rename", or "new" affordance scoped to vault entries. The
    // test-id alphabet on the component exposes only read-shaped ids
    // (vault-panel-row, vault-panel-hit, vault-panel-paste-link,
    // vault-panel-copy-link, vault-panel-copy-body,
    // vault-panel-redaction-toggle).
    const writeIds = [
      "vault-panel-delete",
      "vault-panel-edit",
      "vault-panel-rename",
      "vault-panel-new",
    ];
    for (const id of writeIds) {
      expect(container.querySelector(`[data-testid="${id}"]`)).toBeNull();
    }
    // Visible-text screen for English mutation verbs scoped to
    // entries. We look only inside the index column so the
    // composer-paste affordances (which DO say "Paste") don't
    // accidentally match.
    const indexColumn = container.querySelector(".vault-panel__index");
    expect(indexColumn).not.toBeNull();
    expect(indexColumn?.textContent ?? "").not.toMatch(/\b(Delete|Rename|New plan|New todo)\b/);
    expect(queryByText(/^Edit doc$/)).toBeNull();
  });
});

describe("VaultPanel — search debounce", () => {
  it("calls setVaultSearchQuery after the debounce window", async () => {
    const setVaultSearchQuery = vi.fn().mockResolvedValue(undefined);
    const stubStore = makeStubStore();
    const { getByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        setVaultSearchQuery,
      },
    });
    const search = getByTestId("vault-panel-search") as HTMLInputElement;
    await fireEvent.input(search, { target: { value: "hello" } });
    expect(setVaultSearchQuery).not.toHaveBeenCalled();
    vi.advanceTimersByTime(VAULT_SEARCH_DEBOUNCE_MS + 5);
    await waitFor(() => expect(setVaultSearchQuery).toHaveBeenCalledWith("hello"));
  });

  it("renders capped indicator when the result is capped", () => {
    const stubStore = makeStubStore({
      searchResult: {
        hits: [
          {
            vault_id: 1,
            path: "/x.md",
            title: "X",
            kind: VAULT_KIND_PLAN,
            line_number: 3,
            snippet: "match",
          },
        ],
        capped: true,
      },
    });
    const { getByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
      },
    });
    expect(getByTestId("vault-panel-search-capped")).toBeInTheDocument();
  });
});

describe("VaultPanel — paste-into-message integration", () => {
  function makeSelectedDoc(): VaultDocOut {
    return {
      entry: fakeEntry({ id: 5 }),
      body: "doc body",
      redactions: [],
      truncated: false,
    };
  }

  it("paste-link calls composer bridge with the markdown_link + 'link' kind", async () => {
    const pasteIntoComposer = vi.fn();
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { getByTestId } = render(VaultPanel, {
      props: {
        activeSessionId: "sess_abc",
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        pasteIntoComposer,
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    await fireEvent.click(getByTestId("vault-panel-paste-link"));
    expect(pasteIntoComposer).toHaveBeenCalledWith({
      sessionId: "sess_abc",
      text: "[Title X](file:///abs/x.md)",
      kind: "link",
    });
  });

  it("paste-body calls composer bridge with the doc body + 'body' kind", async () => {
    const pasteIntoComposer = vi.fn();
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { getByTestId } = render(VaultPanel, {
      props: {
        activeSessionId: "sess_abc",
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        pasteIntoComposer,
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    await fireEvent.click(getByTestId("vault-panel-paste-body"));
    expect(pasteIntoComposer).toHaveBeenCalledWith({
      sessionId: "sess_abc",
      text: "doc body",
      kind: "body",
    });
  });

  it("disables paste affordances + surfaces toast when no active session", async () => {
    const pasteIntoComposer = vi.fn();
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { getByTestId } = render(VaultPanel, {
      props: {
        activeSessionId: null,
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        pasteIntoComposer,
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    const btn = getByTestId("vault-panel-paste-link") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("copy-as-markdown-link writes to the clipboard", async () => {
    const writeClipboard = vi.fn().mockResolvedValue(undefined);
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { getByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
        writeClipboard,
      },
    });
    await fireEvent.click(getByTestId("vault-panel-copy-link"));
    expect(writeClipboard).toHaveBeenCalledWith("[Title X](file:///abs/x.md)");
  });
});

describe("VaultPanel — redaction toggles", () => {
  it("renders one toggle per redaction range", () => {
    const stubStore = makeStubStore({
      selected: {
        entry: fakeEntry(),
        body: "key=secret-very-long",
        redactions: [
          { offset: 4, length: 16, pattern: "key" },
          { offset: 0, length: 3, pattern: "preamble" },
        ],
        truncated: false,
      },
    });
    const { getAllByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    const toggles = getAllByTestId("vault-panel-redaction-toggle");
    expect(toggles).toHaveLength(2);
  });
});

describe("VaultPanel — drag-paste-into-composer", () => {
  it("dragstart on a vault row calls dataTransfer.setData with the entry markdown_link", async () => {
    /**
     * Guards ``handleDragStartVaultRow`` per vault.md §"Paste-into-message
     * behavior": dragging a vault row sets ``text/plain`` on the
     * DataTransfer to the entry's ``markdown_link`` string so that dropping
     * into the composer inserts the markdown reference.
     *
     * Regression guard for finding feature-7-004 (remaining drag-paste gap).
     */
    const stubStore = makeStubStore();
    const { getAllByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
      },
    });
    const rows = getAllByTestId("vault-panel-row");
    // rows[0] is the plan entry from fakeList() — markdown_link comes from
    // fakeEntry's base value (title override does not change the link).
    const expectedLink = fakeEntry({ id: 1, title: "Plan A" }).markdown_link;

    const setData = vi.fn();
    const mockDataTransfer = { setData, effectAllowed: "" } as unknown as DataTransfer;
    // jsdom does not implement DragEvent; use a plain bubbling Event with
    // dataTransfer injected via Object.defineProperty.  Svelte's ondragstart
    // attribute listens for the "dragstart" event name regardless of the
    // event's constructor, so the handler receives the patched event object.
    const dragEvent = new Event("dragstart", { bubbles: true, cancelable: true });
    Object.defineProperty(dragEvent, "dataTransfer", { value: mockDataTransfer });

    await fireEvent(rows[0], dragEvent);

    expect(setData).toHaveBeenCalledWith("text/plain", expectedLink);
  });
});

describe("VaultPanel — selection", () => {
  it("clicking a row calls selectVaultDoc with the entry id", async () => {
    const selectVaultDoc = vi.fn().mockResolvedValue(undefined);
    const stubStore = makeStubStore();
    const { getAllByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        selectVaultDoc,
      },
    });
    const rows = getAllByTestId("vault-panel-row");
    await fireEvent.click(rows[1]);
    expect(selectVaultDoc).toHaveBeenCalledWith(2);
  });
});

// ---------------------------------------------------------------------------
// F7-RT-00 — Row metadata: parent-dir + relative mtime
// ---------------------------------------------------------------------------

describe("parentDirName (helper)", () => {
  it("returns the directory segment one level above the filename", () => {
    expect(parentDirName("/home/u/.claude/plans/foo.md")).toBe("plans");
    expect(parentDirName("/home/u/Projects/my-project/TODO.md")).toBe("my-project");
  });

  it("returns empty string for a path with no parent", () => {
    expect(parentDirName("/file.md")).toBe("");
    expect(parentDirName("")).toBe("");
  });

  it("handles paths with a leading slash and no segments", () => {
    expect(parentDirName("/")).toBe("");
  });
});

describe("formatRelativeTime (helper)", () => {
  const NOW = 1_700_000_000_000; // fixed ms epoch

  it("formats sub-60s difference as 'Xs ago'", () => {
    const mtime = (NOW - 45_000) / 1000; // 45 s ago
    expect(formatRelativeTime(mtime, NOW)).toBe("45s ago");
  });

  it("formats 0s difference as '0s ago'", () => {
    const mtime = NOW / 1000;
    expect(formatRelativeTime(mtime, NOW)).toBe("0s ago");
  });

  it("formats minutes-range as 'Xm ago'", () => {
    const mtime = (NOW - 5 * 60 * 1000) / 1000; // 5 min ago
    expect(formatRelativeTime(mtime, NOW)).toBe("5m ago");
  });

  it("formats hours-range as 'Xh ago'", () => {
    const mtime = (NOW - 3 * 3600 * 1000) / 1000; // 3 h ago
    expect(formatRelativeTime(mtime, NOW)).toBe("3h ago");
  });

  it("formats days-range as 'Xd ago'", () => {
    const mtime = (NOW - 2 * 86_400 * 1000) / 1000; // 2 d ago
    expect(formatRelativeTime(mtime, NOW)).toBe("2d ago");
  });

  it("clamps negative diff to 0s ago (future mtime)", () => {
    const mtime = (NOW + 10_000) / 1000; // 10 s in the future
    expect(formatRelativeTime(mtime, NOW)).toBe("0s ago");
  });
});

describe("VaultPanel — row metadata (F7-RT-00)", () => {
  it("renders parent-dir and relative-mtime in each row (plan + todo)", () => {
    // Use real Date.now() so formatRelativeTime() inside the component
    // (which calls Date.now() internally) sees the same clock as the test.
    const NOW_MS = Date.now();
    const mtimeSec = (NOW_MS - 5 * 60 * 1000) / 1000; // 5 min ago
    const stubStore = makeStubStore({
      list: {
        plans: [
          fakeEntry({
            id: 1,
            title: "Plan A",
            path: "/home/u/.claude/plans/plan-a.md",
            mtime: mtimeSec,
          }),
        ],
        todos: [
          fakeEntry({
            id: 2,
            title: null,
            kind: VAULT_KIND_TODO,
            path: "/home/u/Projects/my-project/TODO.md",
            mtime: mtimeSec,
          }),
        ],
        plan_roots: ["/home/u/.claude/plans"],
        todo_globs: ["**/TODO.md"],
      },
    });
    const { getAllByTestId } = render(VaultPanel, {
      props: {
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
      },
    });
    const metas = getAllByTestId("vault-panel-row-meta");
    // Two rows (plan + todo) each render a meta line
    expect(metas).toHaveLength(2);
    // Plan row: parent dir = "plans", mtime = "5m ago"
    expect(metas[0]?.textContent).toContain("plans");
    expect(metas[0]?.textContent).toContain("5m ago");
    // Todo row: parent dir = "my-project"
    expect(metas[1]?.textContent).toContain("my-project");
  });
});

// ---------------------------------------------------------------------------
// F7-RT-02 — "Open against this session" affordance
// ---------------------------------------------------------------------------

describe("VaultPanel — open-against-session affordance (F7-RT-02)", () => {
  function makeSelectedDoc(): VaultDocOut {
    return {
      entry: fakeEntry({ id: 5 }),
      body: "doc body",
      redactions: [],
      truncated: false,
    };
  }

  it("renders 'Open against this session' button when activeSessionId is set + doc selected", () => {
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { getByTestId } = render(VaultPanel, {
      props: {
        activeSessionId: "sess_abc",
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    expect(getByTestId("vault-panel-open-against-session")).toBeInTheDocument();
  });

  it("does NOT render 'Open against this session' button when activeSessionId is null", () => {
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { queryByTestId } = render(VaultPanel, {
      props: {
        activeSessionId: null,
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    expect(queryByTestId("vault-panel-open-against-session")).toBeNull();
  });

  it("clicking the button shows the pinned-session indicator", async () => {
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { getByTestId, queryByTestId } = render(VaultPanel, {
      props: {
        activeSessionId: "sess_xyz",
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    // Indicator absent before pinning
    expect(queryByTestId("vault-panel-pinned-session")).toBeNull();
    await fireEvent.click(getByTestId("vault-panel-open-against-session"));
    // Indicator appears after pinning, showing the session id
    const indicator = getByTestId("vault-panel-pinned-session");
    expect(indicator).toBeInTheDocument();
    expect(indicator.textContent).toContain("sess_xyz");
  });

  it("paste-link uses the pinned session id after pinning", async () => {
    const pasteIntoComposer = vi.fn();
    const stubStore = makeStubStore({ selected: makeSelectedDoc() });
    const { getByTestId } = render(VaultPanel, {
      props: {
        activeSessionId: "sess_xyz",
        vaultStore: stubStore,
        refreshVault: vi.fn().mockResolvedValue(undefined),
        pasteIntoComposer,
        renderMarkdown: vi.fn().mockResolvedValue(""),
        sanitizeHtml: vi.fn().mockReturnValue(""),
      },
    });
    await fireEvent.click(getByTestId("vault-panel-open-against-session"));
    await fireEvent.click(getByTestId("vault-panel-paste-link"));
    expect(pasteIntoComposer).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: "sess_xyz" }),
    );
  });
});
