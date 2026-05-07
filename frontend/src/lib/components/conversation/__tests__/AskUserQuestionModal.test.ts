/**
 * Component tests for ``AskUserQuestionModal`` covering the three input
 * shapes the component supports:
 *
 * 1. **Structured** ``{questions: [...]}`` — the current Claude Code
 *    AskUserQuestion shape with per-question ``options`` and a
 *    ``multiSelect`` flag. The user picks one option per radio group
 *    or any number per checkbox group; the modal serialises the picks
 *    as labelled lines into the ``answer`` string posted back.
 * 2. **Legacy** ``{question: "..."}`` — the original v1 free-text
 *    shape; the user types into a textarea.
 * 3. **Unknown** — neither shape recognised. The modal pretty-prints
 *    the raw JSON and degrades to a free-text answer box rather than
 *    showing the user the raw blob.
 *
 * The shared submit path is the same in all three cases: ``postApproval``
 * is called with ``approved=true`` and the encoded answer string.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ``vi.mock`` is hoisted above the import block, so the mock factory
// can't close over a top-level binding. Use ``vi.hoisted`` to stash the
// shared spy in a hoisted slot the factory can read at module-init time.
const { postApprovalMock } = vi.hoisted(() => ({ postApprovalMock: vi.fn() }));

vi.mock("../../../api/approvals", () => ({
  postApproval: postApprovalMock,
}));

import AskUserQuestionModal from "../AskUserQuestionModal.svelte";
import type { PendingApproval } from "../../../stores/conversation.svelte";

function makeApproval(toolInput: unknown): PendingApproval {
  return {
    requestId: "req_test",
    toolName: "AskUserQuestion",
    toolInputJson: typeof toolInput === "string" ? toolInput : JSON.stringify(toolInput),
  };
}

const STRUCTURED_FIXTURE = {
  questions: [
    {
      header: "Schema",
      question: "How should the two-class distinction be encoded?",
      multiSelect: false,
      options: [
        { label: "First-class column", description: "Add a column." },
        { label: "Slash-prefixes", description: "No schema change." },
        { label: "Both", description: "Most expressive." },
      ],
    },
    {
      header: "Cardinality",
      question: "How many tags of each class can a session carry?",
      multiSelect: false,
      options: [{ label: "1 project, 0-or-1 severity" }, { label: "Many of each" }],
    },
  ],
} as const;

beforeEach(() => {
  postApprovalMock.mockReset();
  postApprovalMock.mockResolvedValue(undefined);
});
afterEach(() => {
  vi.clearAllMocks();
});

describe("AskUserQuestionModal — structured questions[]", () => {
  it("renders one block per question with header, prompt, and options", () => {
    const { getAllByTestId, getByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_a", approval: makeApproval(STRUCTURED_FIXTURE) },
    });
    expect(getByTestId("ask-modal-structured")).toBeTruthy();
    const headers = getAllByTestId("ask-modal-question-header");
    expect(headers.map((el) => el.textContent)).toEqual(["Schema", "Cardinality"]);
    // 3 + 2 = 5 radios across the two single-select questions.
    expect(getAllByTestId("ask-modal-radio").length).toBe(5);
  });

  it("disables submit until every question has a selection", async () => {
    const { getAllByTestId, getByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_a", approval: makeApproval(STRUCTURED_FIXTURE) },
    });
    const submit = getByTestId("ask-modal-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    const radios = getAllByTestId("ask-modal-radio") as HTMLInputElement[];
    // Pick the first option of question 1 only.
    await fireEvent.click(radios[0]);
    expect(submit.disabled).toBe(true);
    // Now the first option of question 2.
    await fireEvent.click(radios[3]);
    expect(submit.disabled).toBe(false);
  });

  it("submits one labelled line per question", async () => {
    const { getAllByTestId, getByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_a", approval: makeApproval(STRUCTURED_FIXTURE) },
    });
    const radios = getAllByTestId("ask-modal-radio") as HTMLInputElement[];
    await fireEvent.click(radios[0]); // Schema → First-class column
    await fireEvent.click(radios[3]); // Cardinality → 1 project, 0-or-1 severity
    await fireEvent.click(getByTestId("ask-modal-submit"));
    await waitFor(() => {
      expect(postApprovalMock).toHaveBeenCalledTimes(1);
    });
    const [sessionId, requestId, approved, answer] = postApprovalMock.mock.calls[0];
    expect(sessionId).toBe("ses_a");
    expect(requestId).toBe("req_test");
    expect(approved).toBe(true);
    expect(answer).toBe("Schema: First-class column\nCardinality: 1 project, 0-or-1 severity");
  });

  it("renders checkboxes for multiSelect=true and joins picks with comma+space", async () => {
    const multi = {
      questions: [
        {
          header: "Severity",
          question: "Which severities apply?",
          multiSelect: true,
          options: [{ label: "low" }, { label: "medium" }, { label: "high" }],
        },
      ],
    };
    const { getAllByTestId, getByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_a", approval: makeApproval(multi) },
    });
    const checkboxes = getAllByTestId("ask-modal-checkbox") as HTMLInputElement[];
    expect(checkboxes.length).toBe(3);
    await fireEvent.click(checkboxes[0]); // low
    await fireEvent.click(checkboxes[2]); // high
    await fireEvent.click(getByTestId("ask-modal-submit"));
    await waitFor(() => {
      expect(postApprovalMock).toHaveBeenCalledTimes(1);
    });
    expect(postApprovalMock.mock.calls[0][3]).toBe("Severity: low, high");
  });

  it("shows a single-select hint by default and a multi-select hint when flagged", () => {
    const mixed = {
      questions: [
        {
          header: "A",
          question: "Pick one",
          multiSelect: false,
          options: [{ label: "x" }, { label: "y" }],
        },
        {
          header: "B",
          question: "Pick any",
          multiSelect: true,
          options: [{ label: "x" }, { label: "y" }],
        },
      ],
    };
    const { getAllByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_a", approval: makeApproval(mixed) },
    });
    const hints = getAllByTestId("ask-modal-select-hint");
    expect(hints[0].textContent).toBe("Pick one");
    expect(hints[1].textContent).toBe("Pick one or more");
  });
});

describe("AskUserQuestionModal — legacy {question}", () => {
  it("renders the question text and submits the typed answer", async () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      props: {
        sessionId: "ses_a",
        approval: makeApproval({ question: "Are you sure?" }),
      },
    });
    expect(getByTestId("ask-modal-question").textContent).toBe("Are you sure?");
    const textarea = getByTestId("ask-modal-answer") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "yes" } });
    await fireEvent.click(getByTestId("ask-modal-submit"));
    await waitFor(() => {
      expect(postApprovalMock).toHaveBeenCalledWith("ses_a", "req_test", true, "yes");
    });
  });

  it("disables submit while the textarea is empty or whitespace-only", async () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      props: {
        sessionId: "ses_a",
        approval: makeApproval({ question: "Hi?" }),
      },
    });
    const submit = getByTestId("ask-modal-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    const textarea = getByTestId("ask-modal-answer") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "   " } });
    expect(submit.disabled).toBe(true);
    await fireEvent.input(textarea, { target: { value: "ok" } });
    expect(submit.disabled).toBe(false);
  });
});

describe("AskUserQuestionModal — Cancel button (gap-cycle-10-007)", () => {
  it("renders a Cancel button alongside Submit", () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_a", approval: makeApproval({ question: "Continue?" }) },
    });
    expect(getByTestId("ask-modal-cancel")).toBeTruthy();
    expect(getByTestId("ask-modal-submit")).toBeTruthy();
  });

  it("Cancel POSTs approved=false (deny) with no answer", async () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_b", approval: makeApproval({ question: "Proceed?" }) },
    });
    await fireEvent.click(getByTestId("ask-modal-cancel"));
    await waitFor(() => {
      expect(postApprovalMock).toHaveBeenCalledTimes(1);
    });
    const [sessionId, requestId, approved, answer] = postApprovalMock.mock.calls[0];
    expect(sessionId).toBe("ses_b");
    expect(requestId).toBe("req_test");
    expect(approved).toBe(false);
    expect(answer).toBeUndefined();
  });

  it("Submit still works after Cancel button is present", async () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_c", approval: makeApproval({ question: "What?" }) },
    });
    const textarea = getByTestId("ask-modal-answer") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "my answer" } });
    await fireEvent.click(getByTestId("ask-modal-submit"));
    await waitFor(() => {
      expect(postApprovalMock).toHaveBeenCalledTimes(1);
    });
    const [sessionId, requestId, approved, answer] = postApprovalMock.mock.calls[0];
    expect(sessionId).toBe("ses_c");
    expect(requestId).toBe("req_test");
    expect(approved).toBe(true);
    expect(answer).toBe("my answer");
  });
});

describe("AskUserQuestionModal — unknown shape fallback", () => {
  it("pretty-prints the raw JSON and falls back to a free-text answer box", async () => {
    const { getByTestId, queryByTestId } = render(AskUserQuestionModal, {
      props: {
        sessionId: "ses_a",
        approval: makeApproval({ unexpected: "shape", n: 7 }),
      },
    });
    expect(queryByTestId("ask-modal-structured")).toBeNull();
    expect(getByTestId("ask-modal-unknown-notice")).toBeTruthy();
    const pretty = getByTestId("ask-modal-unknown-pretty");
    expect(pretty.textContent).toContain('"unexpected": "shape"');
    expect(pretty.textContent).toContain('"n": 7');
    const textarea = getByTestId("ask-modal-answer") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "manual answer" } });
    await fireEvent.click(getByTestId("ask-modal-submit"));
    await waitFor(() => {
      expect(postApprovalMock).toHaveBeenCalledWith("ses_a", "req_test", true, "manual answer");
    });
  });

  it("falls back when JSON parsing fails entirely (raw non-JSON input)", () => {
    const { getByTestId, queryByTestId } = render(AskUserQuestionModal, {
      props: {
        sessionId: "ses_a",
        approval: makeApproval("not-actually-json"),
      },
    });
    expect(getByTestId("ask-modal-unknown-notice")).toBeTruthy();
    expect(getByTestId("ask-modal-unknown-pretty").textContent).toBe("not-actually-json");
    expect(queryByTestId("ask-modal-structured")).toBeNull();
    expect(queryByTestId("ask-modal-question")).toBeNull();
  });

  it("falls back when questions[] is malformed (no readable options)", () => {
    const malformed = {
      questions: [{ question: "x", options: [{ no_label: true }] }],
    };
    const { getByTestId, queryByTestId } = render(AskUserQuestionModal, {
      props: { sessionId: "ses_a", approval: makeApproval(malformed) },
    });
    expect(getByTestId("ask-modal-unknown-notice")).toBeTruthy();
    expect(queryByTestId("ask-modal-structured")).toBeNull();
  });
});
