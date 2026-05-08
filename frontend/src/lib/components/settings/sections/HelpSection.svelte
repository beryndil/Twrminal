<script lang="ts">
  /**
   * Help section — keyboard shortcuts, README, docs, feedback buttons.
   * Extracted from ``+page.svelte`` as part of gap-cycle-07-007.
   *
   * gap-cycle-17-004: each row now renders a title, one-line description,
   * and a trailing affordance. The entire row surface is the action target.
   * External-link rows carry the ↗ glyph in their trailing to signal a new
   * tab opens. All strings live in ``HELP_SECTION_STRINGS`` in config.ts.
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
      class="settings-help__row-btn"
      onclick={() => getHandler(KEYBINDING_ACTION_TOGGLE_CHEAT_SHEET)?.()}
      data-testid="help-keyboard-shortcuts-btn"
    >
      <span class="settings-help__row-body">
        <span class="settings-help__row-title">{HELP_SECTION_STRINGS.keyboardShortcutsLabel}</span>
        <span class="settings-help__row-desc" data-testid="help-keyboard-shortcuts-desc"
          >{HELP_SECTION_STRINGS.keyboardShortcutsDescription}</span
        >
      </span>
      <span
        class="settings-help__row-trailing"
        aria-hidden="true"
        data-testid="help-keyboard-shortcuts-trailing"
        >{HELP_SECTION_STRINGS.keyboardShortcutsTrailing}</span
      >
    </button>
  </div>

  <div class="settings-help__row" data-testid="help-readme-row">
    <a
      class="settings-help__row-btn"
      href={HELP_SECTION_STRINGS.readmeHref}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="help-readme-link"
    >
      <span class="settings-help__row-body">
        <span class="settings-help__row-title">{HELP_SECTION_STRINGS.readmeLabel}</span>
        <span class="settings-help__row-desc" data-testid="help-readme-desc"
          >{HELP_SECTION_STRINGS.readmeDescription}</span
        >
      </span>
      <span
        class="settings-help__row-trailing"
        aria-hidden="true"
        data-testid="help-readme-trailing">{HELP_SECTION_STRINGS.readmeTrailing}</span
      >
    </a>
  </div>

  <div class="settings-help__row" data-testid="help-docs-row">
    <a
      class="settings-help__row-btn"
      href={HELP_SECTION_STRINGS.docsHref}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="help-docs-link"
    >
      <span class="settings-help__row-body">
        <span class="settings-help__row-title">{HELP_SECTION_STRINGS.docsLabel}</span>
        <span class="settings-help__row-desc" data-testid="help-docs-desc"
          >{HELP_SECTION_STRINGS.docsDescription}</span
        >
      </span>
      <span class="settings-help__row-trailing" aria-hidden="true" data-testid="help-docs-trailing"
        >{HELP_SECTION_STRINGS.docsTrailing}</span
      >
    </a>
  </div>

  <div class="settings-help__row" data-testid="help-report-bug-row">
    <button
      type="button"
      class="settings-help__row-btn"
      disabled={helpFeedbackOpening}
      onclick={() => void handleOpenFeedback("bug")}
      data-testid="help-report-bug-btn"
    >
      <span class="settings-help__row-body">
        <span class="settings-help__row-title">{HELP_SECTION_STRINGS.reportBugLabel}</span>
        <span class="settings-help__row-desc" data-testid="help-report-bug-desc"
          >{HELP_SECTION_STRINGS.reportBugDescription}</span
        >
      </span>
      <span
        class="settings-help__row-trailing"
        aria-hidden="true"
        data-testid="help-report-bug-trailing">{HELP_SECTION_STRINGS.reportBugTrailing}</span
      >
    </button>
  </div>

  <div class="settings-help__row" data-testid="help-request-feature-row">
    <button
      type="button"
      class="settings-help__row-btn"
      disabled={helpFeedbackOpening}
      onclick={() => void handleOpenFeedback("feature")}
      data-testid="help-request-feature-btn"
    >
      <span class="settings-help__row-body">
        <span class="settings-help__row-title">{HELP_SECTION_STRINGS.requestFeatureLabel}</span>
        <span class="settings-help__row-desc" data-testid="help-request-feature-desc"
          >{HELP_SECTION_STRINGS.requestFeatureDescription}</span
        >
      </span>
      <span
        class="settings-help__row-trailing"
        aria-hidden="true"
        data-testid="help-request-feature-trailing"
        >{HELP_SECTION_STRINGS.requestFeatureTrailing}</span
      >
    </button>
  </div>
</section>

<style>
  .settings-help__row {
    display: block;
  }

  .settings-help__row-btn {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    width: 100%;
    padding: 0.5rem 0.75rem;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 0.375rem;
    cursor: pointer;
    text-align: left;
    text-decoration: none;
    color: inherit;
    font: inherit;
    transition:
      background 0.1s,
      border-color 0.1s;
  }

  .settings-help__row-btn:hover {
    background: rgb(var(--bearings-surface-2));
    border-color: rgb(var(--bearings-border));
  }

  .settings-help__row-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .settings-help__row-body {
    display: flex;
    flex-direction: column;
    gap: 0.1875rem;
    flex: 1;
    min-width: 0;
  }

  .settings-help__row-title {
    font-size: 0.875rem;
    font-weight: 500;
    color: rgb(var(--bearings-accent));
  }

  .settings-help__row-desc {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
  }

  .settings-help__row-trailing {
    font-size: 0.75rem;
    color: rgb(var(--bearings-fg-muted));
    white-space: nowrap;
    flex-shrink: 0;
  }
</style>
