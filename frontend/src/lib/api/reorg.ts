/**
 * Typed client for the reorg surface (gap-cycle-03-008/009, gap-cycle-13-002).
 *
 * Owns merge, split, move, audit-list, and undo calls.  Wire shapes mirror
 * :class:`bearings.web.models.reorg.ReorgAuditOut`,
 * :class:`bearings.web.models.reorg.ReorgSplitOut`,
 * :class:`bearings.web.models.reorg.ReorgAuditListOut`, and
 * :class:`bearings.web.models.reorg.UndoReorgOut`.
 */
import {
  sessionReorgAuditEndpoint,
  sessionReorgAuditsEndpoint,
  sessionReorgMergeEndpoint,
  sessionReorgMoveEndpoint,
  sessionReorgSplitEndpoint,
} from "../config";
import { deleteResource, getJson, postJson } from "./client";

/**
 * Wire shape for one reorg audit record — one-to-one with
 * :class:`bearings.web.models.reorg.ReorgAuditOut`.
 *
 * ``kind`` is ``'merge'``, ``'split'``, or ``'move'``.
 * ``dst_session_id`` is always the session that hosts the divider;
 * ``src_session_id`` is the "other" session (deleted for merge,
 * still-live target for split/move).
 */
export interface ReorgAuditOut {
  id: string;
  dst_session_id: string;
  src_session_id: string;
  merged_at: string;
  src_title: string;
  boundary_msg_id: string | null;
  kind: "merge" | "split" | "move";
}

/**
 * Wire shape for the split response — one-to-one with
 * :class:`bearings.web.models.reorg.ReorgSplitOut`.
 */
export interface ReorgSplitOut {
  audit: ReorgAuditOut;
  moved_message_ids: string[];
}

/**
 * Wire shape for the audit-list response — one-to-one with
 * :class:`bearings.web.models.reorg.ReorgAuditListOut`.
 */
export interface ReorgAuditListOut {
  items: ReorgAuditOut[];
}

/**
 * Wire shape for a successful undo response — one-to-one with
 * :class:`bearings.web.models.reorg.UndoReorgOut`.
 */
export interface UndoMergeOut {
  new_session_id: string;
}

/**
 * Merge ``srcId`` into ``dstId``.
 *
 * Calls ``POST /api/sessions/{src}/reorg/merge?target={dst}``.
 * Returns the audit record on success.
 * Throws :class:`ApiError` (409 for self-merge, 404 for missing session).
 */
export async function mergeSession(
  srcId: string,
  dstId: string,
): Promise<ReorgAuditOut> {
  return await postJson<ReorgAuditOut>(sessionReorgMergeEndpoint(srcId, dstId), undefined);
}

/**
 * Split ``srcId`` at ``fromSeq`` into ``dstId``.
 *
 * Calls ``POST /api/sessions/{src}/reorg/split?target={dst}&from_seq={n}``.
 * Re-parents all messages with rowid >= ``fromSeq`` from ``srcId`` to
 * ``dstId`` in one atomic transaction.  Returns the audit row and the list
 * of moved message ids.
 * Throws :class:`ApiError` (409 for self-split, 404 for missing session).
 */
export async function splitSession(
  srcId: string,
  dstId: string,
  fromSeq: number,
): Promise<ReorgSplitOut> {
  return await postJson<ReorgSplitOut>(
    sessionReorgSplitEndpoint(srcId, dstId, fromSeq),
    undefined,
  );
}

/**
 * Move a single message from ``srcId`` to ``dstId``.
 *
 * Calls ``POST /api/sessions/{src}/reorg/move?target={dst}&message_id={id}``.
 * Returns the audit row on success.
 * Throws :class:`ApiError` (409 for self-move, 404 when session or message absent).
 */
export async function moveMessageReorg(
  srcId: string,
  dstId: string,
  messageId: string,
): Promise<ReorgAuditOut> {
  return await postJson<ReorgAuditOut>(
    sessionReorgMoveEndpoint(srcId, dstId, messageId),
    undefined,
  );
}

/**
 * Fetch all reorg-audit rows for ``sessionId`` (all kinds), oldest-first.
 *
 * Calls ``GET /api/sessions/{id}/reorg/audits``.
 * Returns an empty list when no reorg operations have been performed on
 * this session.
 */
export async function listReorgAudits(sessionId: string): Promise<ReorgAuditListOut> {
  return await getJson<ReorgAuditListOut>(sessionReorgAuditsEndpoint(sessionId));
}

/**
 * Undo the reorg recorded by ``auditId`` in ``sessionId``.
 *
 * Calls ``DELETE /api/sessions/{id}/reorg/audits/{auditId}``.
 * Works for merge, split, and move kinds.
 * Returns the id of the session to navigate to on success.
 * Throws :class:`ApiError` (404 when audit absent, 409 when stale).
 */
export async function deleteReorgAudit(
  sessionId: string,
  auditId: string,
): Promise<UndoMergeOut> {
  return await deleteResource<UndoMergeOut>(sessionReorgAuditEndpoint(sessionId, auditId));
}
