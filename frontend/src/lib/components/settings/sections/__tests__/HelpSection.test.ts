/**
 * Unit tests for the Help section component (gap-cycle-17-004).
 *
 * Acceptance criteria covered:
 *
 * 1. Every row renders a one-line description sourced from
 *    ``HELP_SECTION_STRINGS``.
 * 2. Every row renders a trailing affordance string sourced from
 *    ``HELP_SECTION_STRINGS``.
 * 3. External-link rows (README, Documentation) carry the ↗ glyph in their
 *    trailing to signal that the action opens a new tab.
 * 4. Existing data-testid selectors (help-readme-link, help-docs-link,
 *    help-report-bug-btn, help-request-feature-btn,
 *    help-keyboard-shortcuts-btn) continue to resolve.
 *
 * All runtime dependencies are mocked — no real network or browser APIs.
 */
import { render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- Mock keyboard store ----
vi.mock("../../../../keyboard/store.svelte", () => ({
  getHandler: vi.fn().mockReturnValue(undefined),
  bindHandler: vi.fn(),
  setComposerFocused: vi.fn(),
  setModalOpen: vi.fn(),
  _resetForTests: vi.fn(),
  keybindingsState: { composerFocused: false, modalOpen: false },
}));

// ---- Mock feedback utilities ----
vi.mock("../../../../utils/feedback", () => ({
  openFeedbackTab: vi.fn().mockResolvedValue(undefined),
}));

import { HELP_SECTION_STRINGS } from "../../../../config";
import HelpSection from "../HelpSection.svelte";

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// AC4 (backward-compat): existing data-testid selectors resolve
// ---------------------------------------------------------------------------

describe("HelpSection — existing data-testid selectors", () => {
  it("renders all five row wrappers", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("settings-help")).toBeTruthy();
      expect(getByTestId("help-keyboard-shortcuts-row")).toBeTruthy();
      expect(getByTestId("help-readme-row")).toBeTruthy();
      expect(getByTestId("help-docs-row")).toBeTruthy();
      expect(getByTestId("help-report-bug-row")).toBeTruthy();
      expect(getByTestId("help-request-feature-row")).toBeTruthy();
    });
  });

  it("keyboard shortcuts row exposes help-keyboard-shortcuts-btn", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-keyboard-shortcuts-btn")).toBeTruthy();
    });
  });

  it("README row exposes help-readme-link anchor", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-readme-link")).toBeTruthy();
    });
  });

  it("Documentation row exposes help-docs-link anchor", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-docs-link")).toBeTruthy();
    });
  });

  it("Report-a-bug row exposes help-report-bug-btn", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-report-bug-btn")).toBeTruthy();
    });
  });

  it("Request-a-feature row exposes help-request-feature-btn", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-request-feature-btn")).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// AC1: Descriptions render for every row
// ---------------------------------------------------------------------------

describe("HelpSection — row descriptions", () => {
  it("Keyboard shortcuts row renders its description", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-keyboard-shortcuts-desc");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.keyboardShortcutsDescription);
    });
  });

  it("README row renders its description", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-readme-desc");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.readmeDescription);
    });
  });

  it("Documentation row renders its description", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-docs-desc");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.docsDescription);
    });
  });

  it("Report-a-bug row renders its description", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-report-bug-desc");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.reportBugDescription);
    });
  });

  it("Request-a-feature row renders its description", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-request-feature-desc");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.requestFeatureDescription);
    });
  });
});

// ---------------------------------------------------------------------------
// AC2: Trailing affordances render for every row
// ---------------------------------------------------------------------------

describe("HelpSection — row trailing affordances", () => {
  it("Keyboard shortcuts row renders 'Show ?' trailing", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-keyboard-shortcuts-trailing");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.keyboardShortcutsTrailing);
    });
  });

  it("README row renders 'README ↗' trailing", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-readme-trailing");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.readmeTrailing);
    });
  });

  it("Documentation row renders 'docs/ ↗' trailing", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-docs-trailing");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.docsTrailing);
    });
  });

  it("Report-a-bug row renders 'New bug ↗' trailing", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-report-bug-trailing");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.reportBugTrailing);
    });
  });

  it("Request-a-feature row renders 'New request ↗' trailing", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      const el = getByTestId("help-request-feature-trailing");
      expect(el.textContent?.trim()).toBe(HELP_SECTION_STRINGS.requestFeatureTrailing);
    });
  });
});

// ---------------------------------------------------------------------------
// AC3: ↗ glyph appears only on external-link rows
// ---------------------------------------------------------------------------

describe("HelpSection — ↗ glyph on external-link rows only", () => {
  it("README trailing contains the ↗ glyph", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-readme-trailing").textContent).toContain("↗");
    });
  });

  it("Documentation trailing contains the ↗ glyph", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-docs-trailing").textContent).toContain("↗");
    });
  });

  it("Report-a-bug trailing contains the ↗ glyph", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-report-bug-trailing").textContent).toContain("↗");
    });
  });

  it("Request-a-feature trailing contains the ↗ glyph", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-request-feature-trailing").textContent).toContain("↗");
    });
  });

  it("Keyboard shortcuts trailing does NOT contain the ↗ glyph", async () => {
    const { getByTestId } = render(HelpSection);
    await waitFor(() => {
      expect(getByTestId("help-keyboard-shortcuts-trailing").textContent).not.toContain("↗");
    });
  });
});
