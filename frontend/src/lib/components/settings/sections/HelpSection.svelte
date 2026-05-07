<script lang="ts">
  /**
   * Help section — keyboard shortcuts, README, docs, feedback buttons.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   */
  import type { SaveStatus } from "../sections.js";
  import { HELP_SECTION_STRINGS, KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET } from "$lib/config";
  import { getHandler } from "$lib/keyboard/store.svelte";
  import { openFeedbackTab } from "$lib/utils/feedback";

  interface Props {
    onsaveStatus?: (status: SaveStatus) => void;
  }

  // Help is read-only — no user-initiated saves.
  const { onsaveStatus: _onsaveStatus }: Props = $props();

  let helpFeedbackOpening = $state(false);

  async function handleOpenFeedback(kind: "bug" | "feature"): Promise<void> {
    if (helpFeedbackOpening) return;
    helpFeedbackOpening = true;
    try {
      await openFeedbackTab(kind);
    } finally {
      helpFeedbackOpening = false;
    }
  }
</script>

<section class="settings-page__group" aria-label="Help" data-testid="settings-help">
  <h2 class="settings-page__heading">{HELP_SECTION_STRINGS.heading}</h2>

  <div class="settings-help__row" data-testid="help-keyboard-shortcuts-row">
    <button
      type="button"
      class="settings-help__action-btn"
      onclick={() => getHandler(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET)?.()}
      data-testid="help-keyboard-shortcuts-btn"
    >
      {HELP_SECTION_STRINGS.keyboardShortcutsLabel}
    </button>
    <span class="settings-page__lede">{HELP_SECTION_STRINGS.keyboardShortcutsHint}</span>
  </div>

  <div class="settings-help__row" data-testid="help-readme-row">
    <a
      class="settings-help__action-btn settings-help__link"
      href={HELP_SECTION_STRINGS.readmeHref}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="help-readme-link"
    >
      {HELP_SECTION_STRINGS.readmeLabel}
    </a>
  </div>

  <div class="settings-help__row" data-testid="help-docs-row">
    <a
      class="settings-help__action-btn settings-help__link"
      href={HELP_SECTION_STRINGS.docsHref}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="help-docs-link"
    >
      {HELP_SECTION_STRINGS.docsLabel}
    </a>
  </div>

  <div class="settings-help__row" data-testid="help-report-bug-row">
    <button
      type="button"
      class="settings-help__action-btn"
      disabled={helpFeedbackOpening}
      onclick={() => void handleOpenFeedback("bug")}
      data-testid="help-report-bug-btn"
    >
      {HELP_SECTION_STRINGS.reportBugLabel}
    </button>
  </div>

  <div class="settings-help__row" data-testid="help-request-feature-row">
    <button
      type="button"
      class="settings-help__action-btn"
      disabled={helpFeedbackOpening}
      onclick={() => void handleOpenFeedback("feature")}
      data-testid="help-request-feature-btn"
    >
      {HELP_SECTION_STRINGS.requestFeatureLabel}
    </button>
  </div>
</section>

<style>
  .settings-help__row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  .settings-help__action-btn {
    background: transparent;
    color: rgb(var(--bearings-accent));
    border: 1px solid rgb(var(--bearings-border));
    border-radius: 0.25rem;
    padding: 0.3rem 0.875rem;
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
  }
  .settings-help__action-btn:hover {
    background: rgb(var(--bearings-surface-2));
    border-color: rgb(var(--bearings-accent));
  }
  .settings-help__action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .settings-help__link {
    text-decoration: none;
  }
</style>
