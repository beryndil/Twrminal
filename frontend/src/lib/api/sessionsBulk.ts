/**
 * Typed client for ``POST /api/sessions/bulk`` (gap-cycle-13-001).
 *
 * Replaces the N-independent-HTTP-request pattern the sidebar used for
 * multi-select close / delete / export / tag / untag with a single atomic
 * server-side call that returns per-ID success/failure results.
 *
 * The backend executes mutating ops (close, delete, tag, untag) in a single
 * DB transaction with per-ID savepoints so a failure on one ID does not
 * affect the rest. Callers inspect each ``BulkResultItem.ok`` field to
 * detect partial failures and surface them to the user.
 *
 * The ``export`` op is read-only — the backend assembles a single
 * ``BulkExportBundle`` JSON object and returns it as ``application/json``.
 * This client returns a ``Blob`` for that op so the caller can trigger a
 * browser download directly.
 *
 * Per ``docs/behavior/sessions.md`` §"Bulk operations contract".
 */
import { API_SESSIONS_BULK_ENDPOINT } from "../config";
import { ApiError } from "./client";

// ---------------------------------------------------------------------------
// Wire shapes (mirror bearings.web.models.sessions)
// ---------------------------------------------------------------------------

/** One per-ID result entry returned by the bulk endpoint (non-export ops). */
export interface BulkResultItem {
  session_id: string;
  ok: boolean;
  detail?: string | null;
}

/** Response body for close / delete / tag / untag bulk ops. */
export interface BulkSessionsOut {
  op: string;
  results: BulkResultItem[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const HTTP_OK_MIN = 200;
const HTTP_OK_MAX = 300;

async function _postBulk(body: Record<string, unknown>): Promise<Response> {
  const resp = await fetch(API_SESSIONS_BULK_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (resp.status < HTTP_OK_MIN || resp.status >= HTTP_OK_MAX) {
    let errorBody: unknown = null;
    try {
      errorBody = await resp.json();
    } catch {
      try {
        errorBody = await resp.text();
      } catch {
        // ignore
      }
    }
    throw new ApiError(
      resp.status,
      errorBody,
      `POST /api/sessions/bulk (op=${String(body["op"])}) → ${resp.status} ${resp.statusText}`,
    );
  }
  return resp;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Close multiple sessions in a single atomic server-side call.
 *
 * Returns the per-ID result list. Partial failures (``ok=false``) are
 * included in the result rather than thrown so the UI can surface a
 * "N of M closed; K failed" summary.
 *
 * @throws {@link ApiError} on network failure or non-2xx HTTP (e.g. 422
 *   for malformed request, 503 for DB not configured).
 */
export async function bulkCloseSessions(sessionIds: string[]): Promise<BulkSessionsOut> {
  const resp = await _postBulk({ op: "close", session_ids: sessionIds });
  return (await resp.json()) as BulkSessionsOut;
}

/**
 * Delete multiple sessions in a single atomic server-side call.
 *
 * Returns the per-ID result list. Partial failures are included in the
 * result rather than thrown.
 *
 * @throws {@link ApiError} on network failure or non-2xx HTTP.
 */
export async function bulkDeleteSessions(sessionIds: string[]): Promise<BulkSessionsOut> {
  const resp = await _postBulk({ op: "delete", session_ids: sessionIds });
  return (await resp.json()) as BulkSessionsOut;
}

/**
 * Attach *tagId* to multiple sessions in a single atomic server-side call.
 *
 * Returns the per-ID result list.
 *
 * @throws {@link ApiError} on network failure or non-2xx HTTP.
 */
export async function bulkTagSessions(
  sessionIds: string[],
  tagId: number,
): Promise<BulkSessionsOut> {
  const resp = await _postBulk({ op: "tag", session_ids: sessionIds, tag_id: tagId });
  return (await resp.json()) as BulkSessionsOut;
}

/**
 * Detach *tagId* from multiple sessions in a single atomic server-side call.
 *
 * Returns the per-ID result list.
 *
 * @throws {@link ApiError} on network failure or non-2xx HTTP.
 */
export async function bulkUntagSessions(
  sessionIds: string[],
  tagId: number,
): Promise<BulkSessionsOut> {
  const resp = await _postBulk({ op: "untag", session_ids: sessionIds, tag_id: tagId });
  return (await resp.json()) as BulkSessionsOut;
}

/**
 * Export multiple sessions as a single bundled JSON download.
 *
 * The backend assembles ``{sessions: [SessionExport|null, …]}`` in one
 * pass and streams the bundle as ``application/json``. This function
 * returns the raw ``Blob`` so the caller can create an object URL and
 * trigger a browser ``<a download>`` click.
 *
 * Sessions not found on the server produce a ``null`` slot in the array
 * — the bundle is still valid; the importer skips nulls.
 *
 * @throws {@link ApiError} on network failure or non-2xx HTTP.
 */
export async function bulkExportSessions(sessionIds: string[]): Promise<Blob> {
  const resp = await _postBulk({ op: "export", session_ids: sessionIds });
  return await resp.blob();
}
