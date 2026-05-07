<script lang="ts">
  /**
   * Feedback megaphone button (gap-cycle-01-008).
   *
   * Renders a small megaphone icon button at the same density as the
   * other conversation-header icon buttons (``rounded p-0.5``).
   * Clicking it opens a GitHub ``issues/new`` URL in a new tab,
   * pre-filled with the operator environment (Bearings version, UA,
   * platform, language) and a steps-to-reproduce scaffold.
   *
   * The version is fetched lazily on the first click and the promise
   * is cached — subsequent clicks reuse the resolved value without a
   * second network request.
   *
   * Per Beryndil standards §17: Bearings does not POST any data; the
   * browser opens the GitHub form and the user submits manually.
   *
   * Behavior anchor: ``docs/behavior/chat.md`` §"Conversation header".
   */
  import { FEEDBACK_BUTTON_STRINGS } from "../../config";
  import { openFeedbackTab } from "../../utils/feedback";

  /** True while the version fetch is in-flight (disables the button). */
  let opening = $state(false);

  /**
   * Click handler — fetches the version lazily (cached after first
   * click), builds the URL, and opens a new tab.  The ``opening`` flag
   * prevents double-clicks from dispatching two window.open calls.
   */
  async function handleClick(): Promise<void> {
    if (opening) return;
    opening = true;
    try {
      await openFeedbackTab();
    } finally {
      opening = false;
    }
  }
</script>

<!--
  Icon button — same density as PendingOpsCard close / other inline
  icon actions: ``rounded p-0.5 text-fg-muted hover:bg-surface-2``.
-->
<button
  type="button"
  class="rounded p-0.5 text-fg-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"
  aria-label={FEEDBACK_BUTTON_STRINGS.ariaLabel}
  title={FEEDBACK_BUTTON_STRINGS.tooltip}
  data-testid="feedback-button"
  disabled={opening}
  onclick={() => void handleClick()}
>
  <!--
    Megaphone / speakerphone icon — Heroicons v1 outline ``speakerphone``
    path, scaled to 14×14 within a 24×24 viewBox so it matches the
    other 14-wide inline icons in the header (e.g. PendingOpsCard close).
  -->
  <svg
    viewBox="0 0 24 24"
    width="14"
    height="14"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path
      d="M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z"
    />
  </svg>
</button>
