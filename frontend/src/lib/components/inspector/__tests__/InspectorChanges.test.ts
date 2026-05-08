/**
 * InspectorChanges tests — verifies verb mapping, excerpt extraction,
 * home-path shortening, sort order, and the empty-state branch.
 *
 * Uses the component's ``turns`` test seam so each test owns its
 * fixture data without touching the module-singleton conversation store.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorChanges from "../InspectorChanges.svelte";
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
    name: "Write",
    inputJson: JSON.stringify({
      file_path: "/home/dave/foo.ts",
      content: "export const x = 1;",
    }),
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

describe("InspectorChanges — empty state", () => {
  it("shows empty-state copy when no turns are provided", () => {
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns: [] },
    });
    const emptyEl = getByTestId("inspector-changes-empty");
    expect(emptyEl).toBeInTheDocument();
    expect(emptyEl).toHaveTextContent(INSPECTOR_STRINGS.changesEmptyHeading);
    expect(emptyEl).toHaveTextContent(INSPECTOR_STRINGS.changesEmptyBody);
  });

  it("shows empty state when turns contain only Read/Grep/Glob calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/a.ts" }),
          }),
          fakeToolCall({
            id: "tc2",
            name: "Grep",
            inputJson: JSON.stringify({ pattern: "foo", path: "/tmp" }),
          }),
          fakeToolCall({
            id: "tc3",
            name: "Glob",
            inputJson: JSON.stringify({ pattern: "**/*.ts" }),
          }),
        ],
      }),
    ];
    const { getByTestId, queryByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-empty")).toBeInTheDocument();
    expect(queryByTestId("inspector-changes-list")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Verb mapping
// ---------------------------------------------------------------------------

describe("InspectorChanges — verb mapping", () => {
  it('maps Write tool to "Created" verb', () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/new.ts",
              content: "const x = 1;",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-verb")).toHaveTextContent("Created");
  });

  it('maps Edit tool to "Edited" verb', () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Edit",
            inputJson: JSON.stringify({
              file_path: "/tmp/existing.ts",
              old_string: "const x = 1;",
              new_string: "const x = 2;",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-verb")).toHaveTextContent("Edited");
  });

  it('maps NotebookEdit tool to "Notebook-edited" verb', () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "NotebookEdit",
            inputJson: JSON.stringify({
              notebook_path: "/tmp/analysis.ipynb",
              new_source: "import pandas as pd",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-verb")).toHaveTextContent("Notebook-edited");
  });
});

// ---------------------------------------------------------------------------
// Excerpt extraction
// ---------------------------------------------------------------------------

describe("InspectorChanges — excerpt extraction", () => {
  it("uses the content field for Write calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/f.ts",
              content: "export const answer = 42;",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-excerpt")).toHaveTextContent("export const answer = 42;");
  });

  it("uses the new_string field for Edit calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Edit",
            inputJson: JSON.stringify({
              file_path: "/tmp/f.ts",
              old_string: "const x = 1;",
              new_string: "const x = 99;",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-excerpt")).toHaveTextContent("const x = 99;");
  });

  it("uses the new_source field for NotebookEdit calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "NotebookEdit",
            inputJson: JSON.stringify({
              notebook_path: "/tmp/nb.ipynb",
              new_source: "import numpy as np",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-excerpt")).toHaveTextContent("import numpy as np");
  });

  it("takes only the first newline-delimited line of multi-line content", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/f.ts",
              content: "line one\nline two\nline three",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    const excerptEl = getByTestId("inspector-changes-excerpt");
    expect(excerptEl).toHaveTextContent("line one");
    expect(excerptEl).not.toHaveTextContent("line two");
  });

  it("trims leading whitespace from the first line", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Edit",
            inputJson: JSON.stringify({
              file_path: "/tmp/f.ts",
              old_string: "",
              new_string: "   indented content",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-excerpt")).toHaveTextContent("indented content");
  });

  it("clips the first line to 120 characters", () => {
    const longLine = "x".repeat(200);
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/f.ts",
              content: longLine,
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    const text = getByTestId("inspector-changes-excerpt").textContent ?? "";
    expect(text.trim().length).toBe(120);
  });

  it("does not render the excerpt element when the content field is absent", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Write",
            // content key intentionally missing
            inputJson: JSON.stringify({ file_path: "/tmp/f.ts" }),
          }),
        ],
      }),
    ];
    const { queryByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(queryByTestId("inspector-changes-excerpt")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Row rendering — one row per tool call (no deduplication)
// ---------------------------------------------------------------------------

describe("InspectorChanges — row rendering", () => {
  it("renders one row per Write-side tool call", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/a.ts",
              content: "a",
            }),
          }),
          fakeToolCall({
            id: "tc2",
            name: "Edit",
            inputJson: JSON.stringify({
              file_path: "/tmp/a.ts",
              old_string: "a",
              new_string: "b",
            }),
          }),
        ],
      }),
    ];
    // Two Write-side calls on the same file → two rows (no dedup)
    const { getAllByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getAllByTestId("inspector-changes-row")).toHaveLength(2);
  });

  it("skips Read / Grep / Glob / Bash calls", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Read",
            inputJson: JSON.stringify({ file_path: "/tmp/a.ts" }),
          }),
          fakeToolCall({
            id: "tc2",
            name: "Bash",
            inputJson: JSON.stringify({ command: "ls" }),
          }),
          fakeToolCall({
            id: "tc3",
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/b.ts",
              content: "ok",
            }),
          }),
        ],
      }),
    ];
    const { getAllByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    // Only the Write call survives
    expect(getAllByTestId("inspector-changes-row")).toHaveLength(1);
  });

  it("shortens /home/<user>/... paths to ~/...", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/home/beryndil/Projects/foo.ts",
              content: "x",
            }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-path")).toHaveTextContent("~/Projects/foo.ts");
  });

  it("preserves the full path in the title tooltip", () => {
    const fullPath = "/home/beryndil/Projects/foo.ts";
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            name: "Write",
            inputJson: JSON.stringify({ file_path: fullPath, content: "x" }),
          }),
        ],
      }),
    ];
    const { getByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    expect(getByTestId("inspector-changes-path").getAttribute("title")).toBe(fullPath);
  });
});

