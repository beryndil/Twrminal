<script lang="ts">
  /**
   * Severity shield — coloured shield glyph driven by a severity name.
   *
   * Rendered in the conversation header band, sidebar rows (via the
   * session tag chips), the new-session dialog, and the inspector
   * header per ``docs/behavior/chat.md`` §"When the user creates a
   * chat — severity tag drives the header shield colour".
   *
   * Colour mapping (Tailwind fill utilities, theme-independent):
   *   low      → green-400
   *   medium   → yellow-400
   *   high     → orange-500
   *   critical → red-500
   *   unknown  → fg-muted (graceful fallback)
   *
   * Behaviour anchor: gap-cycle-01-009 acceptance criterion 2.
   * Pure presentational — no store access.
   */
  type SeverityName = "low" | "medium" | "high" | "critical";

  interface Props {
    /** Severity level name — determines the fill colour. */
    severity: SeverityName | string;
    /** Icon size in px. Default: 16. */
    size?: number;
    /** CSS classes forwarded to the root ``<svg>``. */
    class?: string;
  }

  const { severity, size = 16, class: className = "" }: Props = $props();
</script>

<!--
  Shield path: flat top (y=2), straight sides to y=14, rounded point
  at (12,22). The fill colour is determined by ``severity`` via Tailwind
  fill utilities applied directly to the path element.
-->
<svg
  xmlns="http://www.w3.org/2000/svg"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  class={className}
  role="img"
  aria-label="Severity: {severity}"
  data-testid="severity-shield"
  data-severity={severity}
>
  <path
    d="M12 2 L20 5.5 L20 14 Q20 20 12 22 Q4 20 4 14 L4 5.5 Z"
    class:fill-green-400={severity === "low"}
    class:fill-yellow-400={severity === "medium"}
    class:fill-orange-500={severity === "high"}
    class:fill-red-500={severity === "critical"}
    class:fill-fg-muted={severity !== "low" &&
      severity !== "medium" &&
      severity !== "high" &&
      severity !== "critical"}
  />
</svg>
