<script lang="ts">
  /**
   * Close glyph — two crossed lines at 45°, used by modal dismiss
   * buttons and tag / chip remove controls throughout Bearings.
   *
   * Behaviour anchor: gap-cycle-01-009 acceptance criterion 4.
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
  data-testid="icon-x"
>
  <!-- ╲ line -->
  <line x1="3" y1="3" x2="13" y2="13" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
  <!-- ╱ line -->
  <line x1="13" y1="3" x2="3" y2="13" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
</svg>
