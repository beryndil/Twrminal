/**
 * Typed client for the tag-memory CRUD surface (item 1.4;
 * ``src/bearings/web/routes/memories.py``).
 *
 * Memories are user-authored, tag-scoped system-prompt fragments per
 * arch §1.1.3. Unlike the read-only vault (see ``api/vault.ts``)
 * memories ARE editable — this module surfaces full create / read /
 * update / delete helpers.
 *
 * Wire shapes mirror :class:`bearings.web.models.tags.TagMemoryIn` /
 * :class:`TagMemoryOut`; ``extra="forbid"`` on the backend means a
 * stray TS field surfaces as a 422 at the wire boundary.
 */
import { API_ALL_MEMORIES_ENDPOINT, memoryEndpoint, tagMemoriesEndpoint } from "../config";
import { deleteResource, getJson, patchJson, postJson, type RequestOptions } from "./client";

/**
 * Wire shape for one memory — one-to-one with
 * :class:`bearings.web.models.tags.TagMemoryOut`.
 *
 * ``enabled`` flips visibility to the prompt assembler without
 * deleting the row (so a user can ramp a memory back up later); the
 * backend list endpoint accepts ``?only_enabled=true`` for the
 * prompt-assembler consumer.
 */
export interface TagMemoryOut {
  id: number;
  tag_id: number;
  title: string;
  body: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Request body shared by POST + PATCH — mirrors
 * :class:`bearings.web.models.tags.TagMemoryIn`. Validation rules:
 *
 * * ``title`` — 1 to :const:`TAG_MEMORY_TITLE_MAX_LENGTH` chars.
 * * ``body`` — 1 to :const:`TAG_MEMORY_BODY_MAX_LENGTH` chars.
 * * ``enabled`` — defaults true on create; PATCH must specify.
 *
 * The frontend editor enforces the same rules client-side so a
 * 422 is unreachable through the form path; the server-side
 * checks remain authoritative.
 */
export interface TagMemoryIn {
  title: string;
  body: string;
  enabled: boolean;
}

/**
 * Wire shape for one row in the global memories index — mirrors
 * :class:`bearings.web.models.tags.AllMemoriesOut`.
 *
 * ``memory_body_preview`` is the body truncated server-side to
 * :const:`MEMORY_BODY_PREVIEW_MAX_LENGTH` chars; the full body is
 * available via :func:`getMemory`.
 *
 * The list is sorted by ``(tag_name, memory_title)`` so grouping by
 * tag emerges from the sort order.
 */
export interface AllMemoriesRow {
  tag_id: number;
  tag_name: string;
  tag_color: string | null;
  memory_id: number;
  memory_title: string;
  memory_body_preview: string;
  enabled: boolean;
  updated_at: string;
}

/**
 * ``GET /api/memories`` — every memory across all tags.
 *
 * Returns the flat list sorted by tag name then memory title. Pass
 * ``onlyEnabled: true`` to restrict to enabled memories (mirrors the
 * ``?only_enabled=true`` query param on the per-tag list endpoint).
 */
export async function listAllMemories(
  options: RequestOptions = {},
): Promise<AllMemoriesRow[]> {
  return await getJson<AllMemoriesRow[]>(API_ALL_MEMORIES_ENDPOINT, options);
}

/**
 * ``GET /api/tags/{tag_id}/memories`` — every memory under one tag.
 * Returns empty list (not 404) for tags with no memories yet. 404
 * when the tag itself does not exist.
 */
export async function listTagMemories(
  tagId: number,
  options: RequestOptions = {},
): Promise<TagMemoryOut[]> {
  return await getJson<TagMemoryOut[]>(tagMemoriesEndpoint(tagId), options);
}

/** ``GET /api/memories/{id}`` — fetch one memory by direct id. */
export async function getMemory(
  memoryId: number,
  options: RequestOptions = {},
): Promise<TagMemoryOut> {
  return await getJson<TagMemoryOut>(memoryEndpoint(memoryId), options);
}

/** ``POST /api/tags/{tag_id}/memories`` — create a memory under ``tag_id``. */
export async function createMemory(
  tagId: number,
  body: TagMemoryIn,
  options: RequestOptions = {},
): Promise<TagMemoryOut> {
  return await postJson<TagMemoryOut>(tagMemoriesEndpoint(tagId), body, options);
}

/** ``PATCH /api/memories/{id}`` — replace mutable fields. */
export async function updateMemory(
  memoryId: number,
  body: TagMemoryIn,
  options: RequestOptions = {},
): Promise<TagMemoryOut> {
  return await patchJson<TagMemoryOut>(memoryEndpoint(memoryId), body, options);
}

/** ``DELETE /api/memories/{id}`` — delete a memory. 204 on success. */
export async function deleteMemory(memoryId: number, options: RequestOptions = {}): Promise<void> {
  await deleteResource<void>(memoryEndpoint(memoryId), options);
}
