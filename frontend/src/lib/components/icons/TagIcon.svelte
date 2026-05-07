<script lang="ts">
  /**
   * Tag glyph — price-tag shape used by tag chips in the sidebar and
   * the new-session dialog.
   *
   * The shape is a rounded-rectangle body with a pointed right end and
   * a small circle (hole) near the tip, matching the canonical "label /
   * price tag" metaphor used in most design systems.
   *
   * Behaviour anchor: gap-cycle-01-009 acceptance criterion 5.
   * Pure presentational — no store access.
   */
  interface Props {
    /** Icon size in px. Default: 16. */
    size?: number;
    /** CSS classes forwarded to the root ``<svg>``. */
    class?: string;
  }

  const { size = 16, class: className = "" }: Props = $props();
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill="none"
  class={className}
  aria-hidden="true"
  data-testid="tag-icon"
>
  <!--
    Tag body: rectangle with rounded left end, pointed right end.
    Path: start at the left-centre rounded tip, go up, across, then
    angle to the right point, angle back, go across and back to start.
  -->
  <path
    d="M2 5 Q2 3 4 3 L10 3 L14 8 L10 13 L4 13 Q2 13 2 11 Z"
    stroke="currentColor"
    stroke-width="1.25"
    stroke-linejoin="round"
    fill="none"
  />
  <!-- Hole near the pointed tip -->
  <circle cx="5" cy="8" r="1" fill="currentColor" />
</svg>
