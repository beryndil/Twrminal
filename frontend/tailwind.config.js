import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
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
        flashRed: {
          '0%, 100%': {
            backgroundColor: 'rgb(127 29 29 / 0.6)',
            color: 'rgb(254 202 202)'
          },
          '50%': {
            backgroundColor: 'rgb(239 68 68 / 0.9)',
            color: 'rgb(255 255 255)'
          }
        }
      },
      animation: {
        'flash-red': 'flashRed 1.2s ease-in-out infinite'
      }
    }
  },
  plugins: [typography]
};
