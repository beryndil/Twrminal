/**
 * Pending-operations store — card open/close state + the ops list for
 * the active project's ``.bearings/pending.toml``.
 *
 * Per arch §2.2 one canonical store per feature, one file. The card
 * reads the active session's ``working_dir`` from the sessions list,
 * fetches ``.bearings/pending.toml`` via ``GET /api/fs/read``, and
 * parses the TOML into :type:`PendingOp` rows. The store deliberately
 * does NOT subscribe to the inspector store — callers drive
 * :func:`refreshOps` when the active session changes.
 *
 * UI state:
 *
 * - ``open`` — whether the floating card is visible.
 * - ``ops`` — current list of pending ops (empty when none or no
 *   session selected).
 * - ``loading`` — ``true`` while a fetch is in flight.
 * - ``error`` — last fetch error; cleared on success.
 */
import { fetchPendingOps, type PendingOp } from "../api/pendingOps";

export type { PendingOp };

interface PendingState {
  /** Whether the floating card is open. */
  open: boolean;
  /** Current pending ops for the active project. */
  ops: PendingOp[];
  /** ``true`` while a fetch is in flight. */
  loading: boolean;
  /** Last error from a fetch attempt; cleared on success. */
  error: Error | null;
}

const state: PendingState = $state({
  open: false,
  ops: [],
  loading: false,
  error: null,
});

/** Reactive proxy — read fields directly in ``$derived`` / templates. */
export const pendingOpsStore = state;

let refreshController: AbortController | null = null;

// ---- Card visibility --------------------------------------------------------

/** Toggle the floating card open / closed. */
export function toggleCard(): void {
  state.open = !state.open;
}

/** Open the floating card. */
export function openCard(): void {
  state.open = true;
}

/** Close the floating card. */
export function closeCard(): void {
  state.open = false;
}

// ---- Data loading -----------------------------------------------------------

/**
 * Refresh the pending-ops list for ``workingDir``.
 *
 * Cancels any in-flight request so a rapid session-switch doesn't
 * produce a stale update from the previous project.
 *
 * Pass ``null`` / empty string to clear the list without fetching
 * (used when no session is active).
 */
export async function refreshOps(workingDir: string | null): Promise<void> {
  refreshController?.abort();

  if (!workingDir) {
    state.ops = [];
    state.error = null;
    return;
  }

  const controller = new AbortController();
  refreshController = controller;
  state.loading = true;

  try {
    const ops = await fetchPendingOps(workingDir, { signal: controller.signal });
    if (controller.signal.aborted) return;
    state.ops = ops;
    state.error = null;
  } catch (err) {
    if (controller.signal.aborted || isAbortError(err)) return;
    state.error = err instanceof Error ? err : new Error(String(err));
  } finally {
    if (!controller.signal.aborted) {
      state.loading = false;
    }
  }
}

function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === "AbortError";
}

/** Test seam — reset all state. */
export function _resetForTests(): void {
  refreshController?.abort();
  refreshController = null;
  state.open = false;
  state.ops = [];
  state.loading = false;
  state.error = null;
}
