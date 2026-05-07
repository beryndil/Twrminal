/**
 * No-flash theme boot — synchronous cold-load logic extracted as a
 * testable module.
 *
 * :file:`src/app.html` embeds an inline IIFE that mirrors
 * :func:`runBootScript` verbatim (without ES imports) so it executes
 * *before* SvelteKit head injection and any stylesheet paint, giving
 * users their persisted theme on frame 1. This module exists so the
 * same behavior is verifiable via vitest without a real browser.
 *
 * Behavior anchors:
 *
 * - ``docs/behavior/themes.md`` §"What gets re-themed live" — the boot
 *   script paints ``data-theme`` and ``<meta name="theme-color">`` on
 *   frame 1; the runtime corrects any single-frame drift on the next
 *   tick.
 * - §"Failure modes" §"Drift between boot script and runtime" — the
 *   runtime drift detector in
 *   :file:`src/lib/themes/ThemeProvider.svelte` ``console.warn``s when
 *   the meta-color written here disagrees with ``THEME_COLOR_HEX`` in
 *   :file:`src/lib/config.ts`.
 */

/**
 * localStorage key — literal so the inline IIFE in
 * :file:`src/app.html` can match it without an import. Must stay in
 * sync with ``THEME_STORAGE_KEY`` in :file:`src/lib/config.ts`.
 */
export const BOOT_STORAGE_KEY = "bearings-theme-v1";

/**
 * Theme → address-bar hex map — an inline literal that mirrors
 * ``THEME_COLOR_HEX`` in :file:`src/lib/config.ts` exactly. The
 * runtime drift detector ``console.warn``s on cold load if the two
 * maps disagree (the meta-color the boot script wrote differs from what
 * the runtime computes).
 *
 * Values are the ``--bearings-surface-0`` tuples rendered as
 * ``#rrggbb``; see :file:`src/app.css`.
 */
export const BOOT_THEME_HEX: Readonly<Record<string, string>> = {
  evergreen: "#0e131b",
  "midnight-glass": "#0e1729",
  default: "#111827",
  "paper-light": "#faf7f0",
} as const;

/** Fallback theme id — matches the static ``data-theme`` in app.html. */
export const BOOT_FALLBACK_THEME = "evergreen";

/** Fallback hex — matches the static ``<meta name="theme-color">`` in app.html. */
export const BOOT_FALLBACK_HEX = "#0e131b";

/**
 * Run the no-flash boot script against ``win`` + ``doc``.
 *
 * Steps executed synchronously:
 *
 * 1. Try to read :data:`BOOT_STORAGE_KEY` from ``win.localStorage``.
 * 2. If the stored value is a key in :data:`BOOT_THEME_HEX`, use it.
 * 3. If absent (first visit), try the OS color-scheme fallback.
 * 4. If the stored value is unknown (removed theme), stay on the
 *    evergreen fallback.
 * 5. Write ``data-theme`` on ``doc.documentElement``.
 * 6. Set (or create) ``<meta name="theme-color">`` to the matching hex.
 *
 * Every read is ``try/catch``-guarded. Any failure leaves the static
 * ``data-theme="evergreen"`` and meta-color already on the HTML element
 * unchanged — the page is always usable.
 *
 * Called without arguments from the inline IIFE in
 * :file:`src/app.html`; called with mock window/document from vitest.
 */
export function runBootScript(
  win: Window & typeof globalThis = window,
  doc: Document = document,
): void {
  try {
    let theme = BOOT_FALLBACK_THEME;
    let hex = BOOT_FALLBACK_HEX;

    try {
      const stored = win.localStorage.getItem(BOOT_STORAGE_KEY);
      if (stored !== null && Object.prototype.hasOwnProperty.call(BOOT_THEME_HEX, stored)) {
        // Valid persisted choice.
        theme = stored;
        hex = BOOT_THEME_HEX[stored] ?? BOOT_FALLBACK_HEX;
      } else if (stored === null) {
        // No persisted choice — resolve OS color-scheme fallback.
        try {
          if (win.matchMedia("(prefers-color-scheme: light)").matches) {
            theme = "paper-light";
            hex = BOOT_THEME_HEX["paper-light"] ?? BOOT_FALLBACK_HEX;
          }
          // Dark or unset OS scheme → already at evergreen fallback.
        } catch {
          // matchMedia unavailable (e.g. SSR shim) — stay on evergreen.
        }
      }
      // Unknown stored value (removed theme) → stay on evergreen fallback.
    } catch {
      // localStorage inaccessible (private mode / quota) — stay on evergreen.
    }

    doc.documentElement.setAttribute("data-theme", theme);

    let meta = doc.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (meta === null) {
      meta = doc.createElement("meta");
      meta.setAttribute("name", "theme-color");
      doc.head.appendChild(meta);
    }
    meta.setAttribute("content", hex);
  } catch {
    // Absolute last resort — the static HTML already has the right
    // data-theme="evergreen" attribute and meta-color on the element.
  }
}
