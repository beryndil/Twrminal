/**
 * Pure sidebar-navigation helpers — wrap-around row selection for `j`/`k`
 * and their `Alt+]`/`Alt+[` variants.
 *
 * Per ``docs/behavior/keyboard-shortcuts.md`` §Navigate (sidebar):
 *
 * - `j` / `Alt+]`: move one row **down**, wrapping at the bottom back to
 *   the top.
 * - `k` / `Alt+[`: move one row **up**, wrapping at the top back to the
 *   bottom.
 * - No current selection (``currentId === null``) → `j` seeds to the
 *   first row; `k` seeds to the last row.
 * - Empty list → both return ``null`` (no-op at the call site).
 *
 * Extracting the wrap math into pure functions keeps ``+layout.svelte``
 * thin and gives vitest a straightforward surface to assert against.
 */
import type { SessionOut } from "../api/sessions";

/**
 * Return the id of the session that ``j`` / ``Alt+]`` should navigate to,
 * or ``null`` when the session list is empty (no navigation should happen).
 *
 * @param sessions - The current visible session list (order matches the
 *   sidebar rendering order — newest first).
 * @param currentId - The id of the currently selected session, or ``null``
 *   when nothing is selected.
 */
export function sidebarNavNext(
  sessions: readonly SessionOut[],
  currentId: string | null,
): string | null {
  if (sessions.length === 0) return null;
  if (currentId === null) return sessions[0].id;
  const idx = sessions.findIndex((s) => s.id === currentId);
  if (idx < 0) return sessions[0].id;
  return sessions[(idx + 1) % sessions.length].id;
}

/**
 * Return the id of the session that ``k`` / ``Alt+[`` should navigate to,
 * or ``null`` when the session list is empty (no navigation should happen).
 *
 * @param sessions - The current visible session list.
 * @param currentId - The id of the currently selected session, or ``null``
 *   when nothing is selected.
 */
export function sidebarNavPrev(
  sessions: readonly SessionOut[],
  currentId: string | null,
): string | null {
  if (sessions.length === 0) return null;
  if (currentId === null) return sessions[sessions.length - 1].id;
  const idx = sessions.findIndex((s) => s.id === currentId);
  if (idx < 0) return sessions[sessions.length - 1].id;
  return sessions[(idx - 1 + sessions.length) % sessions.length].id;
}

/**
 * Return the session id for sidebar slot ``N`` (``Alt+1``..``Alt+9``), where
 * slot numbers are **1-indexed positions in the visible open-session list**.
 *
 * Returns ``null`` when ``slot`` is out of range so the call site can treat
 * it as a no-op. Callers must pass the pre-filtered open-session list
 * (``openSessionsList`` from the sessions store) — this function operates on
 * whatever list it receives and does not perform any closed-session filtering
 * itself.
 *
 * @param sessions - The open sessions list in sidebar display order.
 * @param slot - 1-indexed slot number (1–9).
 */
export function sidebarNavSlot(sessions: readonly SessionOut[], slot: number): string | null {
  if (slot < 1 || slot > sessions.length) return null;
  return sessions[slot - 1].id;
}
