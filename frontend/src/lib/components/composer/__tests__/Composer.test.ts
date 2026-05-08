/**
 * Component tests for ``Composer`` — Enter-to-send keybind,
 * Shift+Enter newline, POST against the prompt endpoint, draft clear
 * on success, draft retention on failure, per-session draft
 * persistence, Up/Down history navigation, and attachment chip
 * lifecycle (gap-cycle-03-001).
 *
 * The composer talks to the backend via ``api/prompt.ts`` →
 * ``api/client.ts``'s ``postJson`` wrapper → ``fetch``, and via
 * ``api/uploads.ts`` → ``fetch`` for multipart uploads. We stub
 * ``fetch`` globally and assert on the recorded calls; that catches
 * the real wire shape (URL, body, ack handling) without mocking the
 * internal API surface.
 */
import { createEvent, fireEvent, render, waitFor } from "@testing-library/svelte";
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

// ---------------------------------------------------------------------------
// Attachment chip lifecycle (gap-cycle-03-001)
// ---------------------------------------------------------------------------

/**
 * Build a DragEvent with a real file in ``dataTransfer.files``.
 *
 * jsdom's ``DataTransfer`` does not fully support ``items.add(file)``
 * in all environments, so we build the dataTransfer object manually and
 * attach it via Object.defineProperty.
 */
function makeDropEvent(element: Element, files: File[]): Event {
  const event = createEvent.drop(element);
  Object.defineProperty(event, "dataTransfer", {
    value: {
      files,
      items: files.map((f) => ({ kind: "file", type: f.type })),
      getData: () => "",
    },
  });
  return event;
}

function uploadOkResponse(id: number, filename: string): Response {
  return {
    status: 201,
    statusText: "Created",
    json: async () => ({
      id,
      sha256: "abc",
      filename,
      mime_type: "text/plain",
      size: 4,
      created_at: 1_000_000,
    }),
    text: async () => JSON.stringify({ id }),
  } as unknown as Response;
}

function uploadErrorResponse(status: number, detail: string): Response {
  return {
    status,
    statusText: "Error",
    json: async () => ({ detail }),
    text: async () => JSON.stringify({ detail }),
  } as unknown as Response;
}

