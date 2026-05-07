/**
 * Typed client for the reorg surface (gap-cycle-03-008/009).
 *
 * Owns the merge, audit-list, and undo calls. Wire shapes mirror
 * :class:`bearings.web.models.reorg.ReorgAuditOut`,
 * :class:`bearings.web.models.reorg.ReorgAuditListOut`, and
 * :class:`bearings.web.models.reorg.UndoMergeOut`.
 */
import {
  sessionReorgAuditEndpoint,
  sessionReorgAuditsEndpoint,
  sessionReorgMergeEndpoint,
} from "../config";
import { deleteResource, getJson, postJson } from "./client";

/**
 * Wire shape for one merge-operation audit record — one-to-one with
 * :class:`bearings.web.models.reorg.ReorgAuditOut`.
 */
export interface ReorgAuditOut {
  id: string;
  dst_session_id: string;
  src_session_id: string;
  merged_at: string;
  src_title: string;
  boundary_msg_id: string | null;
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
 * :class:`bearings.web.models.reorg.UndoMergeOut`.
 */
export interface UndoMergeOut {
  new_session_id: string;
}

/**
 * Merge ``srcId`` into ``dstId``.
 *
 * Calls ``POST /api/sessions/{src}/reorg/merge?target={dst}``.
 * Returns the audit record on success.
 * Throws :class:`ApiError` (409 for self-merge, 404 for missing
 * session, 5xx for server errors).
 */
export async function mergeSession(
  srcId: string,
  dstId: string,
): Promise<ReorgAuditOut> {
  return await postJson<ReorgAuditOut>(sessionReorgMergeEndpoint(srcId, dstId), undefined);
}

/**
 * Fetch all merge-audit rows for ``sessionId``, oldest-first.
 *
 * Calls ``GET /api/sessions/{id}/reorg/audits``.
 * Returns an empty list when no merges have been performed into this
 * session.
 */
export async function listReorgAudits(sessionId: string): Promise<ReorgAuditListOut> {
  return await getJson<ReorgAuditListOut>(sessionReorgAuditsEndpoint(sessionId));
}

/**
 * Undo the merge recorded by ``auditId`` in ``sessionId``.
 *
 * Calls ``DELETE /api/sessions/{id}/reorg/audits/{auditId}``.
 * Returns the id of the newly re-created source session on success.
 * Throws :class:`ApiError` (404 when audit absent, 409 when stale).
 */
export async function deleteReorgAudit(
  sessionId: string,
  auditId: string,
): Promise<UndoMergeOut> {
  return await deleteResource<UndoMergeOut>(sessionReorgAuditEndpoint(sessionId, auditId));
}
