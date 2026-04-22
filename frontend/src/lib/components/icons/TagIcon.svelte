<script lang="ts">
  /** Tiny inline SVG "luggage tag" used as the medallion next to a
   * session's title for each attached general-group tag. Colored from
   * the tag's `color` column when present; dim slate when the user
   * hasn't chosen one yet. The shape is a classic name-tag silhouette
   * (angled tip on the left, rounded body on the right, punched hole)
   * so a row of them reads as "tags" at a glance even at 12px.
   *
   * Hand-drawn path, no external icon dep.
   */
  interface Props {
    /** Fill color for the tag body. Null = neutral slate. */
    color?: string | null;
    /** Hover text — typically the tag's name. */
    title?: string;
    /** Width/height in px. Default matches SeverityShield. */
    size?: number;
  }

  let { color = null, title, size = 12 }: Props = $props();

  // Reactive so the medallion re-tints when the caller changes the
  // tag's color mid-flight (rename-recolor, or swapping tags on a row).
  const fill = $derived(color ?? 'var(--tag-fallback, #475569)');
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  viewBox="0 0 16 16"
  width={size}
  height={size}
  aria-hidden={title ? undefined : 'true'}
  role={title ? 'img' : undefined}
  aria-label={title}
  class="inline-block shrink-0"
>
  {#if title}
    <title>{title}</title>
  {/if}
  <!-- Tag body: rounded right edge, angled cut toward the left tip.
       Start top-left at x≈5 y≈3, go right along the top, round the
       right, come back along the bottom, then diagonal in to the
       pointy tip at x≈1.5 y≈8. -->
  <path
    d="M5 3 H12.5 A1.5 1.5 0 0 1 14 4.5 V11.5 A1.5 1.5 0 0 1 12.5 13 H5 L1.5 8 Z"
    fill={fill}
    stroke="rgba(0,0,0,0.35)"
    stroke-width="0.8"
    stroke-linejoin="round"
  />
  <!-- Punched hole through the tag where a string would pass. Small
       solid dot in the sidebar's slate-900 so it reads as a hole
       rather than a contrasting mark. -->
  <circle cx="5.4" cy="8" r="0.9" fill="#0f172a" />
</svg>
