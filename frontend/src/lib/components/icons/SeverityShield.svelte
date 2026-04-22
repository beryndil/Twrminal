<script lang="ts">
  /** Tiny inline SVG shield used as the severity medallion on a
   * session row. Filled with the severity tag's `color` (hex from the
   * migration-0021 seed, or whatever the user overrode it to); falls
   * back to a dim slate when the caller has no color to offer — which
   * is what shows up for sessions whose severity tag was deleted and
   * never replaced (the "physical law" case).
   *
   * Hand-drawn path, no external icon dep. Viewbox 0 0 16 16 so it
   * sits naturally next to text at small sizes — pass `size` to nudge
   * if a different row density needs it.
   */
  interface Props {
    /** Fill color for the shield body. Pass `null` or omit when the
     * session has no severity tag; we render a dimmed placeholder. */
    color?: string | null;
    /** Hover text. Typically the severity tag's name, e.g. "Blocker". */
    title?: string;
    /** Width/height in px. Defaults to 12 to match the tag-icon
     * sibling at the sidebar's current density. */
    size?: number;
  }

  let { color = null, title, size = 12 }: Props = $props();

  // Hollow slate fallback so the user still sees "no severity here"
  // rather than an invisible slot. Uses a CSS token rather than hex
  // so the fallback re-tints if Tailwind swaps palettes. Must be
  // `$derived` rather than `const` so the SVG re-tints when the caller
  // swaps in a new color prop (e.g. user rename-recolor flow).
  const fill = $derived(color ?? 'var(--severity-fallback, #475569)');
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
  <!-- Shield outline: rounded top, pointed chin. The inner stroke
       (rgba black 0.25) gives it enough edge against dark sidebars
       without relying on a separate drop shadow. -->
  <path
    d="M8 1.2 L2.8 3 V7.6 C2.8 10.9 5 13.4 8 14.8 C11 13.4 13.2 10.9 13.2 7.6 V3 Z"
    fill={fill}
    stroke="rgba(0,0,0,0.35)"
    stroke-width="0.8"
    stroke-linejoin="round"
  />
  <!-- Subtle highlight stripe on the upper-left bevel so tinted fills
       still read as a 3D object instead of a flat blob. -->
  <path
    d="M4.2 3.6 L8 2.4 V6.2 L4.2 7.1 Z"
    fill="rgba(255,255,255,0.18)"
  />
</svg>
