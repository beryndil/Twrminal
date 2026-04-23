<script lang="ts">
  /**
   * Bearings logo mark — the project's permanent brand element and its
   * loading indicator, in a single component.
   *
   * Visual design mirrors the static `/icon.svg` compass: three
   * concentric rings + center dot + eight cardinal/diagonal markers.
   * The rings and center stay put; the eight markers sweep around the
   * center as a single group when `spin` is true. This is intentional —
   * the same mark sits in the app chrome as identity at rest and
   * activates when work is happening, so loading states feel like the
   * logo coming alive rather than a separate "spinner widget."
   *
   * `prefers-reduced-motion: reduce` swaps the rotation for a gentle
   * opacity pulse so spinning mode still communicates "working…"
   * without motion.
   *
   * Strokes/fills use `currentColor` so the mark inherits the
   * surrounding text color — drop it into a slate-500 line of text and
   * it tints to match. Override per-use with Tailwind's text-* classes
   * (sky-400 is the default Bearings blue, applied via `color:` in the
   * component style and overridable from the caller).
   *
   * Size defaults to 20px to sit cleanly inline next to small UI text.
   * Bump the `size` prop for overlay use (file-upload overlay etc).
   */
  interface Props {
    /** Square width/height in px. */
    size?: number;
    /** Animate the eight markers sweeping around the center. */
    spin?: boolean;
    /** Show the dark rounded background (matches the static favicon). */
    showBackground?: boolean;
    /** Extra classes for tinting / spacing from the caller. */
    class?: string;
    /** Accessible label. Omitted → treated as decorative. */
    label?: string;
  }

  let {
    size = 20,
    spin = false,
    showBackground = false,
    class: klass = '',
    label
  }: Props = $props();
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  viewBox="0 0 512 512"
  width={size}
  height={size}
  class="bearings-mark {klass}"
  class:is-spinning={spin}
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
  data-testid="bearings-mark"
  data-spinning={spin ? 'true' : 'false'}
>
  {#if label}
    <title>{label}</title>
  {/if}
  {#if showBackground}
    <rect width="512" height="512" rx="96" fill="#0f172a" />
  {/if}
  <!-- Rings. Opacity steps give the mark depth without introducing a
       second color — still currentColor-tinted. -->
  <g fill="none" stroke="currentColor">
    <circle cx="256" cy="256" r="220" stroke-width="18" opacity="0.3" />
    <circle cx="256" cy="256" r="160" stroke-width="12" opacity="0.5" />
    <circle cx="256" cy="256" r="100" stroke-width="12" opacity="0.7" />
  </g>
  <!-- Center dot — the "you are here" pin on the compass. -->
  <circle cx="256" cy="256" r="34" fill="currentColor" />
  <!-- Eight markers at ±130 offsets from center. When the svg has
       .is-spinning, this group rotates as a unit around (256, 256). -->
  <g class="markers" fill="currentColor">
    <circle cx="386" cy="256" r="24" />
    <circle cx="347.92" cy="347.92" r="24" />
    <circle cx="256" cy="386" r="24" />
    <circle cx="164.08" cy="347.92" r="24" />
    <circle cx="126" cy="256" r="24" />
    <circle cx="164.08" cy="164.08" r="24" />
    <circle cx="256" cy="126" r="24" />
    <circle cx="347.92" cy="164.08" r="24" />
  </g>
</svg>

<style>
  .bearings-mark {
    color: #38bdf8;
    display: inline-block;
    vertical-align: middle;
    flex-shrink: 0;
  }
  .bearings-mark.is-spinning .markers {
    transform-origin: 256px 256px;
    animation: bearings-sweep 2.4s linear infinite;
  }
  @keyframes bearings-sweep {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .bearings-mark.is-spinning .markers {
      animation: bearings-pulse 2s ease-in-out infinite;
    }
    @keyframes bearings-pulse {
      0%,
      100% {
        opacity: 1;
      }
      50% {
        opacity: 0.35;
      }
    }
  }
</style>
