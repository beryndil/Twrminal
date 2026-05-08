/**
 * InspectorFiles tests — verifies path extraction, deduplication, sort
 * order, home-shortening, and the empty-state branch.
 *
 * Uses the component's ``turns`` test seam so each test owns its fixture
 * data without touching the module-singleton conversation store.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorFiles from "../InspectorFiles.svelte";
import { INSPECTOR_STRINGS } from "../../../config";
import type { MessageTurnView, ToolCallView } from "../../../stores/conversation.svelte";
import type { SessionOut } from "../../../api/sessions";

function fakeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "Fixture",
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
  };
}

function fakeTurn(overrides: Partial<MessageTurnView> = {}): MessageTurnView {
  return {
    id: "t1",
    role: "assistant",
    body: "",
    thinking: "",
    complete: true,
    toolCalls: [],
    routing: null,
    error: null,
    createdAt: "2026-01-01T12:00:00Z",
    resumed: false,
    seq: 1,
    attachments: [],
    stopped: false,
    ...overrides,
  };
}

function fakeToolCall(overrides: Partial<ToolCallView> = {}): ToolCallView {
  return {
    id: "tc1",
    name: "Read",
    inputJson: JSON.stringify({ file_path: "/home/dave/foo.txt" }),
    output: "",
    rawLength: 0,
    done: true,
    ok: true,
    durationMs: 10,
    errorMessage: null,
    liveElapsedMs: 0,
    startedAt: 0,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe("InspectorFiles — empty state", () => {
  it("shows empty-state copy when no turns are provided", () => {
    const { getByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns: [] },
    });
    const emptyEl = getByTestId("inspector-files-empty");
    expect(emptyEl).toBeInTheDocument();
    expect(emptyEl).toHaveTextContent(INSPECTOR_STRINGS.filesEmptyHeading);
    expect(emptyEl).toHaveTextContent(INSPECTOR_STRINGS.filesEmptyBody);
  });

  it("shows empty state when turns contain only Bash and Glob calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Bash",
            inputJson: JSON.stringify({ command: "ls -la" }),
          }),
          fakeToolCall({
            id: "tc2",
            name: "Glob",
            inputJson: JSON.stringify({ pattern: "**/*.ts" }),
          }),
        ],
      }),
    ];
    const { getByTestId, queryByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-files-empty")).toBeInTheDocument();
    expect(queryByTestId("inspector-files-list")).toBeNull();
  });

  it("shows empty state when tool inputJson has no recognised path key", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Read",
            inputJson: JSON.stringify({ offset: 10, limit: 50 }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-files-empty")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Row rendering and deduplication
// ---------------------------------------------------------------------------

describe("InspectorFiles — row rendering", () => {
  it("renders one row per distinct file path", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/a.txt" }),
          }),
          fakeToolCall({
            id: "tc2",
            name: "Write",
            inputJson: JSON.stringify({ file_path: "/tmp/b.txt" }),
          }),
        ],
      }),
    ];
    const { getAllByTestId, queryByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(getAllByTestId("inspector-files-row")).toHaveLength(2);
    expect(queryByTestId("inspector-files-empty")).toBeNull();
  });

  it("deduplicates multiple touches to the same path into one row with a count badge", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/file.ts" }),
            startedAt: 1000,
          }),
          fakeToolCall({
            id: "tc2",
            name: "Edit",
            inputJson: JSON.stringify({ file_path: "/tmp/file.ts" }),
            startedAt: 2000,
          }),
        ],
      }),
    ];
    const { getAllByTestId, getByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(getAllByTestId("inspector-files-row")).toHaveLength(1);
    // badge shows × 2
    expect(getByTestId("inspector-files-count-badge")).toHaveTextContent("× 2");
  });

  it("does not render a count badge when a file was touched exactly once", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/once.ts" }),
          }),
        ],
      }),
    ];
    const { queryByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(queryByTestId("inspector-files-count-badge")).toBeNull();
  });

  it("shows the last action verb after multiple touches", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/f.ts" }),
            startedAt: 100,
          }),
          fakeToolCall({
            id: "tc2",
            name: "Edit",
            inputJson: JSON.stringify({ file_path: "/tmp/f.ts" }),
            startedAt: 200,
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    // "Edit" is the most-recent verb
    expect(getByTestId("inspector-files-verb")).toHaveTextContent("Edit");
  });

  it("extracts notebook_path for NotebookEdit tool calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "NotebookEdit",
            inputJson: JSON.stringify({ notebook_path: "/tmp/analysis.ipynb" }),
          }),
        ],
      }),
    ];
    const { getAllByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    const rows = getAllByTestId("inspector-files-row");
    expect(rows).toHaveLength(1);
    expect(rows[0].querySelector("[data-testid='inspector-files-path']")).toHaveTextContent(
      "analysis.ipynb",
    );
  });

  it("extracts path for Grep tool calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Grep",
            inputJson: JSON.stringify({ pattern: "TODO", path: "/tmp/src/main.ts" }),
          }),
        ],
      }),
    ];
    const { getAllByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(getAllByTestId("inspector-files-row")).toHaveLength(1);
    expect(getAllByTestId("inspector-files-path")[0]).toHaveTextContent("main.ts");
  });
});

