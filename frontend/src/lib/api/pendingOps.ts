/**
 * Typed client for reading ``.bearings/pending.toml`` via
 * ``GET /api/fs/read`` and for firing pending-operation actions
 * (resolve, dismiss) against the backend CLI subprocess surface.
 *
 * Pending operations are stored in the per-project
 * ``.bearings/pending.toml`` file; the backend exposes the raw file
 * text via ``GET /api/fs/read?path=<abs_path>`` under the FS allow-
 * roots. This module reads the TOML, parses it into typed objects, and
 * exposes the resolve / dismiss affordances by shelling out via
 * ``POST /api/shell/exec`` (the same surface used by the CLI surface).
 *
 * The parser handles the subset of TOML written by ``bearings pending
 * add``:
 *
 * ```toml
 * [ops.my-op-name]
 * description = "Short description"
 * started_at  = "2024-01-01T12:00:00Z"
 * command     = "optional shell command"   # optional
 * dir         = "/optional/path"           # optional
 * ```
 *
 * Keys outside that set are silently ignored; malformed value lines
 * are skipped.
 */
import { API_FS_READ_ENDPOINT, pendingDismissEndpoint, pendingResolveEndpoint } from "../config";
import { ApiError, getJson } from "./client";

// ---- Types ------------------------------------------------------------------

/** One row from ``.bearings/pending.toml``. */
export interface PendingOp {
  /** Human-readable name (TOML section key). */
  readonly name: string;
  /** Short description written by ``bearings pending add --description``. */
  readonly description: string;
  /** ISO 8601 timestamp written by the CLI on ``add``. */
  readonly started_at: string;
  /** Optional shell command attached to the operation. */
  readonly command?: string;
  /** Optional directory hint (defaults to the project root). */
  readonly dir?: string;
}

// ---- TOML parsing -----------------------------------------------------------

const STRING_VALUE_RE = /^([\w-]+)\s*=\s*"(.*)"$/;
const OPS_SECTION_RE = /^\[ops\.(.*)\]$/;
const QUOTED_OPS_SECTION_RE = /^\[ops\."(.+)"\]$/;

/**
 * Parse the subset of TOML written by ``bearings pending add``.
 *
 * Returns an array of :type:`PendingOp` sorted oldest-first (by
 * ``started_at`` lexicographically, which works for ISO 8601 strings).
 * Empty content or content with no ``[ops.*]`` sections returns ``[]``.
 */
export function parsePendingToml(content: string): PendingOp[] {
  const ops: PendingOp[] = [];
  let current: {
    name: string;
    description: string;
    started_at: string;
    command?: string;
    dir?: string;
  } | null = null;

  function flush(): void {
    if (current !== null && current.started_at !== "") {
      ops.push({ ...current } as PendingOp);
    }
    current = null;
  }

  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (line === "" || line.startsWith("#")) continue;

    // Section header: [ops.name] or [ops."name with spaces"]
    const quotedMatch = QUOTED_OPS_SECTION_RE.exec(line);
    const bareMatch = quotedMatch === null ? OPS_SECTION_RE.exec(line) : null;
    const sectionName = quotedMatch?.[1] ?? bareMatch?.[1] ?? null;
    if (sectionName !== null) {
      flush();
      current = { name: sectionName, description: "", started_at: "" };
      continue;
    }

    if (current === null) continue;

    // Key-value: key = "value"
    const kv = STRING_VALUE_RE.exec(line);
    if (kv === null) continue;
    const [, key, value] = kv;
    if (key === "description") current.description = value;
    else if (key === "started_at") current.started_at = value;
    else if (key === "command") current.command = value;
    else if (key === "dir") current.dir = value;
  }

  flush();

  // Sort oldest-first by started_at (ISO 8601 lexicographic order works).
  ops.sort((a, b) => a.started_at.localeCompare(b.started_at));
  return ops;
}

// ---- API client -------------------------------------------------------------

interface FsReadOut {
  path: string;
  content: string;
  size: number;
  truncated: boolean;
}

/**
 * Read ``.bearings/pending.toml`` for the given project root and
 * return the parsed ops list.
 *
 * - Returns ``[]`` when the file does not exist (404 from the FS
 *   route is treated as "no pending ops").
 * - Returns ``[]`` when ``allow-roots`` is empty and the backend
 *   returns 403 — a documented empty-state, not an access error.
 * - Propagates other :class:`ApiError` values to the caller.
 */
export async function fetchPendingOps(
  workingDir: string,
  options: { signal?: AbortSignal } = {},
): Promise<PendingOp[]> {
  const path = `${workingDir}/.bearings/pending.toml`;
  let out: FsReadOut;
  try {
    out = await getJson<FsReadOut>(`${API_FS_READ_ENDPOINT}?path=${encodeURIComponent(path)}`, {
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
      // 404 — file does not exist (no pending ops).
      // 403 — allow-roots not configured; treat as empty pending list.
      return [];
    }
    throw err;
  }
  return parsePendingToml(out.content);
}

// ---- Mutation helpers -------------------------------------------------------

/**
 * Fire a pending-op action (POST or DELETE) against a 204-returning
 * endpoint.  Throws :class:`ApiError` on non-2xx.
 */
async function _mutateOp(method: "POST" | "DELETE", url: string): Promise<void> {
  const response = await fetch(url, {
    method,
    headers: { Accept: "application/json" },
  });
  if (response.status >= 200 && response.status < 300) return;
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    try {
      body = await response.text();
    } catch {
      // ignore
    }
  }
  throw new ApiError(
    response.status,
    body,
    `${method} ${url} → ${response.status} ${response.statusText}`,
  );
}

/**
 * Mark a pending operation as resolved.
 *
 * Fires ``POST /api/pending/{name}/resolve?directory=<workingDir>``.
 * Returns when the server confirms the removal (204). Throws
 * :class:`ApiError` on non-2xx (caller is responsible for leaving the
 * row in the UI when an error is thrown).
 */
export async function resolvePendingOp(name: string, workingDir: string): Promise<void> {
  const url = `${pendingResolveEndpoint(name)}?directory=${encodeURIComponent(workingDir)}`;
  await _mutateOp("POST", url);
}

/**
 * Dismiss a pending operation.
 *
 * Fires ``DELETE /api/pending/{name}?directory=<workingDir>``.
 * Returns when the server confirms the removal (204). Throws
 * :class:`ApiError` on non-2xx.
 */
export async function dismissPendingOp(name: string, workingDir: string): Promise<void> {
  const url = `${pendingDismissEndpoint(name)}?directory=${encodeURIComponent(workingDir)}`;
  await _mutateOp("DELETE", url);
}
