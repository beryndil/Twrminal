/**
 * Component tests for ``SentAttachmentChips`` — gap-cycle-01-015.
 *
 * Covers all four vitest acceptance criteria:
 *  1. Chips render when ``message.attachments.length > 0``.
 *  2. No chips when array is empty.
 *  3. Right-click surfaces the attachment context menu.
 *  4. Multiple chips render for multiple attachments.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { flushSync } from "svelte";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  MENU_ACTION_ATTACHMENT_COPY_FILENAME,
  MENU_ACTION_ATTACHMENT_COPY_PATH,
  MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR,
  MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER,
  MENU_ACTION_ATTACHMENT_REMOVE,
  MENU_TARGET_ATTACHMENT,
} from "../../../config";
import {
  _resetForTests as resetContextMenu,
  contextMenuStore,
} from "../../../context-menu/store.svelte";
import type { SentAttachment } from "../../../stores/conversation.svelte";
import SentAttachmentChips from "../SentAttachmentChips.svelte";

function attachment(overrides: Partial<SentAttachment> = {}): SentAttachment {
  return {
    id: "att-1",
    label: "[File 1] foo.log",
    path: "/home/beryndil/foo.log",
    ...overrides,
  };
}

beforeEach(() => {
  resetContextMenu();
});

afterEach(() => {
  resetContextMenu();
});

describe("SentAttachmentChips — empty attachments", () => {
  it("renders nothing when attachments array is empty", () => {
    const { queryByTestId } = render(SentAttachmentChips, {
      props: { attachments: [] },
    });
    expect(queryByTestId("sent-attachment-chips")).toBeNull();
    expect(queryByTestId("sent-attachment-chip")).toBeNull();
  });
});

describe("SentAttachmentChips — with attachments", () => {
  it("renders the chips wrapper when attachments are present", () => {
    const { getByTestId } = render(SentAttachmentChips, {
      props: { attachments: [attachment()] },
    });
    expect(getByTestId("sent-attachment-chips")).toBeTruthy();
  });

  it("renders one chip per attachment with the correct label", () => {
    const { getAllByTestId } = render(SentAttachmentChips, {
      props: {
        attachments: [
          attachment({ id: "a1", label: "[File 1] foo.log" }),
          attachment({ id: "a2", label: "[File 2] bar.txt" }),
          attachment({ id: "a3", label: "[File 3] baz.py" }),
        ],
      },
    });
    const chips = getAllByTestId("sent-attachment-chip");
    expect(chips).toHaveLength(3);
    expect(chips[0]).toHaveTextContent("[File 1] foo.log");
    expect(chips[1]).toHaveTextContent("[File 2] bar.txt");
    expect(chips[2]).toHaveTextContent("[File 3] baz.py");
  });

  it("attaches the attachment id as a data attribute on each chip", () => {
    const { getByTestId } = render(SentAttachmentChips, {
      props: { attachments: [attachment({ id: "att-42" })] },
    });
    expect(getByTestId("sent-attachment-chip")).toHaveAttribute(
      "data-attachment-id",
      "att-42",
    );
  });
});

describe("SentAttachmentChips — context menu (right-click)", () => {
  it("right-clicking a chip opens the attachment context menu", () => {
    const { getByTestId } = render(SentAttachmentChips, {
      props: { attachments: [attachment()] },
    });
    flushSync(() => {
      fireEvent.contextMenu(getByTestId("sent-attachment-chip"));
    });
    expect(contextMenuStore.open).not.toBeNull();
    expect(contextMenuStore.open?.target).toBe(MENU_TARGET_ATTACHMENT);
  });

  it("provides handlers for copy-path, copy-filename, open-in-editor, open-in-file-explorer", () => {
    const { getByTestId } = render(SentAttachmentChips, {
      props: { attachments: [attachment()] },
    });
    flushSync(() => {
      fireEvent.contextMenu(getByTestId("sent-attachment-chip"));
    });
    const { handlers } = contextMenuStore.open!;
    expect(typeof handlers[MENU_ACTION_ATTACHMENT_COPY_PATH]).toBe("function");
    expect(typeof handlers[MENU_ACTION_ATTACHMENT_COPY_FILENAME]).toBe("function");
    expect(typeof handlers[MENU_ACTION_ATTACHMENT_OPEN_IN_EDITOR]).toBe("function");
    expect(typeof handlers[MENU_ACTION_ATTACHMENT_OPEN_IN_FILE_EXPLORER]).toBe("function");
  });

  it("does NOT provide a handler for attachment.remove (message already sent)", () => {
    const { getByTestId } = render(SentAttachmentChips, {
      props: { attachments: [attachment()] },
    });
    flushSync(() => {
      fireEvent.contextMenu(getByTestId("sent-attachment-chip"));
    });
    const { handlers } = contextMenuStore.open!;
    expect(handlers[MENU_ACTION_ATTACHMENT_REMOVE]).toBeUndefined();
  });

  it("carries the path and attachment id in the menu data payload", () => {
    const att = attachment({ id: "x99", path: "/tmp/report.pdf" });
    const { getByTestId } = render(SentAttachmentChips, {
      props: { attachments: [att] },
    });
    flushSync(() => {
      fireEvent.contextMenu(getByTestId("sent-attachment-chip"));
    });
    const data = contextMenuStore.open?.data as { attachmentId: string; path: string };
    expect(data.attachmentId).toBe("x99");
    expect(data.path).toBe("/tmp/report.pdf");
  });
});
