/**
 * Component tests for :class:`ChecklistChat`.
 *
 * Done-when criteria covered:
 *
 * - send → user bubble appears immediately (optimistic insert).
 * - Streaming delta updates the assistant turn text in-place.
 * - Send button is disabled while the 202 handshake is in flight.
 *
 * All network calls are stubbed via the component's seam props.
 * The WebSocket is replaced with a minimal mock that exposes the
 * registered ``message`` handler so tests can simulate server frames.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import ChecklistChat from "../ChecklistChat.svelte";
import type { MessageOut, MessagePage } from "../../../api/messages";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emptyPage(): MessagePage {
  return { items: [], has_more: false };
}

function fakeMessage(overrides: Partial<MessageOut> = {}): MessageOut {
  return {
    id: "msg_a",
    session_id: "cl_a",
    role: "user",
    content: "Hello",
    created_at: "2026-05-06T00:00:00Z",
    executor_model: null,
    advisor_model: null,
    effort_level: null,
    routing_source: null,
    routing_reason: null,
    matched_rule_id: null,
    executor_input_tokens: null,
    executor_output_tokens: null,
    advisor_input_tokens: null,
    advisor_output_tokens: null,
    advisor_calls_count: null,
    cache_read_tokens: null,
    input_tokens: null,
    output_tokens: null,
    seq: 1,
    pinned: false,
    hidden_from_context: false,
    evaluated_rules: [],
    ...overrides,
  };
}

/** Build a minimal WebSocket mock that captures the ``message`` listener. */
interface MockWs {
  messageHandler: ((event: MessageEvent) => void) | null;
  closeCalled: boolean;
  ws: {
    addEventListener: ReturnType<typeof vi.fn>;
    removeEventListener: ReturnType<typeof vi.fn>;
    close: ReturnType<typeof vi.fn>;
  };
}

function makeMockWs(): MockWs {
  const mock: MockWs = {
    messageHandler: null,
    closeCalled: false,
    ws: {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      close: vi.fn(),
    },
  };
  mock.ws.addEventListener.mockImplementation((event: string, fn: unknown) => {
    if (event === "message") {
      mock.messageHandler = fn as (event: MessageEvent) => void;
    }
  });
  mock.ws.close.mockImplementation(() => {
    mock.closeCalled = true;
  });
  return mock;
}

function eventFrame(type: string, extra: Record<string, unknown> = {}): string {
  return JSON.stringify({ kind: "event", seq: 1, event: { session_id: "cl_a", type, ...extra } });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChecklistChat — send → user bubble appears", () => {
  it("adds the user bubble immediately after clicking Send", async () => {
    const sendPromptFn = vi.fn().mockResolvedValue({ queued: true, session_id: "cl_a" });
    const listMessagesFn = vi.fn().mockResolvedValue(emptyPage());
    const mock = makeMockWs();
    const createWs = vi.fn().mockReturnValue(mock.ws);

    const { getByTestId, getAllByTestId } = render(ChecklistChat, {
      props: { checklistId: "cl_a", sendPromptFn, listMessagesFn, createWs },
    });

    const input = getByTestId("checklist-chat-input");
    const sendBtn = getByTestId("checklist-chat-send");

    // Type a message and send.
    await fireEvent.input(input, { target: { value: "add five items about CI" } });
    await fireEvent.click(sendBtn);

    await waitFor(() => {
      const turnEls = getAllByTestId("checklist-chat-turn");
      const texts = turnEls.map((el) => el.textContent ?? "");
      expect(texts.some((t) => t.includes("add five items about CI"))).toBe(true);
    });
  });
});

