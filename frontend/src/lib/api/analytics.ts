/**
 * Typed client for the ``/api/analytics/`` surface
 * (``BEARINGS_ANALYTICS_v1.md`` §9).
 *
 * Backend route module: :mod:`bearings.web.routes.analytics`.
 * Pydantic shapes: :mod:`bearings.web.models.analytics`.
 *
 * Consumers:
 *
 * * :class:`InspectorAnalytics` (Phase 5) — all read endpoints.
 *
 * All non-2xx responses flow through :class:`ApiError`; the
 * component renders the documented error copy from
 * :data:`INSPECTOR_STRINGS.analyticsError`.
 */
import {
  ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY,
  ANALYTICS_REDUNDANCY_DEFAULT_LAST_N,
  ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS,
  API_ANALYTICS_ATTRIBUTION_ENDPOINT,
  API_ANALYTICS_BUCKET_CURRENT_ENDPOINT,
  API_ANALYTICS_REDUNDANCY_ENDPOINT,
  API_ANALYTICS_SESSION_PLUG_SUMMARY_ENDPOINT,
  API_ANALYTICS_WARNINGS_SUPPRESS_ENDPOINT,
} from "../config";
import { getJson, postJson, type RequestOptions } from "./client";

// ---------------------------------------------------------------------------
// Response interfaces — one-to-one with Pydantic models
// ---------------------------------------------------------------------------

/**
 * One usage-window breakdown (five-hour or weekly).
 * Mirrors :class:`bearings.web.models.analytics.BucketWindowOut`.
 */
export interface BucketWindowOut {
  used: number;
  limit: number;
  /** Percentage 0-100 (rounded to 2dp by the backend). */
  percent: number;
}

/**
 * Latest ``/usage`` poll snapshot (spec §9.2 ``GET
 * /api/analytics/bucket/current``).
 * Mirrors :class:`bearings.web.models.analytics.BucketCurrentOut`.
 *
 * ``five_hour`` / ``weekly`` are ``null`` when the poller has never
 * produced data for that window.
 */
export interface BucketCurrentOut {
  five_hour: BucketWindowOut | null;
  weekly: BucketWindowOut | null;
  /** Unix ms of the snapshot's timestamp. */
  as_of: number;
}

/**
 * One row from ``GET /api/analytics/attribution`` (spec §9.2).
 * Mirrors :class:`bearings.web.models.analytics.TagAttributionOut`.
 *
 * ``tokens_by_model`` maps model id → token count.  Per spec §3.2
 * these must NOT be summed across models without normalisation; the
 * component renders them per-model to avoid mixing tokenizer output.
 */
export interface TagAttributionOut {
  tag: string;
  tokens_by_model: Record<string, number>;
  /** Fraction 0-1 of total bucket consumption. */
  share_total: number;
  /** Tokens per minute for this tag over the selected window. */
  burn_rate_per_min: number;
}

/**
 * One session reference within a redundancy block (spec §9.2).
 * Mirrors :class:`bearings.web.models.analytics.RedundancySessionRef`.
 */
export interface RedundancySessionRef {
  id: string;
  title: string;
  timestamp: number;
  tags: string[];
}

/**
 * One repeated plug block from ``GET /api/analytics/redundancy``
 * (spec §9.2 + §7.3).
 * Mirrors :class:`bearings.web.models.analytics.RedundancyBlockOut`.
 */
export interface RedundancyBlockOut {
  hash: string;
  block_type: string;
  token_count: number;
  token_count_model: string;
  repeat_count: number;
  /** ``repeat_count × token_count`` — total bucket cost of this block. */
  total_cost_tokens: number;
  source_path: string | null;
  sessions: RedundancySessionRef[];
}

/**
 * One block in a session's plug summary (spec §9.2).
 * Mirrors :class:`bearings.web.models.analytics.PlugSummaryBlockOut`.
 */
export interface PlugSummaryBlockOut {
  hash: string;
  block_type: string;
  tokens: number;
}

/**
 * Plug composition for one session (spec §9.2 ``GET
 * /api/analytics/sessions/{id}/plug-summary``).
 * Mirrors :class:`bearings.web.models.analytics.SessionPlugSummaryOut`.
 *
 * ``status`` is ``"green"`` / ``"yellow"`` / ``"red"`` per spec §8.1
 * thresholds (:data:`PLUG_YELLOW_THRESHOLD_TOKENS` /
 * :data:`PLUG_RED_THRESHOLD_TOKENS`).
 */
export interface SessionPlugSummaryOut {
  total_tokens: number;
  status: "green" | "yellow" | "red";
  blocks: PlugSummaryBlockOut[];
}

// ---------------------------------------------------------------------------
// Read clients
// ---------------------------------------------------------------------------

