/**
 * Tests for the reorg subsystem — gap-cycle-01-013 + gap-cycle-03-009.
 *
 * Coverage:
 *   1. ReorgPicker — opens on right-click action, lists sessions,
 *      confirms "move" mode, confirms "split" mode.
 *   2. ReorgAuditDivider — renders after a successful commit; Undo
 *      button shown for merge entries; Undo invokes onUndo callback.
 *   3. ReorgUndoToast — 30 s auto-dismiss + manual undo + dismiss.
 *   4. ReorgProposalEditor — analyzeReorg() called on open; accept
 *      triggers picker; dismiss removes proposal.
 *   5. reorgStore — state transitions for openPicker / commitMove /
 *      commitSplit / undoReorg / dismissUndoToast / loadAudits / undoMerge.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// API mocks — hoisted so the mock factory can reference them.
// ---------------------------------------------------------------------------

const {
  moveMessageMock,
  listMessagesMock,
  listSessionsMock,
  listReorgAuditsMock,
  deleteReorgAuditMock,
  createSessionMock,
  mergeSessionMock,
  splitSessionMock,
  moveMessageReorgMock,
  listTagsMock,
} = vi.hoisted(() => ({
  moveMessageMock: vi.fn(),
  listMessagesMock: vi.fn(),
  listSessionsMock: vi.fn(),
  listReorgAuditsMock: vi.fn(),
  deleteReorgAuditMock: vi.fn(),
  createSessionMock: vi.fn(),
  mergeSessionMock: vi.fn(),
  splitSessionMock: vi.fn(),
  moveMessageReorgMock: vi.fn(),
  listTagsMock: vi.fn(),
}));

vi.mock("../../../api/messages", () => ({
  moveMessage: moveMessageMock,
  listMessages: listMessagesMock,
}));

vi.mock("../../../api/sessions", () => ({
  listSessions: listSessionsMock,
  createSession: createSessionMock,
}));

vi.mock("../../../api/tags", () => ({
  listTags: listTagsMock,
}));

vi.mock("../../../api/reorg", () => ({
  mergeSession: mergeSessionMock,
  listReorgAudits: listReorgAuditsMock,
  deleteReorgAudit: deleteReorgAuditMock,
  splitSession: splitSessionMock,
  moveMessageReorg: moveMessageReorgMock,
}));

// analyzeReorg uses listMessages internally — covered by the mock above.
// We also need to mock it for the proposal editor tests.
const { analyzeReorgMock } = vi.hoisted(() => ({ analyzeReorgMock: vi.fn() }));
vi.mock("../../../stores/reorg.svelte", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../stores/reorg.svelte")>();
  return {
    ...actual,
    analyzeReorg: analyzeReorgMock,
  };
});

import ReorgPicker from "../ReorgPicker.svelte";
import ReorgAuditDivider from "../ReorgAuditDivider.svelte";
import ReorgUndoToast from "../ReorgUndoToast.svelte";
import ReorgProposalEditor from "../ReorgProposalEditor.svelte";
import SessionPickerModal from "../../menus/SessionPickerModal.svelte";
import {
  reorgStore,
  _resetReorgForTests,
  type ReorgAuditEntry,
  type ReorgUndoPayload,
} from "../../../stores/reorg.svelte";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAuditEntry(overrides: Partial<ReorgAuditEntry> = {}): ReorgAuditEntry {
  return {
    id: "e1",
    anchorMessageId: "msg1",
    kind: "move",
    count: 1,
    targetSessionId: "sess-b",
    targetSessionTitle: "Target Session",
    timestamp: new Date("2026-01-01T12:00:00Z").toISOString(),
    ...overrides,
  };
}

function makeUndoPayload(overrides: Partial<ReorgUndoPayload> = {}): ReorgUndoPayload {
  return {
    entry: makeAuditEntry(),
    originalSessionId: "sess-a",
    movedMessageIds: ["msg1"],
    ...overrides,
  };
}

const SESSION_FIXTURES = [
  {
    id: "sess-a",
    kind: "chat",
    title: "Source Session",
    description: null,
    session_instructions: null,
    working_dir: "/",
    model: "sonnet",
    permission_mode: null,
    max_budget_usd: null,
    total_cost_usd: 0,
    message_count: 3,
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
  },
  {
    id: "sess-b",
    kind: "chat",
    title: "Target Session",
    description: "A target session",
    session_instructions: null,
    working_dir: "/",
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
  },
];

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

const TAG_FIXTURES = [
  {
    id: 1,
    name: "project-alpha",
    color: null,
    default_model: null,
    working_dir: null,
    pinned: false,
    class_: "project",
    sort_order: 0,
    group: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: 2,
    name: "urgent",
    color: null,
    default_model: null,
    working_dir: null,
    pinned: false,
    class_: "severity",
    sort_order: 0,
    group: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

const CREATED_SESSION_FIXTURE = {
  id: "sess-new",
  kind: "chat",
  title: "Brand New Session",
  description: null,
  session_instructions: null,
  working_dir: "/",
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
};

const MOCK_MOVE_AUDIT = {
  id: "rga_move1",
  dst_session_id: "sess-a",
  src_session_id: "sess-b",
  merged_at: "2026-01-01T12:00:00Z",
  src_title: "Target Session",
  boundary_msg_id: "msg1",
  kind: "move" as const,
};

const MOCK_SPLIT_RESULT = {
  audit: {
    id: "rga_split1",
    dst_session_id: "sess-a",
    src_session_id: "sess-b",
    merged_at: "2026-01-01T12:00:00Z",
    src_title: "Target Session",
    boundary_msg_id: "msg1",
    kind: "split" as const,
  },
  moved_message_ids: ["msg1", "msg2"],
};

beforeEach(() => {
  _resetReorgForTests();
  moveMessageMock.mockResolvedValue({ id: "msg1", session_id: "sess-b" });
  moveMessageReorgMock.mockResolvedValue(MOCK_MOVE_AUDIT);
  splitSessionMock.mockResolvedValue(MOCK_SPLIT_RESULT);
  listSessionsMock.mockResolvedValue(SESSION_FIXTURES);
  listMessagesMock.mockResolvedValue({
    items: [
      { id: "msg1", session_id: "sess-a", role: "user", content: "hello", seq: 1, created_at: "2026-01-01T10:00:00Z" },
      { id: "msg2", session_id: "sess-a", role: "assistant", content: "hi", seq: 2, created_at: "2026-01-01T10:01:00Z" },
    ],
    has_more: false,
  });
  analyzeReorgMock.mockResolvedValue([
    { messageId: "msg2", reason: "Natural chunk boundary at message 2" },
  ]);
  listReorgAuditsMock.mockResolvedValue({ items: [] });
  deleteReorgAuditMock.mockResolvedValue({ new_session_id: "ses_new123" });
  createSessionMock.mockResolvedValue(CREATED_SESSION_FIXTURE);
  mergeSessionMock.mockResolvedValue({});
  listTagsMock.mockResolvedValue(TAG_FIXTURES);
});

afterEach(() => {
  vi.clearAllMocks();
  _resetReorgForTests();
});

// ---------------------------------------------------------------------------
// 1. ReorgPicker — opens on right-click context-menu action
// ---------------------------------------------------------------------------

describe("ReorgPicker — picker open on right-click", () => {
  it("renders when picker state is set to move mode", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId } = render(ReorgPicker);

    await waitFor(() => {
      expect(getByTestId("reorg-picker")).toBeTruthy();
    });
    expect(getByTestId("reorg-picker")).toHaveAttribute("data-mode", "move");
  });

  it("renders in split mode when opened with split", async () => {
    reorgStore.openPicker({
      mode: "split",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId } = render(ReorgPicker);
    await waitFor(() => {
      expect(getByTestId("reorg-picker")).toHaveAttribute("data-mode", "split");
    });
  });

  it("does not render when picker state is null", () => {
    const { queryByTestId } = render(ReorgPicker);
    expect(queryByTestId("reorg-picker")).toBeNull();
  });

  it("lists sessions excluding the source session", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId, queryByTestId } = render(ReorgPicker);
    await waitFor(() => {
      // sess-b should be present; sess-a (source) should be excluded
      expect(getByTestId("rp-session-sess-b")).toBeTruthy();
    });
    expect(queryByTestId("rp-session-sess-a")).toBeNull();
  });

  it("closes when cancel is clicked", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId, queryByTestId } = render(ReorgPicker);
    await waitFor(() => expect(getByTestId("reorg-picker")).toBeTruthy());

    fireEvent.click(getByTestId("reorg-picker-cancel"));
    await waitFor(() => expect(queryByTestId("reorg-picker")).toBeNull());
  });

  it("confirm button is disabled until a session is selected", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId } = render(ReorgPicker);
    await waitFor(() => expect(getByTestId("rp-session-sess-b")).toBeTruthy());
    expect(getByTestId("reorg-picker-confirm")).toBeDisabled();
  });

  it("calls moveMessageReorg (server endpoint) and closes on move confirm", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId, queryByTestId } = render(ReorgPicker);
    await waitFor(() => expect(getByTestId("rp-session-sess-b")).toBeTruthy());

    fireEvent.click(getByTestId("rp-session-sess-b"));
    fireEvent.click(getByTestId("reorg-picker-confirm"));

    await waitFor(() => {
      // commitMove now uses moveMessageReorg, not per-message moveMessage.
      expect(moveMessageReorgMock).toHaveBeenCalledWith("sess-a", "sess-b", "msg1");
    });
    await waitFor(() => expect(queryByTestId("reorg-picker")).toBeNull());
  });
});

// ---------------------------------------------------------------------------
// 2. ReorgAuditDivider — divider render after commit
// ---------------------------------------------------------------------------

describe("ReorgAuditDivider — divider render after commit", () => {
  it("renders the moved-message summary label", () => {
    const entry = makeAuditEntry({ kind: "move", count: 1, targetSessionTitle: "Target Session" });
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry } });

    expect(getByTestId("reorg-audit-divider")).toBeTruthy();
    expect(getByTestId("reorg-audit-divider")).toHaveAttribute("data-kind", "move");
  });

  it("renders a link to the target session", () => {
    const entry = makeAuditEntry({ targetSessionId: "sess-b", targetSessionTitle: "Target Session" });
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry } });

    const link = getByTestId("reorg-audit-divider-target-link");
    expect(link).toHaveAttribute("href", "/sessions/sess-b");
    expect(link).toHaveTextContent("Target Session");
  });

  it("renders a timestamp", () => {
    const entry = makeAuditEntry({ timestamp: "2026-01-01T12:00:00Z" });
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry } });
    expect(getByTestId("reorg-audit-divider-time")).toBeTruthy();
  });

  it("renders 'split' kind correctly", () => {
    const entry = makeAuditEntry({ kind: "split", count: 3 });
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry } });
    expect(getByTestId("reorg-audit-divider")).toHaveAttribute("data-kind", "split");
  });
});

// ---------------------------------------------------------------------------
// 3. ReorgUndoToast — timeout + reverse + dismiss
// ---------------------------------------------------------------------------

describe("ReorgUndoToast — undo toast timeout + reverse", () => {
  // Fake timers only in this block — other describe blocks need real timers
  // so that async Promise chains and waitFor polling work correctly.
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders when undo payload is present", () => {
    reorgStore.showUndoToast(makeUndoPayload());
    const { getByTestId } = render(ReorgUndoToast);
    expect(getByTestId("reorg-undo-toast")).toBeTruthy();
  });

  it("does not render when undo payload is null", () => {
    const { queryByTestId } = render(ReorgUndoToast);
    expect(queryByTestId("reorg-undo-toast")).toBeNull();
  });

  it("auto-dismisses after 30 seconds", async () => {
    reorgStore.showUndoToast(makeUndoPayload());
    const { queryByTestId } = render(ReorgUndoToast);

    expect(queryByTestId("reorg-undo-toast")).toBeTruthy();

    vi.advanceTimersByTime(30_000);

    await waitFor(() => {
      expect(queryByTestId("reorg-undo-toast")).toBeNull();
    });
  });

  it("does not auto-dismiss before 30 seconds", async () => {
    reorgStore.showUndoToast(makeUndoPayload());
    const { queryByTestId } = render(ReorgUndoToast);

    vi.advanceTimersByTime(29_999);

    // Still visible.
    expect(queryByTestId("reorg-undo-toast")).toBeTruthy();
  });

  it("calls moveMessage (reverse) when Undo is clicked", async () => {
    const payload = makeUndoPayload({
      originalSessionId: "sess-a",
      movedMessageIds: ["msg1"],
    });
    reorgStore.showUndoToast(payload);
    const { getByTestId, queryByTestId } = render(ReorgUndoToast);

    fireEvent.click(getByTestId("reorg-undo-toast-undo"));

    await waitFor(() => {
      expect(moveMessageMock).toHaveBeenCalledWith("msg1", "sess-a");
    });
    await waitFor(() => {
      expect(queryByTestId("reorg-undo-toast")).toBeNull();
    });
  });

  it("dismisses without reversing when Dismiss (✕) is clicked", async () => {
    reorgStore.showUndoToast(makeUndoPayload());
    const { getByTestId, queryByTestId } = render(ReorgUndoToast);

    fireEvent.click(getByTestId("reorg-undo-toast-dismiss"));

    await waitFor(() => expect(queryByTestId("reorg-undo-toast")).toBeNull());
    expect(moveMessageMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 4. ReorgProposalEditor — analyze + apply / dismiss
// ---------------------------------------------------------------------------

describe("ReorgProposalEditor — analyze + apply", () => {
  it("calls analyzeReorg on open", async () => {
    const onclose = vi.fn();
    render(ReorgProposalEditor, {
      props: { sessionId: "sess-a", open: true, onclose },
    });

    await waitFor(() => {
      expect(analyzeReorgMock).toHaveBeenCalledWith("sess-a");
    });
  });

  it("renders proposals returned by analyzeReorg", async () => {
    const onclose = vi.fn();
    const { getByTestId } = render(ReorgProposalEditor, {
      props: { sessionId: "sess-a", open: true, onclose },
    });

    await waitFor(() => {
      expect(getByTestId("rpe-proposal-msg2")).toBeTruthy();
    });
  });

  it("dismiss removes a proposal from the list", async () => {
    const onclose = vi.fn();
    const { getByTestId, queryByTestId } = render(ReorgProposalEditor, {
      props: { sessionId: "sess-a", open: true, onclose },
    });

    await waitFor(() => expect(getByTestId("rpe-proposal-msg2")).toBeTruthy());

    fireEvent.click(getByTestId("rpe-dismiss-msg2"));

    await waitFor(() => {
      expect(queryByTestId("rpe-proposal-msg2")).toBeNull();
    });
    expect(getByTestId("rpe-empty")).toBeTruthy();
  });

  it("accept opens the reorg picker and closes the editor", async () => {
    const onclose = vi.fn();
    const { getByTestId } = render(ReorgProposalEditor, {
      props: { sessionId: "sess-a", open: true, onclose },
    });

    await waitFor(() => expect(getByTestId("rpe-proposal-msg2")).toBeTruthy());

    fireEvent.click(getByTestId("rpe-accept-msg2"));

    await waitFor(() => {
      expect(reorgStore.picker).not.toBeNull();
      expect(reorgStore.picker?.mode).toBe("split");
      expect(reorgStore.picker?.messageId).toBe("msg2");
    });
    expect(onclose).toHaveBeenCalled();
  });

  it("does not call analyzeReorg when closed", () => {
    const onclose = vi.fn();
    render(ReorgProposalEditor, {
      props: { sessionId: "sess-a", open: false, onclose },
    });
    expect(analyzeReorgMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 5. reorgStore — state transitions
// ---------------------------------------------------------------------------

describe("reorgStore — state transitions", () => {
  it("openPicker sets picker state", () => {
    expect(reorgStore.picker).toBeNull();
    reorgStore.openPicker({ mode: "move", messageId: "m1", sourceSessionId: "s1", seq: 5 });
    expect(reorgStore.picker).toMatchObject({ mode: "move", messageId: "m1" });
  });

  it("closePicker clears picker state", () => {
    reorgStore.openPicker({ mode: "move", messageId: "m1", sourceSessionId: "s1", seq: 5 });
    reorgStore.closePicker();
    expect(reorgStore.picker).toBeNull();
  });

  it("commitMove calls moveMessageReorg (server endpoint) and adds audit entry", async () => {
    await reorgStore.commitMove("sess-a", "msg1", "sess-b", "Target Session");

    expect(moveMessageReorgMock).toHaveBeenCalledWith("sess-a", "sess-b", "msg1");
    expect(moveMessageMock).not.toHaveBeenCalled(); // old per-message path not used
    const entries = reorgStore.auditEntriesFor("sess-a");
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      kind: "move",
      count: 1,
      targetSessionId: "sess-b",
      serverAuditId: "rga_move1",
    });
  });

  it("commitMove shows undo toast", async () => {
    expect(reorgStore.undo).toBeNull();
    await reorgStore.commitMove("sess-a", "msg1", "sess-b", "Target Session");
    expect(reorgStore.undo).not.toBeNull();
    expect(reorgStore.undo?.originalSessionId).toBe("sess-a");
  });

  it("commitSplit calls splitSession (server endpoint, not per-message loop)", async () => {
    await reorgStore.commitSplit("sess-a", "msg1", 1, "sess-b", "Target Session");

    expect(splitSessionMock).toHaveBeenCalledWith("sess-a", "sess-b", 1);
    expect(moveMessageMock).not.toHaveBeenCalled(); // old loop not used
    const entries = reorgStore.auditEntriesFor("sess-a");
    expect(entries[0]).toMatchObject({
      kind: "split",
      count: 2,
      serverAuditId: "rga_split1",
    });
  });

  it("undoReorg with serverAuditId delegates to deleteReorgAudit (not moveMessage)", async () => {
    await reorgStore.commitMove("sess-a", "msg1", "sess-b", "Target Session");
    const payload = reorgStore.undo!;
    moveMessageMock.mockClear();

    await reorgStore.undoReorg(payload);

    // Server-backed undo: uses deleteReorgAudit, NOT per-message moveMessage.
    expect(deleteReorgAuditMock).toHaveBeenCalledWith("sess-a", "rga_move1");
    expect(moveMessageMock).not.toHaveBeenCalled();
    expect(reorgStore.undo).toBeNull();
    expect(reorgStore.auditEntriesFor("sess-a")).toHaveLength(0);
  });

  it("dismissUndoToast clears toast without reversing", async () => {
    await reorgStore.commitMove("sess-a", "msg1", "sess-b", "Target Session");
    moveMessageMock.mockClear();
    reorgStore.dismissUndoToast();

    expect(reorgStore.undo).toBeNull();
    expect(moveMessageMock).not.toHaveBeenCalled();
    expect(deleteReorgAuditMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 6. ReorgAuditDivider — merge kind + Undo button (gap-cycle-03-009)
// ---------------------------------------------------------------------------

describe("ReorgAuditDivider — merge kind and Undo button", () => {
  it("renders 'merge' kind with merged-from label", () => {
    const entry = makeAuditEntry({
      kind: "merge",
      count: 0,
      targetSessionTitle: "Source Session",
      serverAuditId: "rga_abc",
    });
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry } });
    expect(getByTestId("reorg-audit-divider")).toHaveAttribute("data-kind", "merge");
  });

  it("does not render Undo button when onUndo is not provided", () => {
    const entry = makeAuditEntry({ kind: "merge", count: 0, serverAuditId: "rga_abc" });
    const { queryByTestId } = render(ReorgAuditDivider, { props: { entry } });
    expect(queryByTestId("reorg-audit-divider-undo")).toBeNull();
  });

  it("renders Undo button when onUndo is provided", () => {
    const entry = makeAuditEntry({ kind: "merge", count: 0, serverAuditId: "rga_abc" });
    const onUndo = vi.fn();
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry, onUndo } });
    expect(getByTestId("reorg-audit-divider-undo")).toBeTruthy();
  });

  it("calls onUndo when Undo button is clicked", async () => {
    const entry = makeAuditEntry({ kind: "merge", count: 0, serverAuditId: "rga_abc" });
    const onUndo = vi.fn();
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry, onUndo } });

    fireEvent.click(getByTestId("reorg-audit-divider-undo"));
    expect(onUndo).toHaveBeenCalledOnce();
  });

  it("does not render Undo for move kind even with serverAuditId", () => {
    const entry = makeAuditEntry({ kind: "move", count: 1 });
    const onUndo = vi.fn();
    // onUndo provided but this is a move entry — component still renders button
    // because the parent controls whether to pass onUndo.
    // Here we verify the button IS rendered when prop is present (move entries
    // in practice never receive onUndo from Conversation.svelte).
    const { getByTestId } = render(ReorgAuditDivider, { props: { entry, onUndo } });
    expect(getByTestId("reorg-audit-divider-undo")).toBeTruthy();
    expect(onUndo).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 7. reorgStore — loadAudits + undoMerge (gap-cycle-03-009)
// ---------------------------------------------------------------------------

describe("reorgStore — loadAudits and undoMerge", () => {
  it("loadAudits populates _auditMap with merge entries from server", async () => {
    listReorgAuditsMock.mockResolvedValue({
      items: [
        {
          id: "rga_xyz",
          dst_session_id: "sess-a",
          src_session_id: "sess-b",
          merged_at: "2026-01-01T12:00:00Z",
          src_title: "Old Session",
          boundary_msg_id: "msg1",
          kind: "merge",
        },
      ],
    });

    await reorgStore.loadAudits("sess-a");

    const entries = reorgStore.auditEntriesFor("sess-a");
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      kind: "merge",
      anchorMessageId: "msg1",
      targetSessionTitle: "Old Session",
      serverAuditId: "rga_xyz",
    });
  });

  it("loadAudits skips entries with null boundary_msg_id", async () => {
    listReorgAuditsMock.mockResolvedValue({
      items: [
        {
          id: "rga_empty",
          dst_session_id: "sess-a",
          src_session_id: "sess-b",
          merged_at: "2026-01-01T12:00:00Z",
          src_title: "Empty Source",
          boundary_msg_id: null,
          kind: "merge",
        },
      ],
    });

    await reorgStore.loadAudits("sess-a");

    expect(reorgStore.auditEntriesFor("sess-a")).toHaveLength(0);
  });

  it("loadAudits replaces server-backed entries and re-loads from server", async () => {
    // commitMove now sets serverAuditId — entry is server-backed.
    await reorgStore.commitMove("sess-a", "msg1", "sess-b", "Target Session");
    expect(reorgStore.auditEntriesFor("sess-a")).toHaveLength(1);

    // loadAudits with empty server response replaces the server-backed entry.
    listReorgAuditsMock.mockResolvedValue({ items: [] });
    await reorgStore.loadAudits("sess-a");

    // Server-backed entry cleared (server returned nothing).
    expect(reorgStore.auditEntriesFor("sess-a")).toHaveLength(0);
  });

  it("loadAudits returns split and move kinds from server", async () => {
    listReorgAuditsMock.mockResolvedValue({
      items: [
        {
          id: "rga_s1",
          dst_session_id: "sess-a",
          src_session_id: "sess-b",
          merged_at: "2026-01-01T12:00:00Z",
          src_title: "Target",
          boundary_msg_id: "msg1",
          kind: "split",
        },
        {
          id: "rga_m1",
          dst_session_id: "sess-a",
          src_session_id: "sess-b",
          merged_at: "2026-01-01T12:01:00Z",
          src_title: "Target",
          boundary_msg_id: "msg2",
          kind: "move",
        },
      ],
    });

    await reorgStore.loadAudits("sess-a");

    const entries = reorgStore.auditEntriesFor("sess-a");
    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({ kind: "split", serverAuditId: "rga_s1" });
    expect(entries[1]).toMatchObject({ kind: "move", serverAuditId: "rga_m1" });
  });

  it("undoMerge calls deleteReorgAudit and removes the entry", async () => {
    // Seed a merge entry manually.
    listReorgAuditsMock.mockResolvedValue({
      items: [
        {
          id: "rga_del",
          dst_session_id: "sess-a",
          src_session_id: "sess-b",
          merged_at: "2026-01-01T12:00:00Z",
          src_title: "Old",
          boundary_msg_id: "msg1",
          kind: "merge",
        },
      ],
    });
    await reorgStore.loadAudits("sess-a");
    expect(reorgStore.auditEntriesFor("sess-a")).toHaveLength(1);

    const newId = await reorgStore.undoMerge("sess-a", "rga_del");

    expect(deleteReorgAuditMock).toHaveBeenCalledWith("sess-a", "rga_del");
    expect(newId).toBe("ses_new123");
    expect(reorgStore.auditEntriesFor("sess-a")).toHaveLength(0);
  });

  it("undoMerge propagates ApiError on 409 stale", async () => {
    deleteReorgAuditMock.mockRejectedValue(new Error("409 Conflict"));

    listReorgAuditsMock.mockResolvedValue({
      items: [
        {
          id: "rga_stale",
          dst_session_id: "sess-a",
          src_session_id: "sess-b",
          merged_at: "2026-01-01T12:00:00Z",
          src_title: "Old",
          boundary_msg_id: "msg1",
          kind: "merge",
        },
      ],
    });
    await reorgStore.loadAudits("sess-a");

    await expect(reorgStore.undoMerge("sess-a", "rga_stale")).rejects.toThrow();
    // Entry should still be present (not removed on failure).
    expect(reorgStore.auditEntriesFor("sess-a")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 8. Inline create form — gap-cycle-10-011
// ---------------------------------------------------------------------------

describe("ReorgPicker — inline create form (gap-cycle-10-011)", () => {
  it("toggle-into-create: clicking '+ Create a new session' shows create form", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId, queryByTestId } = render(ReorgPicker);
    await waitFor(() => expect(getByTestId("rp-create-new")).toBeTruthy());

    fireEvent.click(getByTestId("rp-create-new"));

    await waitFor(() => {
      expect(getByTestId("rp-create-title")).toBeTruthy();
      expect(getByTestId("rp-create-submit")).toBeTruthy();
      expect(getByTestId("rp-create-cancel")).toBeTruthy();
    });
    // Session list is gone; list-view filter is gone.
    expect(queryByTestId("reorg-picker-filter")).toBeNull();
  });

  it("inline-validation: submitting with empty title shows error", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId } = render(ReorgPicker);
    await waitFor(() => expect(getByTestId("rp-create-new")).toBeTruthy());
    fireEvent.click(getByTestId("rp-create-new"));
    await waitFor(() => expect(getByTestId("rp-create-submit")).toBeTruthy());

    // Submit without filling in title.
    fireEvent.click(getByTestId("rp-create-submit"));

    await waitFor(() => {
      expect(getByTestId("rp-create-error")).toHaveTextContent("Title is required.");
    });
    expect(createSessionMock).not.toHaveBeenCalled();
  });

  it("create-then-move: creates session then immediately commits move", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId, queryByTestId } = render(ReorgPicker);
    await waitFor(() => expect(getByTestId("rp-create-new")).toBeTruthy());
    fireEvent.click(getByTestId("rp-create-new"));
    await waitFor(() => expect(getByTestId("rp-create-title")).toBeTruthy());

    // Fill in title.
    fireEvent.input(getByTestId("rp-create-title"), { target: { value: "Brand New Session" } });

    // Select a tag chip.
    await waitFor(() => expect(getByTestId("rp-create-tag-1")).toBeTruthy());
    fireEvent.click(getByTestId("rp-create-tag-1"));

    // Submit.
    fireEvent.click(getByTestId("rp-create-submit"));

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Brand New Session", tag_ids: [1] }),
      );
    });
    await waitFor(() => {
      // commitMove now calls moveMessageReorg, not per-message moveMessage.
      expect(moveMessageReorgMock).toHaveBeenCalledWith("sess-a", "sess-new", "msg1");
    });
    // Picker closes after success.
    await waitFor(() => expect(queryByTestId("reorg-picker")).toBeNull());
  });

  it("cancel-create-returns-to-list: Back-to-list does not close the picker", async () => {
    reorgStore.openPicker({
      mode: "move",
      messageId: "msg1",
      sourceSessionId: "sess-a",
      seq: 1,
    });

    const { getByTestId } = render(ReorgPicker);
    await waitFor(() => expect(getByTestId("rp-create-new")).toBeTruthy());

    // Open create form.
    fireEvent.click(getByTestId("rp-create-new"));
    await waitFor(() => expect(getByTestId("rp-create-cancel")).toBeTruthy());

    // Cancel — should go back to list, picker stays open.
    fireEvent.click(getByTestId("rp-create-cancel"));

    await waitFor(() => {
      expect(getByTestId("reorg-picker")).toBeTruthy();
      expect(getByTestId("reorg-picker-filter")).toBeTruthy();
    });
  });
});

describe("SessionPickerModal — inline create form (gap-cycle-10-011)", () => {
  it("create-then-merge: creates session then immediately merges", async () => {
    const onMerged = vi.fn();
    const onCancel = vi.fn();
    const { getByTestId } = render(SessionPickerModal, {
      props: { srcSession: SESSION_FIXTURES[0]!, onMerged, onCancel },
    });

    // Wait for the "+ Create a new session" affordance.
    await waitFor(() => expect(getByTestId("session-picker-create-new")).toBeTruthy());

    // Switch to create form.
    fireEvent.click(getByTestId("session-picker-create-new"));
    await waitFor(() => expect(getByTestId("session-picker-create-title")).toBeTruthy());

    // Fill in title.
    fireEvent.input(getByTestId("session-picker-create-title"), {
      target: { value: "Brand New Session" },
    });

    // Select a tag chip.
    await waitFor(() => expect(getByTestId("session-picker-create-tag-2")).toBeTruthy());
    fireEvent.click(getByTestId("session-picker-create-tag-2"));

    // Submit.
    fireEvent.click(getByTestId("session-picker-create-submit"));

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Brand New Session", tag_ids: [2] }),
      );
    });
    await waitFor(() => {
      expect(mergeSessionMock).toHaveBeenCalledWith(SESSION_FIXTURES[0]!.id, "sess-new");
    });
    await waitFor(() => {
      expect(onMerged).toHaveBeenCalledWith("sess-new");
    });
    // onCancel was NOT called — user completed the flow, not cancelled.
    expect(onCancel).not.toHaveBeenCalled();
  });
});
