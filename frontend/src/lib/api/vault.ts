import { jsonFetch } from './core';

/** One row in the vault index. `kind` distinguishes the source
 * bucket — plans under `vault.plan_roots` vs TODOs picked up through
 * `vault.todo_globs`. `slug` is the filename stem; for plans it
 * matches the session slug the plan describes, so the frontend can
 * cross-link on value without a server join. */
export type VaultEntry = {
  path: string;
  kind: 'plan' | 'todo';
  slug: string;
  title: string | null;
  mtime: number;
  size: number;
};

/** Shape of `GET /api/vault/index`. Each bucket is already sorted
 * newest-first server-side — no client re-sort required. */
export type VaultIndex = {
  plans: VaultEntry[];
  todos: VaultEntry[];
};

/** Full body of a single vault doc. `body` is raw markdown; pass
 * through `renderMarkdown()` to get the same `marked + shiki`
 * treatment the Conversation pane uses on chat turns. */
export type VaultDoc = {
  path: string;
  kind: 'plan' | 'todo';
  slug: string;
  title: string | null;
  mtime: number;
  size: number;
  body: string;
};

export type VaultSearchHit = {
  path: string;
  line: number;
  snippet: string;
};

/** Result envelope for `GET /api/vault/search`. `truncated` signals
 * the server hit its hit cap — the UI renders a "narrow your query"
 * hint rather than implying zero remaining matches. */
export type VaultSearchResult = {
  query: string;
  hits: VaultSearchHit[];
  truncated: boolean;
};

export function fetchVaultIndex(
  fetchImpl: typeof fetch = fetch
): Promise<VaultIndex> {
  return jsonFetch<VaultIndex>(fetchImpl, '/api/vault/index');
}

export function fetchVaultDoc(
  path: string,
  fetchImpl: typeof fetch = fetch
): Promise<VaultDoc> {
  const params = new URLSearchParams({ path });
  return jsonFetch<VaultDoc>(fetchImpl, `/api/vault/doc?${params.toString()}`);
}

export function searchVault(
  query: string,
  fetchImpl: typeof fetch = fetch
): Promise<VaultSearchResult> {
  const params = new URLSearchParams({ q: query });
  return jsonFetch<VaultSearchResult>(
    fetchImpl,
    `/api/vault/search?${params.toString()}`
  );
}
