/**
 * Component tests for ``MessageTurn`` — user/assistant rendering,
 * routing badge surface, error block, tool drawer counter,
 * "Regenerate from here" context-menu / confirm-dialog behavior
 * (gap-cycle-03-006), and stale-target detection (gap-cycle-15-004).
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { flushSync } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { _resetForTests, contextMenuStore } from "../../../context-menu/store.svelte";
import { CONVERSATION_STRINGS, MENU_ACTION_MESSAGE_REGENERATE } from "../../../config";

import MessageTurn from "../MessageTurn.svelte";
import {
  conversationStore,
  _resetForTests as resetConversationStore,
  type MessageTurnView,
} from "../../../stores/conversation.svelte";

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
              startedAt: 0,
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
              startedAt: 0,
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
    article.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
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
    article.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
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
    article.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
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
    article.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    const handler = contextMenuStore.open?.handlers[MENU_ACTION_MESSAGE_REGENERATE];
    expect(handler).toBeDefined();
    // Narrow to callable — all MessageTurn handlers are functions (none use disabledReason).
    (handler as (() => void) | undefined)?.();

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
    article.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    (
      contextMenuStore.open?.handlers[MENU_ACTION_MESSAGE_REGENERATE] as (() => void) | undefined
    )?.();
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

// ---------------------------------------------------------------------------
// gap-cycle-06-002 — ⤴ TOOLS jump button
// ---------------------------------------------------------------------------

describe("MessageTurn — ⤴ TOOLS jump button visibility (gap-cycle-06-002)", () => {
  it("(a) renders the jump button when toolCalls.length > 0 and complete = true", () => {
    const { queryByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          toolCalls: [
            {
              id: "tc-1",
              name: "Bash",
              inputJson: "{}",
              output: "ok",
              rawLength: 2,
              done: true,
              ok: true,
              durationMs: 120,
              errorMessage: null,
              liveElapsedMs: 0,
              startedAt: 0,
            },
          ],
          complete: true,
        }),
      },
    });
    expect(queryByTestId("message-turn-jump-to-tools")).not.toBeNull();
  });

  it("(b) does NOT render the jump button when toolCalls.length === 0", () => {
    const { queryByTestId } = render(MessageTurn, {
      props: { turn: turn({ toolCalls: [], complete: true }) },
    });
    expect(queryByTestId("message-turn-jump-to-tools")).toBeNull();
  });

  it("(c) does NOT render the jump button while complete = false", () => {
    const { queryByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          toolCalls: [
            {
              id: "tc-1",
              name: "Bash",
              inputJson: "{}",
              output: "",
              rawLength: 0,
              done: false,
              ok: null,
              durationMs: null,
              errorMessage: null,
              liveElapsedMs: 0,
              startedAt: 0,
            },
          ],
          complete: false,
        }),
      },
    });
    expect(queryByTestId("message-turn-jump-to-tools")).toBeNull();
  });

  it("button label and aria-label use CONVERSATION_STRINGS.toolDrawerJumpLabel", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          toolCalls: [
            {
              id: "tc-1",
              name: "Read",
              inputJson: "{}",
              output: "",
              rawLength: 0,
              done: true,
              ok: true,
              durationMs: 50,
              errorMessage: null,
              liveElapsedMs: 0,
              startedAt: 0,
            },
          ],
          complete: true,
        }),
      },
    });
    const btn = getByTestId("message-turn-jump-to-tools");
    expect(btn.textContent?.trim()).toBe(CONVERSATION_STRINGS.toolDrawerJumpLabel);
    expect(btn.getAttribute("aria-label")).toBe(CONVERSATION_STRINGS.toolDrawerJumpLabel);
  });
});

describe("MessageTurn — ⤴ TOOLS jump button click handler (gap-cycle-06-002)", () => {
  beforeEach(() => {
    // jsdom does not implement scrollIntoView — shim it so the call is trackable.
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    _resetForTests();
  });

  it("(d) clicking opens the drawer and calls scrollIntoView({behavior:'smooth',block:'start'})", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          toolCalls: [
            {
              id: "tc-1",
              name: "Bash",
              inputJson: "{}",
              output: "exit 0",
              rawLength: 6,
              done: true,
              ok: true,
              durationMs: 80,
              errorMessage: null,
              liveElapsedMs: 0,
              startedAt: 0,
            },
          ],
          complete: true,
        }),
      },
    });

    const drawer = getByTestId("tool-work-drawer") as HTMLDetailsElement;
    const scrollSpy = vi.spyOn(drawer, "scrollIntoView");

    // Close the drawer so we can assert it re-opens on click.
    drawer.open = false;

    flushSync(() => {
      fireEvent.click(getByTestId("message-turn-jump-to-tools"));
    });

    expect(drawer.open).toBe(true);
    expect(scrollSpy).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });

  it("(d) clicking when the drawer is already open leaves it open and still scrolls", () => {
    const { getByTestId } = render(MessageTurn, {
      props: {
        turn: turn({
          toolCalls: [
            {
              id: "tc-1",
              name: "Read",
              inputJson: "{}",
              output: "content",
              rawLength: 7,
              done: true,
              ok: true,
              durationMs: 30,
              errorMessage: null,
              liveElapsedMs: 0,
              startedAt: 0,
            },
          ],
          complete: true,
        }),
      },
    });

    const drawer = getByTestId("tool-work-drawer") as HTMLDetailsElement;
    const scrollSpy = vi.spyOn(drawer, "scrollIntoView");

    // Drawer starts open (the component default for turns with tool calls).
    expect(drawer.open).toBe(true);

    flushSync(() => {
      fireEvent.click(getByTestId("message-turn-jump-to-tools"));
    });

    expect(drawer.open).toBe(true);
    expect(scrollSpy).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });
});

// ---------------------------------------------------------------------------
// gap-cycle-15-004 — stale-target detection via conversationStore.turns
// ---------------------------------------------------------------------------

describe("MessageTurn — stale-target detection (gap-cycle-15-004)", () => {
  beforeEach(() => {
    _resetForTests();
    resetConversationStore();
  });

  afterEach(() => {
    _resetForTests();
    resetConversationStore();
  });

  it("right-clicking when turn is absent from conversationStore passes stale: true", async () => {
    // conversationStore.turns is [] after reset — the turn is not present.
    const { getByTestId } = render(MessageTurn, {
      props: { turn: turn({ id: "t1", role: "assistant", body: "hello" }) },
    });
    flushSync();
    await fireEvent.contextMenu(getByTestId("message-turn"));
    expect(contextMenuStore.open?.stale).toBe(true);
  });

  it("right-clicking when turn is present in conversationStore passes stale: false", async () => {
    // Seed the turn before mounting so the derived value starts false.
    flushSync(() => {
      conversationStore.turns = [turn({ id: "t1", role: "assistant", body: "hello" })];
    });
    const { getByTestId } = render(MessageTurn, {
      props: { turn: turn({ id: "t1", role: "assistant", body: "hello" }) },
    });
    flushSync();
    await fireEvent.contextMenu(getByTestId("message-turn"));
    expect(contextMenuStore.open?.stale).toBe(false);
  });

  it("stale flag transitions to true when turn is removed from the store after mount", async () => {
    // Start with the turn present.
    flushSync(() => {
      conversationStore.turns = [turn({ id: "t1", role: "assistant", body: "hello" })];
    });
    const { getByTestId } = render(MessageTurn, {
      props: { turn: turn({ id: "t1", role: "assistant", body: "hello" }) },
    });
    flushSync();
    // Simulate WS-driven deletion (e.g., paired-chats reorg removes the row).
    flushSync(() => {
      conversationStore.turns = [];
    });
    await fireEvent.contextMenu(getByTestId("message-turn"));
    expect(contextMenuStore.open?.stale).toBe(true);
  });
});
