/**
 * Unit tests for the Help section of the Settings page
 * (gap-cycle-07-004).
 *
 * Acceptance criteria covered:
 *
 * 1. Help section renders (data-testid="settings-help").
 * 2. Clicking "Keyboard shortcuts" button invokes the registered
 *    ``help.toggle_cheat_sheet`` handler via :func:`getHandler`.
 * 3. README link carries the correct href, ``target="_blank"``, and
 *    ``rel="noopener noreferrer"``.
 * 4. Documentation link carries the correct href, ``target="_blank"``,
 *    and ``rel="noopener noreferrer"``.
 * 5. Clicking "Report a bug" calls :func:`openFeedbackTab` with
 *    ``kind="bug"``.
 * 6. Clicking "Request a feature" calls :func:`openFeedbackTab` with
 *    ``kind="feature"``.
 *
 * All API and utility functions are mocked — no real HTTP or browser
 * APIs.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- Mock the preferences API ----
vi.mock("../../../lib/api/preferences", () => ({
  getPreferences: vi.fn(),
  patchPreferences: vi.fn(),
  uploadAvatar: vi.fn(),
  deleteAvatar: vi.fn(),
  syncFromSystem: vi.fn(),
}));

// ---- Mock the health API ----
vi.mock("../../../lib/api/health", () => ({
  getHealth: vi.fn(),
}));

// ---- Mock the shell API ----
vi.mock("../../../lib/api/shell", () => ({
  shellOpenInTerminal: vi.fn(),
  shellOpenInEditor: vi.fn(),
  shellRevealInExplorer: vi.fn(),
}));

// ---- Mock the auth store ----
vi.mock("../../../lib/stores/auth.svelte", () => ({
  authStore: { blocking: false },
  saveToken: vi.fn().mockResolvedValue(undefined),
  clearToken: vi.fn(),
  getStoredToken: vi.fn().mockReturnValue(""),
  _setBlocking: vi.fn(),
  _resetForTests: vi.fn(),
  _setBlockingForTests: vi.fn(),
}));

// ---- Mock notify utilities ----
vi.mock("../../../lib/utils/notify", () => ({
  supportsNotifications: vi.fn().mockReturnValue(true),
  requestNotifyPermission: vi.fn().mockResolvedValue("granted"),
  setNotifyOnComplete: vi.fn(),
  getNotifyOnComplete: vi.fn().mockReturnValue(false),
  maybeFireTurnNotification: vi.fn(),
}));

// ---- Mock feedback utilities ----
vi.mock("../../../lib/utils/feedback", () => ({
  openFeedbackTab: vi.fn().mockResolvedValue(undefined),
}));

// ---- Mock the keyboard store ----
vi.mock("../../../lib/keyboard/store.svelte", () => ({
  getHandler: vi.fn(),
  bindHandler: vi.fn(),
  setComposerFocused: vi.fn(),
  setModalOpen: vi.fn(),
  _resetForTests: vi.fn(),
  keybindingsState: { composerFocused: false, modalOpen: false },
}));

// ---- Mock heavy child components ----
/* eslint-disable @typescript-eslint/no-explicit-any */
vi.mock("../../../lib/themes/ThemePicker.svelte", () => ({
  default: function ThemePickerStub(_anchor: any, _props: any) {},
}));
vi.mock("../../../lib/components/routing/RoutingRuleEditor.svelte", () => ({
  default: function RoutingRuleEditorStub(_anchor: any, _props: any) {},
}));
/* eslint-enable @typescript-eslint/no-explicit-any */
vi.mock("../../../lib/api/import", () => ({
  importFromBearings: vi.fn(),
}));
vi.mock("../../../lib/components/identity/UserIdentityBlock.svelte", () => ({
  /* eslint-disable @typescript-eslint/no-explicit-any */
  default: function UserIdentityBlockStub(_anchor: any, _props: any) {},
  /* eslint-enable @typescript-eslint/no-explicit-any */
}));

import { HELP_SECTION_STRINGS } from "../../../lib/config";
import { getPreferences, type PreferencesOut } from "../../../lib/api/preferences";
import { getHealth, type HealthOut } from "../../../lib/api/health";
import { openFeedbackTab } from "../../../lib/utils/feedback";
import { getHandler } from "../../../lib/keyboard/store.svelte";
import SettingsPage from "../+page.svelte";

// ---- Helpers ----