/**
 * Fetch the latest bucket usage snapshot.
 *
 * Returns ``{five_hour: null, weekly: null}`` when the poller has
 * never run successfully — always safe to call.
 *
 * @throws :class:`ApiError` on non-2xx (503 when DB missing).
 */
export async function getBucketCurrent(
  options: { signal?: AbortSignal } = {},
): Promise<BucketCurrentOut> {
  const requestOptions: RequestOptions = {};
  if (options.signal !== undefined) {
    requestOptions.signal = options.signal;
  }
  return await getJson<BucketCurrentOut>(API_ANALYTICS_BUCKET_CURRENT_ENDPOINT, requestOptions);
}

/**
 * Fetch per-tag token attribution for the requested time window.
 *
 * ``window`` is ``"5h"`` (rolling 5-hour) or ``"weekly"`` (rolling
 * 7-day, default). Per spec §3.2 results are already grouped by model
 * in ``tokens_by_model`` — callers must not sum across models.
 *
 * @throws :class:`ApiError` on non-2xx (422 for unknown window).
 */
export async function getAttribution(
  options: {
    window?: string;
    signal?: AbortSignal;
  } = {},
): Promise<TagAttributionOut[]> {
  const window = options.window ?? ANALYTICS_ATTRIBUTION_WINDOW_WEEKLY;
  const requestOptions: RequestOptions = {
    query: [
      ["window", window],
      ["group_by", "tag"],
    ],
  };
  if (options.signal !== undefined) {
    requestOptions.signal = options.signal;
  }
  return await getJson<TagAttributionOut[]>(API_ANALYTICS_ATTRIBUTION_ENDPOINT, requestOptions);
}

/**
 * Fetch repeated plug blocks within the requested scope.
 *
 * Results are sorted by ``total_cost_tokens`` descending (server-side).
 * ``tag`` filters to sessions with that tag name; ``null`` returns all.
 * ``lastN`` is the session-count scope (default
 * :data:`ANALYTICS_REDUNDANCY_DEFAULT_LAST_N`).
 * ``minRepeats`` is the minimum appearance count threshold (default
 * :data:`ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS`).
 * ``blockTypes`` is a comma-separated type filter; absent means all.
 *
 * @throws :class:`ApiError` on non-2xx (404 if tag not found, 422 for
 *   unknown block types).
 */
export async function getRedundancy(
  options: {
    tag?: string | null;
    lastN?: number;
    minRepeats?: number;
    blockTypes?: string | null;
    signal?: AbortSignal;
  } = {},
): Promise<RedundancyBlockOut[]> {
  const lastN = options.lastN ?? ANALYTICS_REDUNDANCY_DEFAULT_LAST_N;
  const minRepeats = options.minRepeats ?? ANALYTICS_REDUNDANCY_DEFAULT_MIN_REPEATS;
  const queryEntries: [string, string][] = [
    ["last_n", String(lastN)],
    ["min_repeats", String(minRepeats)],
  ];
  if (options.tag != null) {
    queryEntries.push(["tag", options.tag]);
  }
  if (options.blockTypes != null) {
    queryEntries.push(["block_types", options.blockTypes]);
  }
  const requestOptions: RequestOptions = { query: queryEntries };
  if (options.signal !== undefined) {
    requestOptions.signal = options.signal;
  }
  return await getJson<RedundancyBlockOut[]>(API_ANALYTICS_REDUNDANCY_ENDPOINT, requestOptions);
}

/**
 * Fetch the plug composition summary for one session.
 *
 * @throws :class:`ApiError` on non-2xx (404 when session not found,
 *   503 when DB missing).
 */
export async function getSessionPlugSummary(
  sessionId: string,
  options: { signal?: AbortSignal } = {},
): Promise<SessionPlugSummaryOut> {
  const path = `${API_ANALYTICS_SESSION_PLUG_SUMMARY_ENDPOINT}/${sessionId}/plug-summary`;
  const requestOptions: RequestOptions = {};
  if (options.signal !== undefined) {
    requestOptions.signal = options.signal;
  }
  return await getJson<SessionPlugSummaryOut>(path, requestOptions);
}

// ---------------------------------------------------------------------------
// Action clients
// ---------------------------------------------------------------------------

/**
 * Record that the user dismissed a plug-length warning (spec §9.3).
 *
 * Idempotent — safe to call multiple times.
 *
 * @throws :class:`ApiError` on non-2xx (422 for unknown
 *   ``warning_type``).
 */
export async function suppressWarning(
  body: { block_hash: string; warning_type: string },
  options: { signal?: AbortSignal } = {},
): Promise<{ status: string }> {
  const requestOptions: RequestOptions = {};
  if (options.signal !== undefined) {
    requestOptions.signal = options.signal;
  }
  return await postJson<{ status: string }>(
    API_ANALYTICS_WARNINGS_SUPPRESS_ENDPOINT,
    body,
    requestOptions,
  );
}
