/**
 * Component tests for ``MessageTurn`` — user/assistant rendering,
 * routing badge surface, error block, tool drawer counter.
 */
import { render, waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import MessageTurn from "../MessageTurn.svelte";
import type { MessageTurnView } from "../../../stores/conversation.svelte";

function turn(overrides: Partial<MessageTurnView> = {}): MessageTurnView {
  return {
    id: "t1",
    role: "assistant",
    body: "",
    thinking: "",
    complete: false,
    toolCalls: [],
    routing: null,
    error: null,
    createdAt: null,
    resumed: false,
    seq: 0,
    attachments: [],
    ...overrides,
  };
}

describe("MessageTurn — user role", () => {
  it("renders the user body text content", () => {
    const { getByTestId } = render(MessageTurn, {
      props: { turn: turn({ id: "u1", role: "user", body: "hello", complete: true }) },
    });
    expect(getByTestId("message-turn-user-body")).toHaveTextContent("hello");
  });

  it("linkifies URLs in the user body", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          id: "u1",
          role: "user",
          body: "see https://example.com please",
          complete: true,
        }),
      },
    });
    const html = getByTestId("message-turn-user-body").innerHTML;
    expect(html).toContain('href="https://example.com"');
    expect(html).toContain("noopener");
  });
});

describe("MessageTurn — assistant role", () => {
  it("renders the assistant bubble", () => {
    const { getByTestId } = render(MessageTurn, {
      props: { turn: turn({ id: "a1", body: "hi" }) },
    });
    expect(getByTestId("message-turn-assistant")).toBeTruthy();
  });

  it("renders the routing badge when present", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          id: "a1",
          body: "hi",
          routing: {
            executorModel: "sonnet",
            advisorModel: null,
            advisorCallsCount: 0,
            effortLevel: "med",
            routingSource: "tag_rule",
            routingReason: "matched bearings/architect",
          },
        }),
      },
    });
    expect(getByTestId("routing-badge")).toHaveAttribute("data-executor-model", "sonnet");
  });

  it("renders the error block when the turn carried an error", () => {
    const { getByTestId } = render(MessageTurn, {
      props: { turn: turn({ id: "a1", error: "boom", complete: true }) },
    });
    expect(getByTestId("message-turn-error")).toHaveTextContent("boom");
  });

  it("renders the tool-work drawer with one row per tool call", () => {
    const { getAllByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          id: "a1",
          toolCalls: [
            {
              id: "t1",
              name: "Bash",
              inputJson: "{}",
              output: "",
              rawLength: 0,
              done: false,
              ok: null,
              durationMs: null,
              errorMessage: null,
              liveElapsedMs: 0,
            },
            {
              id: "t2",
              name: "Read",
              inputJson: "{}",
              output: "",
              rawLength: 0,
              done: false,
              ok: null,
              durationMs: null,
              errorMessage: null,
              liveElapsedMs: 0,
            },
          ],
        }),
      },
    });
    expect(getAllByTestId("tool-output")).toHaveLength(2);
  });

  it("renders the markdown body via the sanitizer", async () => {
    const { getByTestId } = render(MessageTurn, {
      props: { turn: turn({ id: "a1", body: "**bold**" }) },
    });
    // Body rendering is async; wait for the sanitized HTML to land.
    await waitFor(() => {
      expect(getByTestId("message-turn-body").innerHTML).toContain("<strong>bold</strong>");
    });
  });
});
