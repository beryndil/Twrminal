import { jsonFetch, voidFetch } from './core';

/** Which "axis" of filtering a tag belongs to. `general` is the
 * user-facing project/area tag system (what most tags are).
 * `severity` is the seeded severity ladder from migration 0021:
 * Blocker / Critical / Medium / Low / Quality of Life. Every session
 * carries exactly one severity; see `ensure_default_severity` on the
 * backend. Added in v0.2.14. */
export type TagGroup = 'general' | 'severity';

export type Tag = {
  id: number;
  name: string;
  color: string | null;
  pinned: boolean;
  sort_order: number;
  created_at: string;
  session_count: number;
  /** Open-only partition of `session_count` (sessions whose `closed_at`
   * is null). Rendered in green to the left of the total on the
   * sidebar so live work is distinguishable from archived at a glance. */
  open_session_count: number;
  default_working_dir: string | null;
  default_model: string | null;
  tag_group: TagGroup;
};

export type TagCreate = {
  name: string;
  color?: string | null;
  pinned?: boolean;
  sort_order?: number;
  default_working_dir?: string | null;
  default_model?: string | null;
  tag_group?: TagGroup;
};

export type TagUpdate = {
  name?: string;
  color?: string | null;
  pinned?: boolean;
  sort_order?: number;
  default_working_dir?: string | null;
  default_model?: string | null;
  tag_group?: TagGroup;
};

export type TagMemory = {
  tag_id: number;
  content: string;
  updated_at: string;
};

export function listTags(fetchImpl: typeof fetch = fetch): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, '/api/tags');
}

export function listSessionTags(
  sessionId: string,
  fetchImpl: typeof fetch = fetch
): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, `/api/sessions/${sessionId}/tags`);
}

export function createTag(
  body: TagCreate,
  fetchImpl: typeof fetch = fetch
): Promise<Tag> {
  return jsonFetch<Tag>(fetchImpl, '/api/tags', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export function updateTag(
  id: number,
  patch: TagUpdate,
  fetchImpl: typeof fetch = fetch
): Promise<Tag> {
  return jsonFetch<Tag>(fetchImpl, `/api/tags/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch)
  });
}

export function deleteTag(
  id: number,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  return voidFetch(fetchImpl, `/api/tags/${id}`, { method: 'DELETE' });
}

export function getTagMemory(
  tagId: number,
  fetchImpl: typeof fetch = fetch
): Promise<TagMemory> {
  return jsonFetch<TagMemory>(fetchImpl, `/api/tags/${tagId}/memory`);
}

export function putTagMemory(
  tagId: number,
  content: string,
  fetchImpl: typeof fetch = fetch
): Promise<TagMemory> {
  return jsonFetch<TagMemory>(fetchImpl, `/api/tags/${tagId}/memory`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ content })
  });
}

export function deleteTagMemory(
  tagId: number,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  return voidFetch(fetchImpl, `/api/tags/${tagId}/memory`, { method: 'DELETE' });
}

export function attachSessionTag(
  sessionId: string,
  tagId: number,
  fetchImpl: typeof fetch = fetch
): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, `/api/sessions/${sessionId}/tags/${tagId}`, {
    method: 'POST'
  });
}

export function detachSessionTag(
  sessionId: string,
  tagId: number,
  fetchImpl: typeof fetch = fetch
): Promise<Tag[]> {
  return jsonFetch<Tag[]>(fetchImpl, `/api/sessions/${sessionId}/tags/${tagId}`, {
    method: 'DELETE'
  });
}
