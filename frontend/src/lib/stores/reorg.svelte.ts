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
import { listMessages, moveMessage } from "../api/messages";
import {
  deleteReorgAudit,
  listReorgAudits,
  moveMessageReorg,
  splitSession,
} from "../api/reorg";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** A completed reorg operation recorded as an inline audit divider. */
export interface ReorgAuditEntry {
  /** Client-generated id for keying in ``#each``. */
  id: string;
  /** The message ID at the boundary (moved message for "move"; first message of the split range for "split"; first re-parented message for "merge"). */
  anchorMessageId: string;
  /**
   * "move" = single message moved; "split" = boundary carved;
   * "merge" = server-backed merge operation (persistent across refresh).
   */
  kind: "move" | "split" | "merge";
  /** How many messages were moved/split/merged. */
  count: number;
  /** Target session id. */
  targetSessionId: string;
  /** Target session title for display. */
  targetSessionTitle: string;
  /** ISO timestamp of the operation. */
  timestamp: string;
  /**
   * Server-side audit row id.  Only set for ``kind === "merge"`` entries
   * loaded from (or written to) the backend.  Used to call the DELETE
   * undo endpoint.
   */
  serverAuditId?: string;
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

  // ---- Server-audit hydration (called on conversation load) ---------------

  /**
   * Fetch all reorg-audit rows from the server for ``sessionId`` (all
   * kinds: merge, split, move) and populate ``_auditMap``.  Skips any
   * audit whose ``boundary_msg_id`` is null (no divider to render).
   *
   * Idempotent: replaces all previously server-backed entries for the
   * session (those with a ``serverAuditId``) and keeps any purely
   * client-only entries.  Safe to call on every conversation mount.
   */
  async loadAudits(sessionId: string): Promise<void> {
    const list = await listReorgAudits(sessionId);
    const serverEntries: ReorgAuditEntry[] = list.items
      .filter((a) => a.boundary_msg_id !== null)
      .map((a) => ({
        id: a.id,
        anchorMessageId: a.boundary_msg_id as string,
        kind: a.kind,
        // count is unknown from the audit row alone; use 0 as sentinel.
        count: 0,
        targetSessionId: a.src_session_id,
        targetSessionTitle: a.src_title,
        timestamp: a.merged_at,
        serverAuditId: a.id,
      }));

    // Keep only entries that have no server backing; server entries are
    // replaced wholesale by the fresh fetch.
    const existing = _auditMap.get(sessionId) ?? [];
    const clientOnly = existing.filter((e) => e.serverAuditId === undefined);
    const next = new Map(_auditMap);
    next.set(sessionId, [...serverEntries, ...clientOnly]);
    _auditMap = next;
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
   * Move a single message to another session via the server-backed
   * atomic endpoint, record the persistent audit divider, and show the
   * undo toast.
   *
   * Calls ``POST /api/sessions/{src}/reorg/move`` which writes a
   * ``kind='move'`` audit row in the same transaction.  The resulting
   * ``serverAuditId`` enables server-side undo via the DELETE endpoint.
   */
  async commitMove(
    sourceSessionId: string,
    messageId: string,
    targetSessionId: string,
    targetSessionTitle: string,
  ): Promise<void> {
    const audit = await moveMessageReorg(sourceSessionId, targetSessionId, messageId);

    const entry: ReorgAuditEntry = {
      id: audit.id,
      anchorMessageId: messageId,
      kind: "move",
      count: 1,
      targetSessionId,
      targetSessionTitle,
      timestamp: audit.merged_at,
      serverAuditId: audit.id,
    };
    _addAuditEntry(sourceSessionId, entry);

    reorgStore.showUndoToast({
      entry,
      originalSessionId: sourceSessionId,
      movedMessageIds: [messageId],
    });
  },

  /**
   * Split ``sourceSessionId`` at ``startSeq`` into ``targetSessionId``
   * via the server-backed atomic endpoint.
   *
   * Calls ``POST /api/sessions/{src}/reorg/split`` which re-parents all
   * messages with ``rowid >= startSeq`` in a single transaction and writes
   * a ``kind='split'`` audit row.  The resulting ``serverAuditId`` enables
   * server-side atomic undo via the DELETE endpoint.
   */
  async commitSplit(
    sourceSessionId: string,
    startMessageId: string,
    startSeq: number,
    targetSessionId: string,
    targetSessionTitle: string,
  ): Promise<void> {
    const result = await splitSession(sourceSessionId, targetSessionId, startSeq);

    const entry: ReorgAuditEntry = {
      id: result.audit.id,
      anchorMessageId: startMessageId,
      kind: "split",
      count: result.moved_message_ids.length,
      targetSessionId,
      targetSessionTitle,
      timestamp: result.audit.merged_at,
      serverAuditId: result.audit.id,
    };
    _addAuditEntry(sourceSessionId, entry);

    reorgStore.showUndoToast({
      entry,
      originalSessionId: sourceSessionId,
      movedMessageIds: result.moved_message_ids,
    });
  },

  // ---- Server-backed merge undo ------------------------------------------

  /**
   * Undo a server-recorded merge by calling the DELETE endpoint.
   *
   * Removes the ``"merge"`` audit entry from ``_auditMap`` on success.
   * Propagates :class:`ApiError` with status 409 when the audit is stale
   * (caller should surface that to the user).
   *
   * ``sessionId`` is the destination session (the one that received the
   * merged messages).  ``auditId`` is the server-side audit row id
   * (``entry.serverAuditId``).
   */
  async undoMerge(sessionId: string, auditId: string): Promise<string> {
    const result = await deleteReorgAudit(sessionId, auditId);
    // Remove the divider from the map on success.
    const existing = _auditMap.get(sessionId) ?? [];
    const updated = existing.filter((e) => e.serverAuditId !== auditId);
    const next = new Map(_auditMap);
    next.set(sessionId, updated);
    _auditMap = next;
    return result.new_session_id;
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

  /**
   * Reverse a committed reorg.
   *
   * When the entry has a ``serverAuditId`` (which is always the case for
   * move and split after gap-cycle-13-002, and for merge), this delegates
   * to the server-side DELETE audit endpoint for an atomic, durable undo.
   * ``undoMerge`` also removes the entry from ``_auditMap``.
   *
   * The legacy per-message ``moveMessage`` path is retained as a safety
   * net for entries that somehow lack a ``serverAuditId``.
   */
  async undoReorg(payload: ReorgUndoPayload): Promise<void> {
    clearUndoTimer();
    _undo = null;

    if (payload.entry.serverAuditId !== undefined) {
      // Server-backed atomic undo — works for merge, split, and move.
      // originalSessionId == dst_session_id in the audit (the session hosting the divider).
      await reorgStore.undoMerge(payload.originalSessionId, payload.entry.serverAuditId);
      return;
    }

    // Legacy fallback: client-only entry without a server audit row.
    for (const msgId of payload.movedMessageIds) {
      await moveMessage(msgId, payload.originalSessionId);
    }

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