// ---------------------------------------------------------------------------
// Home-path shortening
// ---------------------------------------------------------------------------

describe("InspectorFiles — ~/... shortening", () => {
  it("shortens /home/<user>/... paths to ~/...", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/home/beryndil/Projects/foo.ts" }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-files-path")).toHaveTextContent("~/Projects/foo.ts");
  });

  it("preserves the full path as the title tooltip while displaying the short form", () => {
    const fullPath = "/home/beryndil/Projects/foo.ts";
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Read",
            inputJson: JSON.stringify({ file_path: fullPath }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    const pathEl = getByTestId("inspector-files-path");
    expect(pathEl.getAttribute("title")).toBe(fullPath);
    expect(pathEl).toHaveTextContent("~/Projects/foo.ts");
  });

  it("leaves paths that do not start with /home/ unchanged", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/workspace/file.ts" }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-files-path")).toHaveTextContent("/tmp/workspace/file.ts");
  });
});

// ---------------------------------------------------------------------------
// Sort order
// ---------------------------------------------------------------------------

describe("InspectorFiles — sort order", () => {
  it("sorts rows most-recent-touch first when startedAt is available", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/older.ts" }),
            startedAt: 1_000,
          }),
          fakeToolCall({
            id: "tc2",
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/newer.ts" }),
            startedAt: 2_000,
          }),
        ],
      }),
    ];
    const { getAllByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns },
    });
    const paths = getAllByTestId("inspector-files-path").map((el) => el.textContent?.trim());
    expect(paths[0]).toBe("/tmp/newer.ts");
    expect(paths[1]).toBe("/tmp/older.ts");
  });

  it("places rows with null timestamp after timestamped rows", () => {
    // tc1 has startedAt=0 and turn createdAt=null → null timestamp
    // tc2 has startedAt=999 → defined timestamp
    const nullTimestampTurn = fakeTurn({
      id: "t1",
      createdAt: null,
      toolCalls: [
        fakeToolCall({
          id: "tc1",
          name: "Read",
          inputJson: JSON.stringify({ file_path: "/tmp/no-ts.ts" }),
          startedAt: 0,
        }),
      ],
    });
    const timestampedTurn = fakeTurn({
      id: "t2",
      toolCalls: [
        fakeToolCall({
          id: "tc2",
          name: "Read",
          inputJson: JSON.stringify({ file_path: "/tmp/has-ts.ts" }),
          startedAt: 999,
        }),
      ],
    });
    const { getAllByTestId } = render(InspectorFiles, {
      props: { session: fakeSession(), turns: [nullTimestampTurn, timestampedTurn] },
    });
    const paths = getAllByTestId("inspector-files-path").map((el) => el.textContent?.trim());
    expect(paths[0]).toBe("/tmp/has-ts.ts");
    expect(paths[1]).toBe("/tmp/no-ts.ts");
  });
});
