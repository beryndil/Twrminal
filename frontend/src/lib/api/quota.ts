/**
 * Typed client for ``GET /api/quota/current`` (spec §4 + §9 + §10).
 *
 * The new-session dialog (item 2.4) reads the latest snapshot to
 * render the in-dialog QuotaBars per spec §6 layout; the session
 * header in the conversation pane will read the same shape (item 2.5
 * onward). Backend route + Pydantic shape:
 *
 * * route — :func:`bearings.web.routes.quota.get_current`
 *   (``src/bearings/web/routes/quota.py:62``);
 * * response — :class:`bearings.web.models.quota.QuotaSnapshotOut`.
 *
 * Documented empty-state responses (never log to console):
 *
 * * 404 — the poller has never succeeded (no snapshot yet);
 * * 503 — quota poller not configured (test apps; bare runtime);
 * * 502 — upstream ``/usage`` poll failed (transient).
 *
 * In every empty-state case the caller receives ``null`` from
 * :func:`getCurrentQuotaSafe`; the dialog falls back to the
 * ``quota_state`` block on the routing-preview response, so a
 * failure here never blocks session creation.
 */
import {
  API_QUOTA_CURRENT_ENDPOINT,
  API_QUOTA_HISTORY_ENDPOINT,
  USAGE_HEADROOM_WINDOW_DAYS,
} from "../config";
import { ApiError, getJson, type RequestOptions } from "./client";

/**
 * Wire shape for one snapshot — one-to-one with
 * :class:`bearings.web.models.quota.QuotaSnapshotOut`.
 *
 * ``overall_used_pct`` / ``sonnet_used_pct`` are fractions in
 * ``[0.0, 1.0]`` (or ``null`` when the upstream payload didn't
 * include the bucket); ``*_resets_at`` are unix timestamps; the
 * ``raw_payload`` JSON string is exposed for forward-compat reads
 * the dialog doesn't use today.
 */
export interface QuotaSnapshot {
  captured_at: number;
  overall_used_pct: number | null;
  sonnet_used_pct: number | null;
  overall_resets_at: number | null;
  sonnet_resets_at: number | null;
  raw_payload: string;
}

/**
 * Fetch the latest quota snapshot.
 *
 * @throws :class:`ApiError` on non-2xx (404 / 502 / 503 — see module
 *   docstring); prefer :func:`getCurrentQuotaSafe` for UI paths that
 *   must stay console-clean on documented empty-state responses.
 */
export async function getCurrentQuota(
  options: { signal?: AbortSignal } = {},
): Promise<QuotaSnapshot> {
  const requestOptions: RequestOptions = {};
  if (options.signal !== undefined) {
    requestOptions.signal = options.signal;
  }
  return await getJson<QuotaSnapshot>(API_QUOTA_CURRENT_ENDPOINT, requestOptions);
}

/** HTTP status codes that indicate "no snapshot available yet" — not errors. */
const QUOTA_EMPTY_STATE_STATUSES: ReadonlySet<number> = new Set([404, 502, 503]);

/**
 * Fetch the latest quota snapshot, resolving to ``null`` on the
 * documented empty-state responses (404 — no snapshot yet; 503 — no
 * poller configured; 502 — upstream poll blip).
 *
 * UI components should call this variant so these expected conditions
 * never surface as a ``console.error``.  Unexpected errors (5xx other
 * than 502, network failures, …) are still re-thrown.
 */
export async function getCurrentQuotaSafe(
  options: { signal?: AbortSignal } = {},
): Promise<QuotaSnapshot | null> {
  try {
    return await getCurrentQuota(options);
  } catch (err) {
    if (err instanceof ApiError && QUOTA_EMPTY_STATE_STATUSES.has(err.status)) {
      return null;
    }
    throw err;
  }
}

/**
 * Fetch the rolling-window quota history (oldest first).
 *
 * Default window is :data:`USAGE_HEADROOM_WINDOW_DAYS` (7 days per
 * spec §10 "Headroom remaining chart"); the parameter is a positive
 * integer ≤ 365 enforced by FastAPI on the wire.
 *
 * Used by :class:`InspectorUsage` (item 2.6) to render the headroom
 * chart. An empty array is a valid response (fresh app with no
 * snapshots yet).
 *
 * @throws :class:`ApiError` on non-2xx (503 when ``db_connection``
 *   is missing on ``app.state``).
 */
export async function getQuotaHistory(
  options: { days?: number; signal?: AbortSignal } = {},
): Promise<QuotaSnapshot[]> {
  const days = options.days ?? USAGE_HEADROOM_WINDOW_DAYS;
  const requestOptions: RequestOptions = { query: [["days", String(days)]] };
  if (options.signal !== undefined) {
    requestOptions.signal = options.signal;
  }
  return await getJson<QuotaSnapshot[]>(API_QUOTA_HISTORY_ENDPOINT, requestOptions);
}
