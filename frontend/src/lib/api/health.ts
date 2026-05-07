/**
 * Typed client for ``GET /api/health`` — the server liveness + readiness
 * snapshot. Used by the Settings Privacy section to display the resolved
 * data-directory path (gap-cycle-07-003).
 *
 * The endpoint is always 200 when the server is alive; the JSON body
 * carries the deeper readiness signal (``db_ok``, ``status``). The
 * ``data_dir`` field (added in gap-cycle-07-003) is the absolute path to
 * the Bearings data directory as resolved by the server at startup —
 * typically ``~/.local/share/bearings-v1/``.
 *
 * Throws :class:`ApiError` on network failure so callers can surface an
 * inline error.
 */
import { API_HEALTH_ENDPOINT } from "../config";
import { getJson } from "./client";

// ---- Wire shape -------------------------------------------------------------

export interface HealthOut {
  readonly status: string;
  readonly version: string;
  readonly uptime_s: number;
  readonly db_ok: boolean;
  readonly data_dir: string;
}

// ---- Public API -------------------------------------------------------------

/**
 * Fetch the health snapshot from ``GET /api/health``.
 *
 * Throws :class:`ApiError` on a non-2xx response so the Settings Privacy
 * section can render an inline error rather than silently showing an
 * empty path.
 */
export async function getHealth(): Promise<HealthOut> {
  return getJson<HealthOut>(API_HEALTH_ENDPOINT);
}

export type { HealthOut as HealthResponse };
