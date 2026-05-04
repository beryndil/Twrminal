/**
 * Typed client for ``GET /api/tags`` and ``GET /api/sessions/{id}/tags``.
 *
 * Mirrors :class:`bearings.web.models.tags.TagOut`. Per
 * ``docs/behavior/chat.md`` the user observes tag chips on every
 * session row; the sidebar reads the per-session list to render those
 * chips and the global list to populate the filter panel.
 */
import { API_TAGS_ENDPOINT, sessionTagsEndpoint } from "../config";
import {
  ApiError,
  deleteResource,
  getJson,
  patchJson,
  postJson,
  type RequestOptions,
} from "./client";

/**
 * Wire shape for one tag — one-to-one with
 * :class:`bearings.web.models.tags.TagOut`. The ``group`` field is
 * derived on the backend (slash-prefix of ``name``) and round-tripped
 * here so the filter-panel UI doesn't have to reparse names.
 */
export interface TagOut {
  id: number;
  name: string;
  color: string | null;
  default_model: string | null;
  working_dir: string | null;
  group: string | null;
  created_at: string;
  updated_at: string;
}

interface ListTagsParams {
  /** Optional group prefix; matches via the backend's ``LIKE "<group>/%"``. */
  group?: string;
  signal?: AbortSignal;
}

export async function listTags(params: ListTagsParams = {}): Promise<TagOut[]> {
  const options: RequestOptions = {};
  if (params.group !== undefined) {
    options.query = [["group", params.group]];
  }
  if (params.signal !== undefined) {
    options.signal = params.signal;
  }
  return await getJson<TagOut[]>(API_TAGS_ENDPOINT, options);
}

export async function listSessionTags(
  sessionId: string,
  params: { signal?: AbortSignal } = {},
): Promise<TagOut[]> {
  const options: RequestOptions = {};
  if (params.signal !== undefined) {
    options.signal = params.signal;
  }
  return await getJson<TagOut[]>(sessionTagsEndpoint(sessionId), options);
}

/**
 * Wire shape for ``POST /api/tags`` + ``PATCH /api/tags/{id}`` —
 * one-to-one with :class:`bearings.web.models.tags.TagIn`. ``color``
 * accepts any string the server's hex / palette validator allows;
 * ``working_dir`` must be non-empty when supplied (the backend
 * enforces ``min_length=1``).
 */
export interface TagInput {
  name: string;
  color?: string | null;
  default_model?: string | null;
  working_dir?: string | null;
}

/**
 * Create a tag via ``POST /api/tags``. 201 on success; 409 if the
 * name is already taken (the caller should surface that to the user
 * inline rather than as a generic failure).
 */
export async function createTag(body: TagInput, options: RequestOptions = {}): Promise<TagOut> {
  return await postJson<TagOut>(API_TAGS_ENDPOINT, body, options);
}

/**
 * Update a tag via ``PATCH /api/tags/{id}``. The PATCH replaces the
 * mutable field set wholesale per the backend contract — callers send
 * the full :class:`TagInput` payload, not a partial.
 */
export async function updateTag(
  tagId: number,
  body: TagInput,
  options: RequestOptions = {},
): Promise<TagOut> {
  return await patchJson<TagOut>(`${API_TAGS_ENDPOINT}/${tagId}`, body, options);
}

/**
 * Delete a tag via ``DELETE /api/tags/{id}``. The cascade clears
 * ``session_tags`` and ``tag_memories`` rows referencing the tag.
 */
export async function deleteTag(tagId: number, options: RequestOptions = {}): Promise<void> {
  await deleteResource<void>(`${API_TAGS_ENDPOINT}/${tagId}`, options);
}

/**
 * Attach a tag to a session via ``PUT /api/sessions/{sessionId}/tags/{tagId}``.
 * Idempotent — attaching an already-attached tag returns 200.
 */
export async function attachTagToSession(
  sessionId: string,
  tagId: number,
  options: RequestOptions = {},
): Promise<TagOut> {
  const path = `${sessionTagsEndpoint(sessionId)}/${tagId}`;
  const response = await fetch(path, {
    method: "PUT",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  if (response.status < 200 || response.status >= 300) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, body, `PUT ${path} → ${response.status}`);
  }
  return (await response.json()) as TagOut;
}

/**
 * Detach a tag from a session via ``DELETE /api/sessions/{sessionId}/tags/{tagId}``.
 */
export async function detachTagFromSession(
  sessionId: string,
  tagId: number,
  options: RequestOptions = {},
): Promise<void> {
  const path = `${sessionTagsEndpoint(sessionId)}/${tagId}`;
  await deleteResource<void>(path, options);
}
