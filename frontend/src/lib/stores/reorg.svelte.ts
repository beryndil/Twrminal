/**
 * Reorg store — state management for the conversation reorganisation
 * surface: session picker, audit dividers, undo toast, and the
 * LLM-assisted proposal editor.
 *
 * Behavior anchor: ``docs/behavior/context-menus.md`` §"Message bubble"
 * — ``move_to_session`` and ``split_here`` both open the ReorgPicker.
 * After a successful commit the source conversation gains an inline
 * ReorgAuditDivider and a 30-second ReorgUndoToast appears.
 */
import { listMessages } from "../api/messages";
import { moveMessage } from "../api/messages";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** A completed reorg operation recorded as an inline audit divider. */
export interface ReorgAuditEntry {
  /** Client-generated id for keying in ``#each``. */
  id: string;
  /** The message ID at the boundary (moved message for "move"; first message of the split range for "split"). */
  anchorMessageId: string;
  /** "move" = single message moved; "split" = boundary carved, messages at + after moved. */
  kind: "move" | "split";
  /** How many messages were moved/split. */
  count: number;
  /** Target session id. */
  targetSessionId: string;
  /** Target session title for display. */
  targetSessionTitle: string;
  /** ISO timestamp of the operation. */
  timestamp: string;
}

/** Payload kept for the 30-second undo affordance. */
export interface ReorgUndoPayload {
  /** The audit entry this undo would reverse. */
  entry: ReorgAuditEntry;
  /** The original session id (to move back to). */
  originalSessionId: string;
  /** Message IDs that were moved, in original order. */
  movedMessageIds: string[];
}

/** Picker open state — null when closed. */
export interface ReorgPickerState {
  /** Which context-menu action triggered the picker. */
  mode: "move" | "split";
  /** The message the user right-clicked. */
  messageId: string;
  /** The conversation's current session id. */
  sourceSessionId: string;
  /** ``seq`` of the right-clicked message (split moves this + all later). */
  seq: number;
}

/** One proposed split boundary from ``analyzeReorg``. */
export interface ReorgProposal {
  /** Message id at the proposed boundary. */
  messageId: string;
  /** Human-readable reason for the proposed split. */
  reason: string;
}

// ---------------------------------------------------------------------------
// Module-level reactive state (Svelte 5 runes)
// ---------------------------------------------------------------------------

const UNDO_TIMEOUT_MS = 30_000;

/** Current picker state. Null = closed. */
let _picker = $state<ReorgPickerState | null>(null);

/** Per-session audit dividers. Key = sourceSessionId. */
let _auditMap = $state<Map<string, ReorgAuditEntry[]>>(new Map());

/** Active undo payload. Null = toast not showing. */
let _undo = $state<ReorgUndoPayload | null>(null);

/** Handle for the undo auto-dismiss timer. */
let _undoTimer: ReturnType<typeof setTimeout> | null = null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function clearUndoTimer(): void {
  if (_undoTimer !== null) {
    clearTimeout(_undoTimer);
    _undoTimer = null;
  }
}

// ---------------------------------------------------------------------------
// Public store object
// ---------------------------------------------------------------------------

