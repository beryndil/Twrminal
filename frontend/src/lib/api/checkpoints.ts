/**
 * Typed client for the checkpoints REST surface (G6;
 * ``src/bearings/web/routes/checkpoints.py``).
 *
 * Mirrors :class:`bearings.web.models.checkpoints.CheckpointOut` /
 * :class:`bearings.web.models.checkpoints.CheckpointIn` /
 * :class:`bearings.web.models.checkpoints.CheckpointForkResult` field
 * for field. The conversation pane fetches the per-session list on
 * mount (and re-fetches after a create / delete / fork) to refresh the
 * gutter chips.
 */
import { API_CHECKPOINTS_ENDPOINT, checkpointEndpoint, checkpointForkEndpoint } from "../config";
import { deleteResource, getJson, postJson, type RequestOptions } from "./client";

/** Wire shape — one-to-one with :class:`bearings.web.models.checkpoints.CheckpointOut`. */
export interface CheckpointOut {
  id: string;
  session_id: string;
  message_id: string;
  label: string;
  created_at: string;
}

/**
 * Wire envelope for ``POST /api/checkpoints/{id}/fork``. Consumed via
 * the ``forkCheckpoint`` return type — not exported because no caller
 * imports the type independently of the function (knip gate).
 */
interface CheckpointForkResult {
  new_session_id: string;
  source_session_id: string;
  checkpoint_id: string;
  message_count: number;
}

interface CreateCheckpointParams {
  sessionId: string;
  messageId: string;
  /** Omit to let the server synthesise a default label. */
  label?: string;
}

/**
 * Create a checkpoint at ``messageId``. Returns the new row.
 *
 * The ``label`` is optional — when omitted the route synthesises one
 * from :data:`bearings.config.constants.DEFAULT_CHECKPOINT_LABEL_TEMPLATE`.
 */
export async function createCheckpoint(
  params: CreateCheckpointParams,
  options: RequestOptions = {},
): Promise<CheckpointOut> {
  const body: Record<string, string> = {
    session_id: params.sessionId,
    message_id: params.messageId,
  };
  if (params.label !== undefined && params.label.length > 0) {
    body.label = params.label;
  }
  return await postJson<CheckpointOut>(API_CHECKPOINTS_ENDPOINT, body, options);
}

/**
 * List every checkpoint for ``sessionId``, newest-first. Returns ``[]``
 * for an unknown / empty session — the gutter renders nothing in
 * either case.
 */
export async function listCheckpoints(
  sessionId: string,
  options: RequestOptions = {},
): Promise<CheckpointOut[]> {
  return await getJson<CheckpointOut[]>(API_CHECKPOINTS_ENDPOINT, {
    ...options,
    query: [["session_id", sessionId]],
  });
}

/**
 * Delete one checkpoint. 204 No Content on success; 404 from the server
 * surfaces as :class:`ApiError`.
 */
export async function deleteCheckpoint(
  checkpointId: string,
  options: RequestOptions = {},
): Promise<void> {
  return await deleteResource<void>(checkpointEndpoint(checkpointId), options);
}

/**
 * Fork the source session at ``checkpointId``. Returns the new
 * session id + the count of copied messages so the caller can navigate
 * to the new session.
 */
export async function forkCheckpoint(
  checkpointId: string,
  options: RequestOptions = {},
): Promise<CheckpointForkResult> {
  return await postJson<CheckpointForkResult>(checkpointForkEndpoint(checkpointId), {}, options);
}
