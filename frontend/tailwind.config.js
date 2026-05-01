import typography from '@tailwindcss/typography';

// Build a color scale whose shades resolve through the Bearings theme
// tokens declared in `src/lib/themes/tokens.css`. Each entry expands to
// `rgb(var(--bearings-<family>-<shade>) / <alpha-value>)` so Tailwind's
// `/80`, `/60`, etc. opacity modifiers keep working — the channel triple
// flips when `[data-theme]` on <html> flips, nothing else changes.
//
// Only the shades actually used in the codebase are mapped (audited via
// grep). Unmapped shades fall through to Tailwind's defaults, which is
// fine for colors we don't intentionally theme.
const themed = (family, shades) =>
  Object.fromEntries(shades.map((s) => [s, `rgb(var(--bearings-${family}-${s}) / <alpha-value>)`]));

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        slate: themed('slate', [
          '50',
          '100',
          '200',
          '300',
          '400',
          '500',
          '600',
          '700',
          '800',
          '900',
          '950',
        ]),
        sky: themed('sky', ['200', '300', '400', '500', '600', '800', '900']),
        emerald: themed('emerald', ['200', '300', '400', '500', '600', '700', '900']),
        amber: themed('amber', ['100', '200', '300', '400', '500', '800', '900', '950']),
        rose: themed('rose', ['200', '300', '400', '500', '600', '700', '800', '900', '950']),
        red: themed('red', ['100', '500', '600', '900']),
        orange: themed('orange', ['100', '600', '900']),
        teal: themed('teal', ['300', '900']),
        indigo: themed('indigo', ['300', '500', '900']),
        // Semantic brand-affordance alias. Each theme rewires
        // `--color-accent-brand` (and its soft companion) to its own
        // primary hue so non-evergreen themes don't inherit
        // evergreen's emerald in chrome surfaces (active nav, primary
        // buttons, brand glyph). See `lib/themes/tokens.css` and
        // each theme's variable block for the per-theme target.
        'accent-brand': 'rgb(var(--color-accent-brand) / <alpha-value>)',
        'accent-brand-soft': 'rgb(var(--color-accent-brand-soft) / <alpha-value>)',
      },
      // `flash-red` is used by ContextMeter when the current context window
      // crosses the empirical 32K-token recall-degradation threshold. The
      // floor state matches the existing ≥90% red band (red-900/60 bg,
      // red-100 fg) so the animation reads as "same pill, pulsing" rather
      // than "new element appeared"; the peak brightens to red-500/90 on
      // white for a hard blink that's hard to miss in peripheral vision.
      //
      // Duration 1.2s is deliberate: fast enough to feel urgent, slow
      // enough not to trigger photosensitive-seizure guidance (≥3 Hz is
      // the WCAG 2.1 danger zone; we run at ~0.83 Hz).
      //
      // Callers should prefer `motion-safe:animate-flash-red` so users
      // with prefers-reduced-motion get the solid red band without the
      // pulse.
      keyframes: {
        // Pull through the same theme tokens the ContextMeter rest-state
        // uses (`bg-red-900/60`, `text-red-100`, peak `bg-red-500/90`) so
        // the pulse stays in the active theme's red family. Hardcoded
        // rgb() literals would desync from the Midnight Glass red-500
        // (#F85149) vs. the Tailwind-default red-500 (#EF4444).
        flashRed: {
          '0%, 100%': {
            backgroundColor: 'rgb(var(--bearings-red-900) / 0.6)',
            color: 'rgb(var(--bearings-red-100))',
          },
          '50%': {
            backgroundColor: 'rgb(var(--bearings-red-500) / 0.9)',
            color: 'rgb(255 255 255)',
          },
        },
      },
      animation: {
        'flash-red': 'flashRed 1.2s ease-in-out infinite',
      },
    },
  },
  plugins: [typography],
};
