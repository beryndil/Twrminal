<script lang="ts">
  /**
   * Bearings brand mark — three concentric rings with eight cardinal-
   * direction dot markers.
   *
   * When ``loading`` is ``true`` the markers animate in a clockwise
   * sweep to signal long-running tool activity (keepalive visual).
   *
   * Behaviour anchor: gap-cycle-01-009 acceptance criterion 1.
   * Pure presentational — no store access.
   */
  interface Props {
    /** Animate the cardinal markers in a sweep (long-tool keepalive). */
    loading?: boolean;
    /** Icon size in px (applied to ``width`` / ``height``). Default: 24. */
    size?: number;
    /** CSS classes forwarded to the root ``<svg>``. */
    class?: string;
  }

  const { loading = false, size = 24, class: className = "" }: Props = $props();

  // Eight cardinal points: N, NE, E, SE, S, SW, W, NW — clockwise from
  // top (−90°). Dots sit between the middle and outer rings at r=9.
  const POINT_COUNT = 8;
  const ORBIT_R = 9;
  const cardinalPoints = Array.from({ length: POINT_COUNT }, (_, i) => {
    const deg = (i * 360) / POINT_COUNT - 90;
    const rad = (deg * Math.PI) / 180;
    return {
      cx: 12 + ORBIT_R * Math.cos(rad),
      cy: 12 + ORBIT_R * Math.sin(rad),
      // Stagger so the sweep travels clockwise around the ring.
      animDelay: `${Math.round((i / POINT_COUNT) * 800)}ms`,
    };
  });
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  class={className}
  aria-hidden="true"
  data-testid="bearings-mark"
>
  <!-- Three concentric rings -->
  <circle cx="12" cy="12" r="11" stroke="currentColor" stroke-width="1" />
  <circle cx="12" cy="12" r="6.5" stroke="currentColor" stroke-width="1" />
  <circle cx="12" cy="12" r="2.5" stroke="currentColor" stroke-width="1" />

  <!-- Eight cardinal-direction markers -->
  {#each cardinalPoints as point, i (i)}
    <circle
      cx={point.cx}
      cy={point.cy}
      r="1.2"
      fill="currentColor"
      class:bearings-mark-cardinal--sweep={loading}
      style={loading ? `animation-delay: ${point.animDelay}` : undefined}
      data-testid="bearings-mark-cardinal"
    />
  {/each}
</svg>

<style>
  /*
   * Staggered sweep — each dot fades in/out at its own offset so the
   * animation travels clockwise around the three-ring mark. The
   * animation-delay is set inline per dot; this rule only defines the
   * keyframe and duration.
   *
   * @keyframes name is verbose to avoid colliding with any other
   * keyframe in the global CSS scope (Svelte does not hash @keyframes).
   */
  @keyframes bearings-cardinal-sweep {
    0%,
    100% {
      opacity: 0.15;
    }
    50% {
      opacity: 1;
    }
  }

  .bearings-mark-cardinal--sweep {
    animation: bearings-cardinal-sweep 800ms ease-in-out infinite;
  }

  /*
   * Reduced-motion opt-back-in: swap the staggered sweep for a slow,
   * uniform opacity pulse so the working state remains legible without
   * any translation or rotation.
   *
   * The global ``@media (prefers-reduced-motion: reduce)`` rule in
   * ``app.css`` collapses ``animation-duration`` to ``0.01ms !important``
   * and ``animation-iteration-count`` to ``1 !important``; we override
   * both with ``!important`` here to restore a perceptible (but calm)
   * indicator. ``animation-delay`` is also cleared so all eight dots
   * pulse together rather than in a staggered sweep.
   *
   * @keyframes name is verbose to avoid colliding with other keyframes in
   * the global CSS scope (Svelte does not hash @keyframes).
   */
  @keyframes bearings-cardinal-pulse {
    0%,
    100% {
      opacity: 0.3;
    }
    50% {
      opacity: 0.9;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .bearings-mark-cardinal--sweep {
      animation: bearings-cardinal-pulse 2s ease-in-out infinite !important;
      animation-delay: 0ms !important;
    }
  }
</style>
