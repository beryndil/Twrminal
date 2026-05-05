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
 * Tag class alphabet — partitions the tag set into project / severity
 * / general buckets the filter panel renders as separate sections.
 * Mirrors :data:`bearings.config.constants.KNOWN_TAG_CLASSES`.
 */
export type TagClass = "project" | "severity" | "general";

export const TAG_CLASS_PROJECT: TagClass = "project";
export const TAG_CLASS_SEVERITY: TagClass = "severity";

/**
 * Wire shape for one tag — one-to-one with
 * :class:`bearings.web.models.tags.TagOut`. The ``class_`` field
 * partitions the tag into project / severity / general (drives the
 * three filter sections); ``sort_order`` is the per-class display
 * order (drag-reorder updates this via
 * :func:`updateTagSortOrder`).
 *
 * The ``group`` field is the deprecated slash-prefix carrier
 * (parsed from ``name`` on the backend); retained for back-compat
 * with v0.18.x consumers and dropped in a future release.
 */
export interface TagOut {
  id: number;
  name: string;
  color: string | null;
  default_model: string | null;
  working_dir: string | null;
  pinned: boolean;
  class_: TagClass;
  sort_order: number;
  group: string | null;
  created_at: string;
  updated_at: string;
}

interface ListTagsParams {
  /** Optional class filter — `project` / `severity` / `general`. */
  class_?: TagClass;
  /**
   * Optional group prefix — deprecated slash-namespace filter,
   * retained for back-compat. Prefer ``class_`` for new callers.
   */
  group?: string;
  signal?: AbortSignal;
}

export async function listTags(params: ListTagsParams = {}): Promise<TagOut[]> {
  const options: RequestOptions = {};
  const query: [string, string][] = [];
  if (params.class_ !== undefined) {
    query.push(["class_", params.class_]);
  }
  if (params.group !== undefined) {
    query.push(["group", params.group]);
  }
  if (query.length > 0) {
    options.query = query;
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
 * enforces ``min_length=1``). ``class_`` defaults to ``"general"``
 * server-side when omitted; ``sort_order`` defaults to ``0``.
 *
 * Severity-class tags must leave ``default_model`` /
 * ``working_dir`` null — the server returns 422 otherwise.
 */
export interface TagInput {
  name: string;
  color?: string | null;
  default_model?: string | null;
  working_dir?: string | null;
  class_?: TagClass;
  sort_order?: number;
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
 * Pin or unpin a tag via ``PATCH /api/tags/{id}/pinned``.
 * ``pinned=true`` pins the tag in the sidebar filter panel;
 * ``pinned=false`` unpins it.
 */
export async function patchTagPinned(
  tagId: number,
  pinned: boolean,
  options: RequestOptions = {},
): Promise<TagOut> {
  return await patchJson<TagOut>(`${API_TAGS_ENDPOINT}/${tagId}/pinned`, { pinned }, options);
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

/**
 * Re-sequence ``sort_order`` within ``class_`` to match
 * ``orderedIds`` via ``PUT /api/tags/sort-order``. The drag-reorder
 * UI on the ``/tags`` page calls this; each id at index ``i`` gets
 * ``sort_order = i``. Empty list is a no-op (still returns 204).
 *
 * 422 if any id is missing or belongs to a different class — the
 * caller should refetch the tag list and retry.
 */
export async function updateTagSortOrder(
  klass: TagClass,
  orderedIds: readonly number[],
  options: RequestOptions = {},
): Promise<void> {
  const path = `${API_TAGS_ENDPOINT}/sort-order`;
  const body = { class_: klass, ordered_ids: [...orderedIds] };
  const response = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    signal: options.signal,
  });
  if (response.status < 200 || response.status >= 300) {
    const errBody: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, errBody, `PUT ${path} → ${response.status}`);
  }
}
