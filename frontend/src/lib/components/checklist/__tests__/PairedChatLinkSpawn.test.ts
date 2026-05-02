/**
 * Component tests for :class:`PairedChatLinkSpawn`.
 *
 * Done-when criteria covered:
 *
 * - Spawn-fresh path calls :func:`spawnPairedChat` with
 *   ``spawned_by="user"``.
 * - Link-existing flow opens the picker, lists the supplied chats,
 *   and calls :func:`linkChat` on confirm.
 * - The component does not render when ``isLeaf`` is false (parent
 *   items have no paired-chat affordance per behavior doc).
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import PairedChatLinkSpawn from "../PairedChatLinkSpawn.svelte";
import type { ChecklistItemOut } from "../../../api/checklists";
import type { SessionOut } from "../../../api/sessions";

function fakeItem(overrides: Partial<ChecklistItemOut> = {}): ChecklistItemOut {
  return {
    id: 1,
    checklist_id: "cl_a",
    parent_item_id: null,
    label: "An item",
    notes: null,
    sort_order: 100,
    checked_at: null,
    chat_session_id: null,
    blocked_at: null,
    blocked_reason_category: null,
    blocked_reason_text: null,
    created_at: "2026-04-29T00:00:00Z",
    updated_at: "2026-04-29T00:00:00Z",
    ...overrides,
  };
}

function fakeChat(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "An open chat",
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
    created_at: "2026-04-29T00:00:00Z",
    updated_at: "2026-04-29T00:00:00Z",
    last_viewed_at: null,
    last_completed_at: null,
    closed_at: null,
    closing_summary: null,
    ...overrides,
  };
}

describe("PairedChatLinkSpawn — gating", () => {
  it("renders nothing when isLeaf is false", () => {
    const { queryByTestId } = render(PairedChatLinkSpawn, {
      props: { item: fakeItem(), isLeaf: false },
    });
    expect(queryByTestId("paired-chat")).toBeNull();
  });
});

describe("PairedChatLinkSpawn — spawn-fresh path", () => {
  it("renders the Work-on-this button when the leaf is unpaired", () => {
    const { getByTestId } = render(PairedChatLinkSpawn, {
      props: { item: fakeItem(), isLeaf: true },
    });
    expect(getByTestId("paired-chat-spawn")).toBeInTheDocument();
  });

  it("calls spawnPairedChat with spawned_by=user on click", async () => {
    const spawnPairedChat = vi.fn().mockResolvedValue({
      chat_session_id: "ses_b",
      item_id: 1,
      title: "An item",
      working_dir: "/wd",
      model: "sonnet",
      created: true,
    });
    const onChange = vi.fn();
    const onSelectChat = vi.fn();
    const { getByTestId } = render(PairedChatLinkSpawn, {
      props: {
        item: fakeItem(),
        isLeaf: true,
        spawnPairedChat,
        onChange,
        onSelectChat,
      },
    });
    await fireEvent.click(getByTestId("paired-chat-spawn"));
    await waitFor(() => expect(spawnPairedChat).toHaveBeenCalledWith(1, { spawned_by: "user" }));
    expect(onChange).toHaveBeenCalled();
    expect(onSelectChat).toHaveBeenCalledWith("ses_b");
  });

  it("renders the Continue / Unlink controls when the leaf is already paired", () => {
    const { getByTestId } = render(PairedChatLinkSpawn, {
      props: { item: fakeItem({ chat_session_id: "ses_existing" }), isLeaf: true },
    });
    expect(getByTestId("paired-chat-continue")).toBeInTheDocument();
    expect(getByTestId("paired-chat-unlink")).toBeInTheDocument();
  });
});

describe("PairedChatLinkSpawn — link-existing path", () => {
  it("opens the picker, lists chats, and calls linkChat on confirm", async () => {
    const linkChat = vi.fn().mockResolvedValue(fakeItem({ chat_session_id: "ses_chosen" }));
    const onChange = vi.fn();
    const { getByTestId } = render(PairedChatLinkSpawn, {
      props: {
        item: fakeItem(),
        isLeaf: true,
        availableChats: [fakeChat({ id: "ses_chosen" })],
        linkChat,
        onChange,
      },
    });
    await fireEvent.click(getByTestId("paired-chat-link"));
    const select = getByTestId("paired-chat-picker-select") as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "ses_chosen" } });
    await fireEvent.click(getByTestId("paired-chat-picker-confirm"));
    await waitFor(() =>
      expect(linkChat).toHaveBeenCalledWith(1, {
        chat_session_id: "ses_chosen",
        spawned_by: "user",
      }),
    );
    expect(onChange).toHaveBeenCalled();
  });

  it("renders the empty-list copy when no chats are available", async () => {
    const { getByTestId } = render(PairedChatLinkSpawn, {
      props: {
        item: fakeItem(),
        isLeaf: true,
        availableChats: [],
      },
    });
    await fireEvent.click(getByTestId("paired-chat-link"));
    expect(getByTestId("paired-chat-picker-empty")).toBeInTheDocument();
  });
});