export const reorgStore = {
  /** Current picker state — reactive. Null = picker closed. */
  get picker(): ReorgPickerState | null {
    return _picker;
  },

  /** Current undo payload — reactive. Null = toast not visible. */
  get undo(): ReorgUndoPayload | null {
    return _undo;
  },

  /**
   * Reactive audit entries for a given source session.
   * Returns a new array each time the map changes.
   */
  auditEntriesFor(sessionId: string): ReorgAuditEntry[] {
    return _auditMap.get(sessionId) ?? [];
  },

  // ---- Picker controls ---------------------------------------------------

  /** Open the picker for the given mode + message. */
  openPicker(state: ReorgPickerState): void {
    _picker = state;
  },

  /** Close the picker without committing. */
  closePicker(): void {
    _picker = null;
  },

  // ---- Commit (called by ReorgPicker on confirm) -------------------------

  /**
   * Move a single message to another session and record the audit
   * divider + undo toast.
   */
  async commitMove(
    sourceSessionId: string,
    messageId: string,
    targetSessionId: string,
    targetSessionTitle: string,
  ): Promise<void> {
    await moveMessage(messageId, targetSessionId);

    const entry: ReorgAuditEntry = {
      id: makeId(),
      anchorMessageId: messageId,
      kind: "move",
      count: 1,
      targetSessionId,
      targetSessionTitle,
      timestamp: new Date().toISOString(),
    };
    _addAuditEntry(sourceSessionId, entry);

    reorgStore.showUndoToast({
      entry,
      originalSessionId: sourceSessionId,
      movedMessageIds: [messageId],
    });
  },

  /**
   * Split from ``startSeq`` (inclusive) — move all messages at or after
   * that seq to the target session.  Fetches the full message list to
   * determine the affected set; moves each in order.
   */
  async commitSplit(
    sourceSessionId: string,
    startMessageId: string,
    startSeq: number,
    targetSessionId: string,
    targetSessionTitle: string,
  ): Promise<void> {
    // Fetch full list (no limit) so we can identify all messages at/after the split.
    const page = await listMessages(sourceSessionId);
    const affected = page.items.filter((m) => m.seq >= startSeq);

    for (const msg of affected) {
      await moveMessage(msg.id, targetSessionId);
    }

    const entry: ReorgAuditEntry = {
      id: makeId(),
      anchorMessageId: startMessageId,
      kind: "split",
      count: affected.length,
      targetSessionId,
      targetSessionTitle,
      timestamp: new Date().toISOString(),
    };
    _addAuditEntry(sourceSessionId, entry);

    reorgStore.showUndoToast({
      entry,
      originalSessionId: sourceSessionId,
      movedMessageIds: affected.map((m) => m.id),
    });
  },

  // ---- Undo toast --------------------------------------------------------

  /**
   * Show the undo toast and start the 30-second auto-dismiss timer.
   * Calling again replaces the current toast.
   */
  showUndoToast(payload: ReorgUndoPayload): void {
    clearUndoTimer();
    _undo = payload;
    _undoTimer = setTimeout(() => {
      _undo = null;
      _undoTimer = null;
    }, UNDO_TIMEOUT_MS);
  },

  /** Reverse a committed reorg — moves messages back to the original session. */
  async undoReorg(payload: ReorgUndoPayload): Promise<void> {
    clearUndoTimer();
    _undo = null;

    for (const msgId of payload.movedMessageIds) {
      await moveMessage(msgId, payload.originalSessionId);
    }

    // Remove the audit divider for this entry.
    const existing = _auditMap.get(payload.originalSessionId) ?? [];
    const updated = existing.filter((e) => e.id !== payload.entry.id);
    const next = new Map(_auditMap);
    next.set(payload.originalSessionId, updated);
    _auditMap = next;
  },

  /** Dismiss the toast without reversing the operation. */
  dismissUndoToast(): void {
    clearUndoTimer();
    _undo = null;
  },
};

// ---------------------------------------------------------------------------
// Internal helpers (not exported)
// ---------------------------------------------------------------------------

function _addAuditEntry(sourceSessionId: string, entry: ReorgAuditEntry): void {
  const existing = _auditMap.get(sourceSessionId) ?? [];
  const next = new Map(_auditMap);
  next.set(sourceSessionId, [...existing, entry]);
  _auditMap = next;
}

// ---------------------------------------------------------------------------
// analyzeReorg — heuristic proposal generator
// ---------------------------------------------------------------------------

/**
 * Analyse a session's messages and propose split boundaries.
 *
 * Heuristic rules (no LLM call — runs entirely client-side):
 *   1. A time gap of ≥ 30 min between consecutive turns suggests a
 *      new topic.
 *   2. Every N turns (default 10) a natural chunk boundary is proposed.
 *
 * Returns a list of proposals ordered by message position.  The
 * ReorgProposalEditor renders these for the user to accept or dismiss.
 */
export async function analyzeReorg(
  sessionId: string,
  chunkSize = 10,
): Promise<ReorgProposal[]> {
  const page = await listMessages(sessionId);
  const msgs = page.items;
  const proposals: ReorgProposal[] = [];

  const GAP_MS = 30 * 60 * 1000; // 30 minutes

  msgs.forEach((msg, idx) => {
    if (idx === 0) return;
    const prev = msgs[idx - 1];
    if (!prev) return;

    const prevTs = prev.created_at ? new Date(prev.created_at).getTime() : 0;
    const curTs = msg.created_at ? new Date(msg.created_at).getTime() : 0;

    if (prevTs > 0 && curTs > 0 && curTs - prevTs >= GAP_MS) {
      proposals.push({
        messageId: msg.id,
        reason: `~${Math.round((curTs - prevTs) / 60_000)} min gap before this message`,
      });
      return;
    }

    if (idx % chunkSize === 0) {
      proposals.push({
        messageId: msg.id,
        reason: `Natural chunk boundary at message ${idx + 1}`,
      });
    }
  });

  return proposals;
}

// ---------------------------------------------------------------------------
// Test seams
// ---------------------------------------------------------------------------

/** Reset all store state. Test use only. */
export function _resetReorgForTests(): void {
  clearUndoTimer();
  _picker = null;
  _auditMap = new Map();
  _undo = null;
}
