/**
 * Date/time formatting utilities.
 *
 * :func:`formatAbsolute` — locale-aware absolute datetime formatter that
 * reads the user's display-timezone preference from
 * :data:`displaySettingsStore` (gap-cycle-07-006).  All timestamp surfaces
 * (conversation, sidebar, inspector tabs) should route through this helper
 * so a timezone switch re-renders every visible timestamp in the same tick.
 *
 * :func:`formatBuildMtime` — formats the Unix ``build_mtime`` field from
 * ``GET /api/diag/server`` for the Settings → About identity card.
 */
import { displaySettingsStore } from "../stores/displaySettings.svelte";

/**
 * Format a date value as a locale-aware absolute datetime string,
 * respecting the user's display-timezone preference.
 *
 * When :data:`displaySettingsStore.timezone` is ``null`` ("Auto"), the
 * browser's default timezone applies (``timeZone`` is omitted from the
 * ``Intl.DateTimeFormat`` call).  Otherwise the chosen IANA zone is
 * injected as ``timeZone`` unless the caller already supplies one in
 * ``opts``.
 *
 * Because :data:`displaySettingsStore` is a Svelte 5 ``$state`` object,
 * any ``$derived`` that calls this function re-runs automatically when the
 * timezone changes — no additional subscription or effect needed.
 *
 * @param value - A ``Date``, ISO-8601 string, or Unix timestamp in **ms**.
 * @param opts  - Optional ``Intl.DateTimeFormatOptions``.  A ``timeZone``
 *   supplied here takes precedence over the store value.
 * @returns Formatted datetime string.
 */
export function formatAbsolute(
  value: Date | string | number,
  opts?: Intl.DateTimeFormatOptions,
): string {
  const date = value instanceof Date ? value : new Date(value as string | number);
  const tz = displaySettingsStore.timezone;
  const effectiveOpts: Intl.DateTimeFormatOptions = {
    ...(tz !== null && !opts?.timeZone ? { timeZone: tz } : {}),
    ...opts,
  };
  return date.toLocaleString(undefined, effectiveOpts);
}

/**
 * Format a Unix timestamp (seconds, float) as a human-readable local
 * date-time string for the About section "Build" row.
 *
 * Rules:
 * - ``null`` → ``"dev build"`` (no build token embedded).
 * - Non-finite (``NaN``, ``±Infinity``) → ``"dev build"`` (guard against
 *   corrupt tokens from the server).
 * - Valid finite timestamp → formatted via :func:`formatAbsolute` using
 *   the active display timezone (e.g. ``"Jan 15, 2026, 2:30 PM"``).
 *
 * @param ts - Unix timestamp in seconds, or ``null``.
 * @returns Human-readable build string.
 */
export function formatBuildMtime(ts: number | null): string {
  if (ts === null || !isFinite(ts)) return "dev build";
  return formatAbsolute(ts * 1000);
}
