/**
 * Typed client for the reorg surface (gap-cycle-03-008).
 *
 * Owns the ``POST /api/sessions/{src}/reorg/merge`` call that merges
 * one session into another. Mirrors
 * :class:`bearings.web.models.reorg.ReorgAuditOut`.
 */
import { sessionReorgMergeEndpoint } from "../config";
import { postJson } from "./client";

/**
 * Wire shape for a successful merge response — one-to-one with
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