describe("ChecklistChat — streaming delta updates", () => {
  it("appends token deltas and shows the cursor during streaming", async () => {
    const sendPromptFn = vi.fn().mockResolvedValue({ queued: true, session_id: "cl_a" });
    const listMessagesFn = vi.fn().mockResolvedValue(emptyPage());
    const mock = makeMockWs();
    const createWs = vi.fn().mockReturnValue(mock.ws);

    const { getByTestId, getAllByTestId, queryByTestId } = render(ChecklistChat, {
      props: { checklistId: "cl_a", sendPromptFn, listMessagesFn, createWs },
    });

    // Wait for the WS listener to be registered.
    await waitFor(() => expect(mock.messageHandler).not.toBeNull());

    // Simulate message_start — opens an assistant bubble.
    mock.messageHandler!({ data: eventFrame("message_start", { message_id: "msg_1" }) } as MessageEvent);

    await waitFor(() => {
      const turns = getAllByTestId("checklist-chat-turn");
      expect(turns.some((el) => el.dataset.role === "assistant")).toBe(true);
    });

    // Streaming cursor is visible.
    expect(queryByTestId("checklist-chat-cursor")).not.toBeNull();

    // Simulate token delta.
    mock.messageHandler!({
      data: eventFrame("token", { message_id: "msg_1", delta: "Hello" }),
    } as MessageEvent);

    await waitFor(() => {
      const turns = getAllByTestId("checklist-chat-turn");
      expect(turns.some((el) => el.textContent?.includes("Hello"))).toBe(true);
    });

    // Simulate message_complete — cursor disappears and body freezes.
    mock.messageHandler!({
      data: eventFrame("message_complete", {
        message_id: "msg_1",
        content: "Hello, I'm on it.",
        executor_input_tokens: null,
        executor_output_tokens: null,
        advisor_input_tokens: null,
        advisor_output_tokens: null,
        advisor_calls_count: 0,
        cache_read_tokens: null,
        input_tokens: null,
        output_tokens: null,
      }),
    } as MessageEvent);

    await waitFor(() => {
      expect(queryByTestId("checklist-chat-cursor")).toBeNull();
      const turns = getAllByTestId("checklist-chat-turn");
      expect(turns.some((el) => el.textContent?.includes("Hello, I'm on it."))).toBe(true);
    });

    // getByTestId used as coverage guard — panel still present.
    expect(getByTestId("checklist-chat")).toBeInTheDocument();
  });
});

describe("ChecklistChat — send disabled while in flight", () => {
  it("disables the send button while the 202 handshake is pending", async () => {
    let resolvePrompt: (value: unknown) => void = () => {};
    const sendPromptFn = vi
      .fn()
      .mockReturnValue(new Promise((res) => { resolvePrompt = res; }));
    const listMessagesFn = vi.fn().mockResolvedValue(emptyPage());
    const mock = makeMockWs();
    const createWs = vi.fn().mockReturnValue(mock.ws);

    const { getByTestId } = render(ChecklistChat, {
      props: { checklistId: "cl_a", sendPromptFn, listMessagesFn, createWs },
    });

    const input = getByTestId("checklist-chat-input");
    const sendBtn = getByTestId("checklist-chat-send");

    // Type content so the button would normally be enabled.
    await fireEvent.input(input, { target: { value: "test message" } });

    // Button enabled before send.
    await waitFor(() => expect(sendBtn).not.toBeDisabled());

    // Click send — starts the in-flight period.
    await fireEvent.click(sendBtn);

    // Button must be disabled while the promise is unresolved.
    await waitFor(() => expect(sendBtn).toBeDisabled());

    // Resolve the handshake — button re-enables (draft is now empty,
    // but the disabled-for-empty-draft state is correct post-send).
    resolvePrompt({ queued: true, session_id: "cl_a" });
    await waitFor(() => expect(sendPromptFn).toHaveBeenCalledOnce());
  });

  it("hydrates existing messages on mount", async () => {
    const existing: MessageOut[] = [
      fakeMessage({ id: "msg_old", role: "user", content: "Existing message" }),
    ];
    const listMessagesFn = vi
      .fn()
      .mockResolvedValue({ items: existing, has_more: false } satisfies MessagePage);
    const sendPromptFn = vi.fn();
    const mock = makeMockWs();
    const createWs = vi.fn().mockReturnValue(mock.ws);

    const { getAllByTestId } = render(ChecklistChat, {
      props: { checklistId: "cl_a", sendPromptFn, listMessagesFn, createWs },
    });

    await waitFor(() => {
      const turns = getAllByTestId("checklist-chat-turn");
      expect(turns.some((el) => el.textContent?.includes("Existing message"))).toBe(true);
    });
  });
});
