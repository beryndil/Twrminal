<script lang="ts">
  /**
   * Claude logomark — five-petal radial mark used to identify Claude
   * sessions and Claude-specific UI elements throughout Bearings.
   *
   * The mark is five elongated oval petals arranged at 72° intervals
   * around a shared centre, producing the distinctive Anthropic / Claude
   * identity glyph at any icon size.
   *
   * Behaviour anchor: gap-cycle-01-009 acceptance criterion 3.
   * Pure presentational — no store access.
   */
  interface Props {
    /** Icon size in px. Default: 24. */
    size?: number;
    /** CSS classes forwarded to the root ``<svg>``. */
    class?: string;
  }

  const { size = 24, class: className = "" }: Props = $props();

  // Five petals at 72° intervals (0°, 72°, 144°, 216°, 288°).
  // Each petal is an ellipse centred at (12, 7.5) in local space,
  // rotated around the SVG centre (12, 12).
  const PETAL_COUNT = 5;
  const petals = Array.from({ length: PETAL_COUNT }, (_, i) => ({
    rotate: i * (360 / PETAL_COUNT),
  }));
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  class={className}
  aria-hidden="true"
  data-testid="claude-mark"
>
  {#each petals as petal, i (i)}
    <!--
      Each petal: an ellipse whose centre sits 4.5 px above the SVG
      centre (cy = 12 − 4.5 = 7.5), height 3.8 px, width 1.6 px.
      Rotating around the SVG centre (12, 12) distributes the petals
      evenly around the origin.
    -->
    <ellipse
      cx="12"
      cy="7.5"
      rx="1.6"
      ry="3.8"
      fill="currentColor"
      transform="rotate({petal.rotate} 12 12)"
      data-testid="claude-mark-petal"
    />
  {/each}
</svg>
