/**
 * Bundle-identity probe used by the seamless-reload watcher.
 *
 * Pairs with `routes_health.version` on the backend. The shape carries
 * a release string and a build token; the watcher pins the build on
 * boot and watches for changes (poll + WS-handshake later) so a fresh
 * frontend bundle reaches the user without a forced reload.
 *
 * `build` is `null` when the API is running but the static bundle
 * directory is absent (developer workflow). The watcher tolerates
 * `null` and skips the reload arming on the dev path.
 */

import { jsonFetch } from './core';

export type VersionInfo = {
  version: string;
  build: string | null;
};

export function fetchVersion(fetchImpl: typeof fetch = fetch): Promise<VersionInfo> {
  return jsonFetch<VersionInfo>(fetchImpl, '/api/version');
}