function makePrefs(overrides: Partial<PreferencesOut> = {}): PreferencesOut {
  return {
    theme: "default",
    default_model: null,
    default_permission_mode: null,
    default_working_dir: null,
    display_name: null,
    avatar_url: null,
    notify_on_complete: false,
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeHealth(overrides: Partial<HealthOut> = {}): HealthOut {
  return {
    status: "ok",
    version: "0.18.0",
    uptime_s: 42.0,
    db_ok: true,
    data_dir: "/home/beryndil/.local/share/bearings-v1",
    ...overrides,
  };
}

const mockGetPrefs = getPreferences as ReturnType<typeof vi.fn>;
const mockGetHealth = getHealth as ReturnType<typeof vi.fn>;
const mockOpenFeedbackTab = openFeedbackTab as ReturnType<typeof vi.fn>;
const mockGetHandler = getHandler as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockGetPrefs.mockResolvedValue(makePrefs());
  mockGetHealth.mockResolvedValue(makeHealth());
  mockOpenFeedbackTab.mockResolvedValue(undefined);
  mockGetHandler.mockReturnValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// AC1: Section renders
// ---------------------------------------------------------------------------

describe("Settings — Help section renders", () => {
  it("mounts the help section", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("settings-help")).toBeTruthy();
    });
  });

  it("renders all five rows", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("help-keyboard-shortcuts-row")).toBeTruthy();
      expect(getByTestId("help-readme-row")).toBeTruthy();
      expect(getByTestId("help-docs-row")).toBeTruthy();
      expect(getByTestId("help-report-bug-row")).toBeTruthy();
      expect(getByTestId("help-request-feature-row")).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// AC2: Keyboard shortcuts button invokes cheat-sheet handler
// ---------------------------------------------------------------------------

describe("Settings — Help keyboard shortcuts button", () => {
  it("invokes the registered cheat-sheet handler on click", async () => {
    const cheatSheetHandler = vi.fn();
    mockGetHandler.mockReturnValue(cheatSheetHandler);

    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-keyboard-shortcuts-btn"));

    fireEvent.click(getByTestId("help-keyboard-shortcuts-btn"));

    expect(cheatSheetHandler).toHaveBeenCalledTimes(1);
  });

  it("is a no-op when no cheat-sheet handler is registered", async () => {
    // getHandler returns undefined — optional-chain call must not throw.
    mockGetHandler.mockReturnValue(undefined);

    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-keyboard-shortcuts-btn"));

    expect(() => {
      fireEvent.click(getByTestId("help-keyboard-shortcuts-btn"));
    }).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// AC3: README link
// ---------------------------------------------------------------------------

describe("Settings — Help README link", () => {
  it("carries the expected href", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-readme-link"));

    const link = getByTestId("help-readme-link") as HTMLAnchorElement;
    expect(link.href).toBe(HELP_SECTION_STRINGS.readmeHref);
  });

  it("opens in a new tab with noopener noreferrer", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-readme-link"));

    const link = getByTestId("help-readme-link") as HTMLAnchorElement;
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
    expect(link.rel).toContain("noreferrer");
  });
});

// ---------------------------------------------------------------------------
// AC4: Documentation link
// ---------------------------------------------------------------------------

describe("Settings — Help Documentation link", () => {
  it("carries the expected href", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-docs-link"));

    const link = getByTestId("help-docs-link") as HTMLAnchorElement;
    expect(link.href).toBe(HELP_SECTION_STRINGS.docsHref);
  });

  it("opens in a new tab with noopener noreferrer", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-docs-link"));

    const link = getByTestId("help-docs-link") as HTMLAnchorElement;
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
    expect(link.rel).toContain("noreferrer");
  });
});

// ---------------------------------------------------------------------------
// AC5: Report a bug button → kind="bug"
// ---------------------------------------------------------------------------

describe("Settings — Help report a bug button", () => {
  it("calls openFeedbackTab with kind='bug' on click", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-report-bug-btn"));

    fireEvent.click(getByTestId("help-report-bug-btn"));

    await waitFor(() => {
      expect(mockOpenFeedbackTab).toHaveBeenCalledWith("bug");
    });
  });
});

// ---------------------------------------------------------------------------
// AC6: Request a feature button → kind="feature"
// ---------------------------------------------------------------------------

describe("Settings — Help request a feature button", () => {
  it("calls openFeedbackTab with kind='feature' on click", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("help-request-feature-btn"));

    fireEvent.click(getByTestId("help-request-feature-btn"));

    await waitFor(() => {
      expect(mockOpenFeedbackTab).toHaveBeenCalledWith("feature");
    });
  });
});
