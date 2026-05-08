/**
 * Version-watcher store (gap-cycle-01-018).
 *
 * Polls ``GET /api/diag/server`` every
 * :data:`STATUS_BAR_VERSION_POLL_INTERVAL_MS` and exposes the result as
 * a reactive ``$state`` object so the status bar re-renders when the
 * server version changes (e.g. after a hot-reload restart).
 *
 * The initial fetch fires immediately on first import so the status bar
 * shows a real version string as early as possible. On fetch failure the
 * current value is left unchanged; on the very first failure the version
 * stays at the loading placeholder.
 *
 * Behavior anchor: ``docs/behavior/chat.md`` §"App chrome" "Status strip".
 */
import { getJson } from "../api/client";
import {
  API_DIAG_SERVER_ENDPOINT,
  STATUS_BAR_VERSION_POLL_INTERVAL_MS,
  STATUS_BAR_STRINGS,
} from "../config";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Subset of ``ServerDiagOut`` that the version watcher reads. */
interface DiagServerOut {
  version: string;
}

// ---------------------------------------------------------------------------
// Reactive state
// ---------------------------------------------------------------------------

interface VersionWatcherStore {
  /** Current Bearings server version string, or the loading placeholder. */
  version: string;
}

const _store: VersionWatcherStore = $state({ version: STATUS_BAR_STRINGS.versionLoading });

/** Read-only reactive view of the version watcher state. */
export const versionWatcherStore: VersionWatcherStore = _store;

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

/**
 * Fetch the server version once and update the store. Errors are
 * swallowed — a failed refresh leaves the displayed version unchanged
 * rather than crashing the status bar.
 */
async function refreshVersion(): Promise<void> {
  try {
    const diag = await getJson<DiagServerOut>(API_DIAG_SERVER_ENDPOINT);
    _store.version = diag.version;
  } catch {
    // Silently retain the current value on network / server error.
  }
}

// Kick off the first fetch immediately.
void refreshVersion();

// Schedule subsequent polls on the configured interval.
let _pollInterval: ReturnType<typeof setInterval> | null = setInterval(
  () => void refreshVersion(),
  STATUS_BAR_VERSION_POLL_INTERVAL_MS,
);

// ---------------------------------------------------------------------------
// Test helpers (not part of the public API)
// ---------------------------------------------------------------------------

/**
 * Override the displayed version for unit tests. Call before rendering
 * the component under test.
 *
 * @internal
 */
export function _setVersionForTests(version: string): void {
  _store.version = version;
}

/**
 * Reset the version to the loading placeholder and cancel any in-flight
 * interval timer so fake-timer tests start from a clean state.
 *
 * **Must be called in ``afterEach``** when fake timers are active —
 * otherwise the setInterval callback queued by this module fires during
 * the next test's fake-clock advance and pollutes that test's fetch mocks.
 *
 * @internal
 */
export function _resetVersionWatcherForTests(): void {
  _store.version = STATUS_BAR_STRINGS.versionLoading;
  if (_pollInterval !== null) {
    clearInterval(_pollInterval);
    _pollInterval = null;
  }
}

/**
 * Re-arm the poll interval after :func:`_resetVersionWatcherForTests`
 * has torn it down (used by tests that exercise the tick behaviour).
 *
 * @internal
 */
export function _startVersionPollForTests(): void {
  if (_pollInterval !== null) clearInterval(_pollInterval);
  _pollInterval = setInterval(() => void refreshVersion(), STATUS_BAR_VERSION_POLL_INTERVAL_MS);
}