describe("Composer — attachment chips (gap-cycle-03-001)", () => {
  it("dropping a single file onto the textarea calls POST /api/uploads and shows a chip", async () => {
    fetchMock.mockResolvedValueOnce(uploadOkResponse(1, "hello.txt"));
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_attach" } });
    const textarea = getByTestId("composer-textarea");

    await fireEvent(
      textarea,
      makeDropEvent(textarea, [new File(["hi"], "hello.txt", { type: "text/plain" })]),
    );

    await waitFor(() => {
      expect(getByTestId("composer-attachment-chips")).toBeInTheDocument();
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/uploads");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("dropping multiple files fires one POST /api/uploads per file", async () => {
    fetchMock
      .mockResolvedValueOnce(uploadOkResponse(1, "a.txt"))
      .mockResolvedValueOnce(uploadOkResponse(2, "b.txt"));
    const { getByTestId, getAllByTestId } = render(Composer, { props: { sessionId: "ses_multi" } });
    const textarea = getByTestId("composer-textarea");

    const files = [
      new File(["a"], "a.txt", { type: "text/plain" }),
      new File(["b"], "b.txt", { type: "text/plain" }),
    ];
    await fireEvent(textarea, makeDropEvent(textarea, files));

    await waitFor(() => {
      expect(getAllByTestId("composer-attachment-chip").length).toBe(2);
    });
    // Both uploads should have been fired.
    const uploadCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/uploads");
    expect(uploadCalls.length).toBe(2);
  });

  it("a failed upload shows an error on the chip but does not remove the chip", async () => {
    fetchMock.mockResolvedValueOnce(uploadErrorResponse(413, "file too large"));
    const { getByTestId } = render(Composer, { props: { sessionId: "ses_err" } });
    const textarea = getByTestId("composer-textarea");

    await fireEvent(textarea, makeDropEvent(textarea, [new File(["x"], "big.bin")]));

    await waitFor(() => {
      const chip = getByTestId("composer-attachment-chip");
      expect(chip.getAttribute("data-chip-status")).toBe("error");
    });
  });

  it("clicking the remove button on an uploading chip removes it immediately", async () => {
    // Never resolve — keeps the upload in-flight.
    fetchMock.mockReturnValueOnce(new Promise(() => undefined));
    const { getByTestId, queryByTestId } = render(Composer, { props: { sessionId: "ses_rm" } });
    const textarea = getByTestId("composer-textarea");

    await fireEvent(textarea, makeDropEvent(textarea, [new File(["x"], "remove.txt")]));

    await waitFor(() => {
      expect(getByTestId("composer-attachment-chip")).toBeInTheDocument();
    });

    const removeBtn = getByTestId("composer-chip-remove");
    await fireEvent.click(removeBtn);

    await waitFor(() => {
      expect(queryByTestId("composer-attachment-chip")).toBeNull();
    });
  });

  it("Send is disabled while a chip is uploading, enabled once all chips are done", async () => {
    // Keep first upload unresolved to observe the blocked state.
    let resolveUpload!: (r: Response) => void;
    const pendingUpload = new Promise<Response>((res) => {
      resolveUpload = res;
    });
    fetchMock.mockReturnValueOnce(pendingUpload);

    const { getByTestId } = render(Composer, { props: { sessionId: "ses_gate" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;
    const sendBtn = getByTestId("composer-send");

    // Type a non-empty draft so content gate is satisfied.
    await fireEvent.input(textarea, { target: { value: "message with file" } });
    // Drop a file — send should be blocked while uploading.
    await fireEvent(textarea, makeDropEvent(textarea, [new File(["x"], "attached.txt")]));

    await waitFor(() => {
      expect(getByTestId("composer-attachment-chip")).toBeInTheDocument();
    });
    expect(sendBtn).toBeDisabled();

    // Resolve the upload — send should become enabled.
    resolveUpload(uploadOkResponse(5, "attached.txt"));
    await waitFor(() => {
      expect(sendBtn).not.toBeDisabled();
    });
  });

  it("submitting includes upload_ids of done chips in the prompt POST body", async () => {
    // Upload resolves first, then prompt ack.
    fetchMock.mockResolvedValueOnce(uploadOkResponse(99, "doc.txt")).mockResolvedValueOnce({
      status: 202,
      statusText: "Accepted",
      json: async () => ({ queued: true, session_id: "ses_ids" }),
      text: async () => JSON.stringify({ queued: true, session_id: "ses_ids" }),
    } as unknown as Response);

    const { getByTestId } = render(Composer, { props: { sessionId: "ses_ids" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;

    await fireEvent(textarea, makeDropEvent(textarea, [new File(["x"], "doc.txt")]));
    // Wait for upload to complete and chip to reach "done" state.
    await waitFor(() => {
      const chip = getByTestId("composer-attachment-chip");
      expect(chip.getAttribute("data-chip-status")).toBe("done");
    });

    await fireEvent.input(textarea, { target: { value: "here is a file" } });
    await fireEvent.click(getByTestId("composer-send"));

    await waitFor(() => expect(textarea.value).toBe(""));

    const allCalls = fetchMock.mock.calls as [string, RequestInit][];
    const promptCalls = allCalls.filter(([url]) => url.includes("/prompt"));
    expect(promptCalls.length).toBe(1);
    const [, init] = promptCalls[0];
    const body = JSON.parse(init.body as string) as { content: string; upload_ids?: number[] };
    expect(body.upload_ids).toEqual([99]);
  });

  it("chips are cleared after a successful send", async () => {
    fetchMock.mockResolvedValueOnce(uploadOkResponse(1, "clear.txt")).mockResolvedValueOnce({
      status: 202,
      statusText: "Accepted",
      json: async () => ({ queued: true, session_id: "ses_clr" }),
      text: async () => JSON.stringify({ queued: true, session_id: "ses_clr" }),
    } as unknown as Response);

    const { getByTestId, queryByTestId } = render(Composer, { props: { sessionId: "ses_clr" } });
    const textarea = getByTestId("composer-textarea") as HTMLTextAreaElement;

    await fireEvent(textarea, makeDropEvent(textarea, [new File(["x"], "clear.txt")]));
    await waitFor(() => {
      expect(getByTestId("composer-attachment-chip").getAttribute("data-chip-status")).toBe("done");
    });

    await fireEvent.input(textarea, { target: { value: "done" } });
    await fireEvent.click(getByTestId("composer-send"));

    await waitFor(() => {
      expect(queryByTestId("composer-attachment-chips")).toBeNull();
    });
  });
});
