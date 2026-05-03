/**
 * Component tests for ``Composer`` — Enter-to-send keybind,
 * Shift+Enter newline, POST against the prompt endpoint, draft clear
 * on success, draft retention on failure, per-session draft
 * persistence, and Up/Down history navigation.
 *
 * The composer talks to the backend via ``api/prompt.ts`` →
 * ``api/client.ts``'s ``postJson`` wrapper → ``fetch``. We stub
 * ``fetch`` globally and assert on the recorded calls; that catches
 * the real wire shape (URL, body, ack handling) without mocking the
 * internal API surface.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COMPOSER_DRAFT_KEY_PREFIX } from "../../../config";
import Composer from "../Composer.svelte";

const fetchMock = vi.fn();

function ackResponse(sessionId: string): Response {
  return {
    status: 202,
    statusText: "Accepted",
    json: async () => ({ queued: true, session_id: sessionId }),
    text: async () => JSON.stringify({ queued: true, session_id: sessionId }),
  } as unknown as Response;
}

function errorResponse(status: number, detail: string): Response {
  return {
    status,
    statusText: "Error",
    json: async () => ({ detail }),
    text: async () => JSON.stringify({ detail }),
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Composer — submit flow", () => {
  it("renders a textarea + a Send button", () => {
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    expect(getByTestId("composer-textarea")).toBeInTheDocument();
    expect(getByTestId("composer-send")).toBeInTheDocument();
  });

  it("Send button is disabled when the draft is empty", () => {
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    expect(getByTestId("composer-send")).toBeDisabled();
  });

  it("typing into the textarea enables Send", async () => {
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "hi" } });
    expect(getByTestId("composer-send")).not.toBeDisabled();
  });

  it("clicking Send POSTs to /api/sessions/<id>/prompt with the draft", async () => {
    fetchMock.mockResolvedValueOnce(ackResponse("ses_a"));
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "hello world" } });
    await fireEvent.click(getByTestId("composer-send"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/sessions/ses_a/prompt");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ content: "hello world" });
  });

  it("Enter (without modifiers) submits", async () => {
    fetchMock.mockResolvedValueOnce(ackResponse("ses_a"));
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "x" } });
    await fireEvent.keyDown(textarea, { key: "Enter" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it("Shift+Enter does NOT submit (newline insertion is the browser default)", async () => {
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "x" } });
    await fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("Ctrl+Enter falls through to the OS keymap (no submit, no newline)", async () => {
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "x" } });
    await fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("clears the draft on a successful 202 ack", async () => {
    fetchMock.mockResolvedValueOnce(ackResponse("ses_a"));
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "ping" } });
    await fireEvent.click(getByTestId("composer-send"));
    await waitFor(() => expect(textarea.value).toBe(""));
  });

  it("retains the draft and surfaces the error on a 409 closed-session response", async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(409, "session is closed"));
    const { getByTestId, findByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "still here" } });
    await fireEvent.click(getByTestId("composer-send"));
    expect(await findByTestId("composer-error")).toHaveTextContent("session is closed");
    expect(textarea.value).toBe("still here");
  });

  it("renders the closed-session hint when ``disabled`` is true", () => {
    const { getByTestId, queryByTestId } = render(Composer, {
      props: { sessionId: "ses_a", disabled: true },
    });
    expect(getByTestId("composer-disabled-hint")).toBeInTheDocument();
    expect(queryByTestId("composer-textarea")).toBeNull();
    expect(queryByTestId("composer-send")).toBeNull();
  });

  it("whitespace-only drafts do not enable Send", async () => {
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_a" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "   \n  " } });
    expect(getByTestId("composer-send")).toBeDisabled();
  });
});

describe("Composer — draft persistence (item 2.5)", () => {
  it("persists draft to localStorage on input", async () => {
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_persist" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "unsent work" } });
    expect(window.localStorage.getItem(`${COMPOSER_DRAFT_KEY_PREFIX}ses_persist`)).toBe(
      "unsent work",
    );
  });

  it("clears localStorage draft after a successful send", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 202,
      statusText: "Accepted",
      json: async () => ({ queued: true, session_id: "ses_persist" }),
      text: async () => JSON.stringify({ queued: true, session_id: "ses_persist" }),
    } as unknown as Response);
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_persist" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    await fireEvent.input(textarea, { target: { value: "send me" } });
    await fireEvent.click(getByTestId("composer-send"));
    await waitFor(() => expect(textarea.value).toBe(""));
    expect(window.localStorage.getItem(`${COMPOSER_DRAFT_KEY_PREFIX}ses_persist`)).toBeNull();
  });

  it("loads a pre-existing draft from localStorage on mount", async () => {
    window.localStorage.setItem(`${COMPOSER_DRAFT_KEY_PREFIX}ses_preload`, "pre-loaded draft");
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_preload" } });
    await waitFor(() => {
      const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
      expect(textarea.value).toBe("pre-loaded draft");
    });
  });
});

describe("Composer — history navigation (item 2.5)", () => {
  it("ArrowUp with cursor at position 0 recalls the last sent message", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 202,
      statusText: "Accepted",
      json: async () => ({ queued: true, session_id: "ses_hist" }),
      text: async () => JSON.stringify({ queued: true, session_id: "ses_hist" }),
    } as unknown as Response);

    const { getByTestId } = render(Composer, { props: { sessionId: "ses_hist" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;

    // Send a message to populate history.
    await fireEvent.input(textarea, { target: { value: "sent message" } });
    await fireEvent.click(getByTestId("composer-send"));
    await waitFor(() => expect(textarea.value).toBe(""));

    // Simulate ArrowUp with cursor at start.
    Object.defineProperty(textarea, "selectionStart", { value: 0, configurable: true });
    Object.defineProperty(textarea, "selectionEnd", { value: 0, configurable: true });
    await fireEvent.keyDown(textarea, { key: "ArrowUp" });

    await waitFor(() => {
      expect(textarea.value).toBe("sent message");
    });
  });

  it("modified ArrowUp (Shift/Ctrl) does NOT trigger history walk", async () => {
    fetchMock.mockResolvedValueOnce({
      status: 202,
      statusText: "Accepted",
      json: async () => ({ queued: true, session_id: "ses_hist2" }),
      text: async () => JSON.stringify({ queued: true, session_id: "ses_hist2" }),
    } as unknown as Response);

    const { getByTestId } = render(Composer, { props: { sessionId: "ses_hist2" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;

    await fireEvent.input(textarea, { target: { value: "sent" } });
    await fireEvent.click(getByTestId("composer-send"));
    await waitFor(() => expect(textarea.value).toBe(""));

    Object.defineProperty(textarea, "selectionStart", { value: 0, configurable: true });
    Object.defineProperty(textarea, "selectionEnd", { value: 0, configurable: true });
    // Shift+ArrowUp should NOT recall history.
    await fireEvent.keyDown(textarea, { key: "ArrowUp", shiftKey: true });

    expect(textarea.value).toBe("");
  });
});