// ---------------------------------------------------------------------------
// Sort order
// ---------------------------------------------------------------------------

describe("InspectorChanges — sort order", () => {
  it("sorts rows most-recent first when startedAt is available", () => {
    const turns = [
      fakeTurn({
        toolCalls: [
          fakeToolCall({
            id: "tc1",
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/older.ts",
              content: "older",
            }),
            startedAt: 1_000,
          }),
          fakeToolCall({
            id: "tc2",
            name: "Write",
            inputJson: JSON.stringify({
              file_path: "/tmp/newer.ts",
              content: "newer",
            }),
            startedAt: 2_000,
          }),
        ],
      }),
    ];
    const { getAllByTestId } = render(InspectorChanges, {
      props: { session: fakeSession(), turns },
    });
    const paths = getAllByTestId("inspector-changes-path").map((el) => el.textContent?.trim());
    expect(paths[0]).toBe("/tmp/newer.ts");
    expect(paths[1]).toBe("/tmp/older.ts");
  });

  it("places rows with null timestamp after timestamped rows", () => {
    const nullTimestampTurn = fakeTurn({
      id: "t1",
      createdAt: null,
      toolCalls: [
        fakeToolCall({
          id: "tc1",
          name: "Write",
          inputJson: JSON.stringify({ file_path: "/tmp/no-ts.ts", content: "x" }),
          startedAt: 0,
        }),
      ],
    });
    const timestampedTurn = fakeTurn({
      id: "t2",
      toolCalls: [
        fakeToolCall({
          id: "tc2",
          name: "Write",
          inputJson: JSON.stringify({ file_path: "/tmp/has-ts.ts", content: "y" }),
          startedAt: 999,
        }),
      ],
    });
    const { getAllByTestId } = render(InspectorChanges, {
      props: {
        session: fakeSession(),
        turns: [nullTimestampTurn, timestampedTurn],
      },
    });
    const paths = getAllByTestId("inspector-changes-path").map((el) => el.textContent?.trim());
    expect(paths[0]).toBe("/tmp/has-ts.ts");
    expect(paths[1]).toBe("/tmp/no-ts.ts");
  });
});
