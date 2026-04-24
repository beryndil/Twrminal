import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  fetchVaultDoc,
  fetchVaultIndex,
  searchVault,
  type VaultDoc,
  type VaultIndex,
  type VaultSearchResult
} from './vault';

afterEach(() => {
  vi.restoreAllMocks();
});

type Call = { url: string; init?: RequestInit };

function fakeFetch(body: unknown): { fetch: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const impl = (async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify(body),
      json: async () => body
    };
  }) as unknown as typeof fetch;
  return { fetch: impl, calls };
}

describe('fetchVaultIndex', () => {
  it('hits /api/vault/index and returns the payload', async () => {
    const payload: VaultIndex = {
      plans: [
        {
          path: '/abs/plans/alpha.md',
          kind: 'plan',
          slug: 'alpha',
          title: 'Alpha',
          mtime: 1,
          size: 10
        }
      ],
      todos: []
    };
    const { fetch, calls } = fakeFetch(payload);
    const out = await fetchVaultIndex(fetch);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('/api/vault/index');
    expect(out).toEqual(payload);
  });
});

describe('fetchVaultDoc', () => {
  it('URL-encodes the path query param', async () => {
    const payload: VaultDoc = {
      path: '/abs/plans/alpha with space.md',
      kind: 'plan',
      slug: 'alpha with space',
      title: 'Alpha',
      mtime: 2,
      size: 20,
      body: '# hi'
    };
    const { fetch, calls } = fakeFetch(payload);
    await fetchVaultDoc('/abs/plans/alpha with space.md', fetch);
    // URLSearchParams uses `+` for spaces in values — the backend's
    // FastAPI query parser decodes either `+` or `%20`, so this is the
    // right wire shape. The test pins it so a future codepath swap to
    // `encodeURIComponent` (which would emit `%20`) is a deliberate
    // choice, not an accidental regression.
    expect(calls[0].url).toContain(
      'path=%2Fabs%2Fplans%2Falpha+with+space.md'
    );
  });
});

describe('searchVault', () => {
  it('sends the query as `q` and returns the result envelope', async () => {
    const payload: VaultSearchResult = {
      query: 'fish',
      hits: [{ path: '/abs/plans/alpha.md', line: 3, snippet: 'red fish' }],
      truncated: false
    };
    const { fetch, calls } = fakeFetch(payload);
    const out = await searchVault('fish', fetch);
    expect(calls[0].url).toBe('/api/vault/search?q=fish');
    expect(out).toEqual(payload);
  });

  it('URL-encodes special chars in the query', async () => {
    const payload: VaultSearchResult = {
      query: 'r.d',
      hits: [],
      truncated: false
    };
    const { fetch, calls } = fakeFetch(payload);
    await searchVault('r.d', fetch);
    expect(calls[0].url).toBe('/api/vault/search?q=r.d');
  });
});
