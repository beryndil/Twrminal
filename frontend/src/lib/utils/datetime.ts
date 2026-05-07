/**
 * Date/time formatting utilities (gap-cycle-07-005).
 *
 * Provides :func:`formatBuildMtime` — formats the Unix-timestamp
 * ``build_mtime`` field from ``GET /api/diag/server`` into a
 * human-readable local datetime string for the Settings → About
 * identity card.
 */

/**
 * Format a Unix timestamp (seconds, float) as a human-readable local
 * date-time string for the About section "Build" row.
 *
 * Rules:
 * - ``null`` → ``"dev build"`` (no build token embedded).
 * - Non-finite (``NaN``, ``±Infinity``) → ``"dev build"`` (guard against
 *   corrupt tokens from the server).
 * - Valid finite timestamp → locale date + time string using the browser's
 *   ``Intl.DateTimeFormat`` defaults (e.g. ``"Jan 15, 2026, 2:30 PM"``).
 *
 * @param ts - Unix timestamp in seconds, or ``null``.
 * @returns Human-readable build string.
 */
export function formatBuildMtime(ts: number | null): string {
  if (ts === null || !isFinite(ts)) return "dev build";
  return new Date(ts * 1000).toLocaleString();
}
