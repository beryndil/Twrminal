/**
 * Tailwind v3 configuration for the Bearings frontend.
 *
 * The three-theme system documented in `docs/behavior/themes.md`
 * (Midnight Glass / Default / Paper Light) is wired via CSS variables
 * exposed in `src/app.css`; this Tailwind config reads them through
 * the `colors.surface`, `colors.fg`, etc. token names so utility
 * classes (`bg-surface-1`, `text-fg-strong`) work across themes
 * without per-theme rebuilds.
 *
 * Item 2.9 (Themes + keyboard shortcuts + context menus) populates
 * the live theme switcher; item 2.1 establishes the token system so
 * components written against it in 2.2-2.10 don't need refactoring.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{html,svelte,ts,js}"],
  theme: {
    extend: {
      colors: {
        // Surfaces — backgrounds, panels, modals.
        surface: {
          0: "rgb(var(--bearings-surface-0) / <alpha-value>)",
          1: "rgb(var(--bearings-surface-1) / <alpha-value>)",
          2: "rgb(var(--bearings-surface-2) / <alpha-value>)",
        },
        // Foregrounds — text + iconography.
        fg: {
          DEFAULT: "rgb(var(--bearings-fg) / <alpha-value>)",
          muted: "rgb(var(--bearings-fg-muted) / <alpha-value>)",
          strong: "rgb(var(--bearings-fg-strong) / <alpha-value>)",
        },
        // Accent — interactive primary, links, focus rings.
        accent: {
          DEFAULT: "rgb(var(--bearings-accent) / <alpha-value>)",
          muted: "rgb(var(--bearings-accent-muted) / <alpha-value>)",
        },
        // Borders + dividers.
        border: "rgb(var(--bearings-border) / <alpha-value>)",
        // Semantic state tokens — theme-aware; light on dark themes, dark on paper-light.
        // Defined per [data-theme] in src/app.css (theme-sweep-004).
        info: "rgb(var(--bearings-accent-info) / <alpha-value>)",
        ok: "rgb(var(--bearings-accent-ok) / <alpha-value>)",
        warn: "rgb(var(--bearings-accent-warn) / <alpha-value>)",
        error: "rgb(var(--bearings-accent-error) / <alpha-value>)",
      },
      fontFamily: {
        // System UI stack; per behavior/themes.md the theme picker
        // does not control fonts.
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
