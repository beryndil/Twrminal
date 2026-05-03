/**
 * Typed client for ``POST /api/sessions/{id}/approvals/{request_id}`` —
 * the approval-modal submit surface (``src/bearings/web/routes/approvals.py``
 * Slice A4).
 *
 * The endpoint returns 204 No Content on success. The caller receives
 * an :class:`ApiError` on 404 (no live broker), 409 (duplicate /
 * already-resolved request_id), or any other non-2xx.
 *
 * For standard tool approvals (``ApprovalModal``) only ``approved``
 * is sent. For ``AskUserQuestion`` approvals (``AskUserQuestionModal``)
 * ``answer`` carries the user's typed text; the backend threads it
 * back to the SDK callback as ``PermissionResultAllow.updated_input``
 * so the agent receives the answer as the tool result.
 */
import { sessionApprovalEndpoint } from "../config";
import { ApiError } from "./client";

const HTTP_OK_MIN = 200;
const HTTP_OK_MAX = 300;

/**
 * Resolve a pending ``can_use_tool`` approval request.
 *
 * @param sessionId  The session that owns the in-flight approval.
 * @param requestId  The ``request_id`` from the ``approval_request`` event.
 * @param approved   ``true`` to allow, ``false`` to deny.
 * @param answer     Optional text answer for ``AskUserQuestion`` approvals.
 */
export async function postApproval(
  sessionId: string,
  requestId: string,
  approved: boolean,
  answer?: string,
): Promise<void> {
  const body: { approved: boolean; answer?: string } = { approved };
  if (answer !== undefined) {
    body.answer = answer;
  }
  const response = await fetch(sessionApprovalEndpoint(sessionId, requestId), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  if (response.status < HTTP_OK_MIN || response.status >= HTTP_OK_MAX) {
    let errorBody: unknown = null;
    try {
      errorBody = await response.json();
    } catch {
      try {
        errorBody = await response.text();
      } catch {
        // ignore
      }
    }
    throw new ApiError(
      response.status,
      errorBody,
      `POST approval ${requestId} → ${response.status} ${response.statusText}`,
    );
  }
  // 204 No Content — nothing to parse.
}
