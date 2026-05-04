/**
 * Component tests for ``SessionRow`` — title, kind indicator, tag
 * chips, status indicators (pinned / closed / error), and the
 * finder-click behavior (clicking a tag chip on the row triggers the
 * onToggleTag callback with that tag's id).
 */
import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import SessionRow from "../SessionRow.svelte";
import type { SessionOut } from "../../../api/sessions";
import type { TagOut } from "../../../api/tags";

const baseSession: SessionOut = {
  id: "ses_a",
  kind: "chat",
  title: "Hello",
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
};

const tag = (id: number, name: string): TagOut => ({
  id,
  name,
  color: null,
  default_model: null,
  working_dir: null,
  pinned: false,
  group: name.includes("/") ? name.split("/")[0] : null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

describe("SessionRow", () => {
  it("renders the session title", () => {
    const { getByTestId } = render(SessionRow, {
      props: {
        session: baseSession,
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(getByTestId("session-title")).toHaveTextContent("Hello");
  });

  it("renders the kind indicator with the correct aria-label", () => {
    const { getByTestId } = render(SessionRow, {
      props: {
        session: baseSession,
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(getByTestId("session-kind-indicator")).toHaveAttribute("aria-label", "Chat session");
  });

  it("renders pinned + error indicators when the flags are set", () => {
    const { getByTestId } = render(SessionRow, {
      props: {
        session: { ...baseSession, pinned: true, error_pending: true },
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(getByTestId("session-pinned-indicator")).toBeInTheDocument();
    expect(getByTestId("session-error-indicator")).toBeInTheDocument();
  });

  it("renders the closed indicator when closed_at is set", () => {
    const { getByTestId } = render(SessionRow, {
      props: {
        session: { ...baseSession, closed_at: "2026-01-02T00:00:00Z" },
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(getByTestId("session-closed-indicator")).toBeInTheDocument();
  });

  it("renders one tag chip per attached tag", () => {
    const { getAllByTestId } = render(SessionRow, {
      props: {
        session: baseSession,
        tags: [tag(1, "bearings/architect"), tag(2, "bearings/exec")],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(getAllByTestId("session-tag-chip")).toHaveLength(2);
  });

  it("marks chips for selected tag ids with aria-pressed=true", () => {
    const { getAllByTestId } = render(SessionRow, {
      props: {
        session: baseSession,
        tags: [tag(1, "a"), tag(2, "b")],
        selectedTagIds: new Set([1]),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    const [first, second] = getAllByTestId("session-tag-chip");
    expect(first).toHaveAttribute("aria-pressed", "true");
    expect(second).toHaveAttribute("aria-pressed", "false");
  });

  it("clicking the row fires onSelect with the session id", async () => {
    const onSelect = vi.fn();
    const { getByTestId } = render(SessionRow, {
      props: {
        session: baseSession,
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect,
        onToggleTag: vi.fn(),
      },
    });
    await fireEvent.click(getByTestId("session-row"));
    expect(onSelect).toHaveBeenCalledWith("ses_a");
  });

  it("clicking a tag chip fires onToggleTag with the tag id (finder-click)", async () => {
    const onToggleTag = vi.fn();
    const onSelect = vi.fn();
    const { getAllByTestId } = render(SessionRow, {
      props: {
        session: baseSession,
        tags: [tag(7, "bearings/architect")],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect,
        onToggleTag,
      },
    });
    await fireEvent.click(getAllByTestId("session-tag-chip")[0]);
    expect(onToggleTag).toHaveBeenCalledWith(7);
  });

  it("renders the closing-summary tooltip on closed rows via the title attribute", () => {
    const { getByTestId } = render(SessionRow, {
      props: {
        session: {
          ...baseSession,
          closed_at: "2026-01-02T00:00:00Z",
          closing_summary: "Implemented X and verified the gate.",
        },
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(getByTestId("session-row")).toHaveAttribute(
      "title",
      "Implemented X and verified the gate.",
    );
  });

  it("omits the title attribute when closing_summary is null even on closed rows", () => {
    const { getByTestId } = render(SessionRow, {
      props: {
        session: { ...baseSession, closed_at: "2026-01-02T00:00:00Z", closing_summary: null },
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(getByTestId("session-row")).not.toHaveAttribute("title");
  });

  it("renders the Reopen button on closed rows when onReopen is provided", () => {
    const onReopen = vi.fn();
    const { getByTestId } = render(SessionRow, {
      props: {
        session: { ...baseSession, closed_at: "2026-01-02T00:00:00Z" },
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
        onReopen,
      },
    });
    expect(getByTestId("session-reopen-button")).toBeInTheDocument();
  });

  it("hides the Reopen button when onReopen is omitted", () => {
    const { queryByTestId } = render(SessionRow, {
      props: {
        session: { ...baseSession, closed_at: "2026-01-02T00:00:00Z" },
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect: vi.fn(),
        onToggleTag: vi.fn(),
      },
    });
    expect(queryByTestId("session-reopen-button")).toBeNull();
  });

  it("clicking the Reopen button fires onReopen and not onSelect", async () => {
    const onReopen = vi.fn();
    const onSelect = vi.fn();
    const { getByTestId } = render(SessionRow, {
      props: {
        session: { ...baseSession, closed_at: "2026-01-02T00:00:00Z" },
        tags: [],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect,
        onToggleTag: vi.fn(),
        onReopen,
      },
    });
    await fireEvent.click(getByTestId("session-reopen-button"));
    expect(onReopen).toHaveBeenCalledWith("ses_a");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("tag-chip click does not also fire the row's onSelect (event.stopPropagation)", async () => {
    const onSelect = vi.fn();
    const onToggleTag = vi.fn();
    const { getAllByTestId } = render(SessionRow, {
      props: {
        session: baseSession,
        tags: [tag(7, "x")],
        selectedTagIds: new Set<number>(),
        isSelected: false,
        onSelect,
        onToggleTag,
      },
    });
    await fireEvent.click(getAllByTestId("session-tag-chip")[0]);
    expect(onToggleTag).toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
