/**
 * Component tests for ``MessageTurn`` — user/assistant rendering,
 * routing badge surface, error block, tool drawer counter, and
 * "Regenerate from here" context-menu / confirm-dialog behavior
 * (gap-cycle-03-006).
 */
import { render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { _resetForTests, contextMenuStore } from "../../../context-menu/store.svelte";
import { MENU_ACTION_MESSAGE_REGENERATE } from "../../../config";

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

beforeEach(() => {
  _resetForTests();
});

afterEach(() => {
  _resetForTests();
});

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

// ---- Regenerate from here (gap-cycle-03-006) -------------------------------

describe("MessageTurn — Regenerate from here context-menu entry", () => {
  it("includes MENU_ACTION_MESSAGE_REGENERATE handler for non-last assistant turn", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "a1", role: "assistant", body: "reply" }),
        sessionId: "ses_a",
        isLastAssistantTurn: false,
        turnsAfterCount: 2,
      },
    });
    const article = getByTestId("message-turn");
    article.dispatchEvent(
      new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
    );
    const handlers = contextMenuStore.open?.handlers ?? {};
    expect(MENU_ACTION_MESSAGE_REGENERATE in handlers).toBe(true);
  });

  it("omits MENU_ACTION_MESSAGE_REGENERATE handler for the last assistant turn", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "a1", role: "assistant", body: "reply" }),
        sessionId: "ses_a",
        isLastAssistantTurn: true,
        turnsAfterCount: 0,
      },
    });
    const article = getByTestId("message-turn");
    article.dispatchEvent(
      new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
    );
    const handlers = contextMenuStore.open?.handlers ?? {};
    expect(MENU_ACTION_MESSAGE_REGENERATE in handlers).toBe(false);
  });

  it("omits MENU_ACTION_MESSAGE_REGENERATE handler for user turns", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "u1", role: "user", body: "prompt" }),
        sessionId: "ses_a",
        isLastAssistantTurn: false,
        turnsAfterCount: 1,
      },
    });
    const article = getByTestId("message-turn");
    article.dispatchEvent(
      new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
    );
    const handlers = contextMenuStore.open?.handlers ?? {};
    expect(MENU_ACTION_MESSAGE_REGENERATE in handlers).toBe(false);
  });

  it("shows confirmation dialog with correct discard count when handler fires", async () => {
    const { getByTestId, queryByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "a1", role: "assistant", body: "reply" }),
        sessionId: "ses_a",
        isLastAssistantTurn: false,
        turnsAfterCount: 2,
      },
    });

    // No dialog initially.
    expect(queryByTestId("confirm-dialog")).toBeNull();

    // Fire the context-menu handler.
    const article = getByTestId("message-turn");
    article.dispatchEvent(
      new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
    );
    const handler = contextMenuStore.open?.handlers[MENU_ACTION_MESSAGE_REGENERATE];
    expect(handler).toBeDefined();
    handler?.();

    // Dialog should appear with discard count = turnsAfterCount + 1 = 3.
    await waitFor(() => {
      expect(queryByTestId("confirm-dialog")).not.toBeNull();
    });
    expect(getByTestId("confirm-dialog-message").textContent).toContain("3 message");
  });

  it("dismiss cancels without calling the API", async () => {
    const { getByTestId, queryByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "a1", role: "assistant" }),
        sessionId: "ses_a",
        isLastAssistantTurn: false,
        turnsAfterCount: 1,
      },
    });
    const article = getByTestId("message-turn");
    article.dispatchEvent(
      new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
    );
    contextMenuStore.open?.handlers[MENU_ACTION_MESSAGE_REGENERATE]?.();
    await waitFor(() => expect(queryByTestId("confirm-dialog")).not.toBeNull());

    getByTestId("confirm-dialog-cancel").click();
    await waitFor(() => expect(queryByTestId("confirm-dialog")).toBeNull());
  });
});

// ---------------------------------------------------------------------------
// gap-cycle-03-007 — spawn-from-reply pill (＋ SPAWN)
// ---------------------------------------------------------------------------

describe("MessageTurn — spawn pill (gap-cycle-03-007)", () => {
  it("renders the spawn pill on assistant turns in non-paired sessions", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "a1", role: "assistant", body: "hello" }),
        sessionId: "ses_parent",
        isPaired: false,
      },
    });
    expect(getByTestId("message-turn-spawn-pill")).toBeTruthy();
  });

  it("does NOT render the spawn pill on user turns", () => {
    const { queryByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "u1", role: "user", body: "hi" }),
        sessionId: "ses_parent",
        isPaired: false,
      },
    });
    expect(queryByTestId("message-turn-spawn-pill")).toBeNull();
  });

  it("does NOT render the spawn pill when the session is paired", () => {
    const { queryByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "a1", role: "assistant", body: "hello" }),
        sessionId: "ses_parent",
        isPaired: true,
      },
    });
    expect(queryByTestId("message-turn-spawn-pill")).toBeNull();
  });

  it("omits the spawn pill when isPaired defaults to false but role is user", () => {
    const { queryByTestId } = render(MessageTurn, {
      props: {
        turn: turn({ id: "u2", role: "user", body: "hi" }),
        sessionId: "ses_parent",
      },
    });
    expect(queryByTestId("message-turn-spawn-pill")).toBeNull();
  });
});
