/**
 * Unit tests for the Privacy section of the Settings page
 * (gap-cycle-07-003).
 *
 * Acceptance criteria covered:
 *
 * 1. Privacy section renders (data-testid="settings-privacy").
 * 2. Telemetry row renders headline + external TELEMETRY.md link.
 * 3. Data-dir row shows the path returned by GET /api/health.
 * 4. "Open data dir" button: success path — shell open 2xx → brief "Opened" state.
 * 5. "Open data dir" button: 400-fallback — shell open non-2xx →
 *    clipboard copy → "Path copied" label + footnote naming config key.
 * 6. "Open data dir" button: both-fail — shell open non-2xx + clipboard
 *    write fails → inline error renders.
 * 7. Data-dir error state renders when GET /api/health throws.
 *
 * All API and utility functions are mocked — no real HTTP or browser APIs.
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

import { getPreferences, type PreferencesOut } from "../../../lib/api/preferences";
import { getHealth, type HealthOut } from "../../../lib/api/health";
import { shellOpenInTerminal } from "../../../lib/api/shell";
import { ApiError } from "../../../lib/api/client";
import SettingsPage from "../+page.svelte";

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
const mockShellOpen = shellOpenInTerminal as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockGetPrefs.mockResolvedValue(makePrefs());
  mockGetHealth.mockResolvedValue(makeHealth());
  mockShellOpen.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Section renders
// ---------------------------------------------------------------------------

describe("Settings — Privacy section renders", () => {
  it("mounts the privacy section", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("settings-privacy")).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// 2. Telemetry row: headline + link
// ---------------------------------------------------------------------------

describe("Settings — Privacy telemetry row", () => {
  it("renders the telemetry headline and TELEMETRY.md link", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("privacy-telemetry-row")).toBeTruthy();
    });
    const link = getByTestId("privacy-telemetry-link") as HTMLAnchorElement;
    expect(link.href).toContain("TELEMETRY.md");
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
  });
});

// ---------------------------------------------------------------------------
// 3. Data-dir row shows resolved path
// ---------------------------------------------------------------------------

describe("Settings — Privacy data-dir path display", () => {
  it("renders the data_dir path from GET /api/health", async () => {
    mockGetHealth.mockResolvedValue(
      makeHealth({ data_dir: "/home/beryndil/.local/share/bearings-v1" }),
    );
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const el = getByTestId("privacy-data-dir-path");
      expect(el.textContent?.trim()).toBe("/home/beryndil/.local/share/bearings-v1");
    });
  });
});

// ---------------------------------------------------------------------------
// 4. Success path: shell open 2xx → brief "Opened" state
// ---------------------------------------------------------------------------

describe("Settings — Privacy open dir success path", () => {
  it("shows Opened label briefly after shell open succeeds", async () => {
    mockShellOpen.mockResolvedValue(undefined);
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("privacy-open-dir-btn"));

    fireEvent.click(getByTestId("privacy-open-dir-btn"));

    await waitFor(() => {
      const btn = getByTestId("privacy-open-dir-btn");
      expect(btn.textContent?.trim()).toMatch(/opened/i);
    });
    // Footnote and error must NOT be visible.
    expect(document.querySelector("[data-testid='privacy-clipboard-note']")).toBeNull();
    expect(document.querySelector("[data-testid='privacy-open-error']")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 5. 400-fallback: shell non-2xx → clipboard copy → "Path copied" + footnote
// ---------------------------------------------------------------------------

describe("Settings — Privacy open dir clipboard fallback", () => {
  it("copies path and shows footnote when shell open returns non-2xx", async () => {
    mockShellOpen.mockRejectedValue(new ApiError(400, {}, "shell not configured"));
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("privacy-open-dir-btn"));

    fireEvent.click(getByTestId("privacy-open-dir-btn"));

    await waitFor(() => {
      const btn = getByTestId("privacy-open-dir-btn");
      expect(btn.textContent?.trim()).toMatch(/path copied/i);
    });
    expect(writeText).toHaveBeenCalledWith("/home/beryndil/.local/share/bearings-v1");
    expect(getByTestId("privacy-clipboard-note")).toBeTruthy();
    expect(document.querySelector("[data-testid='privacy-open-error']")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 6. Both-fail: shell non-2xx + clipboard fail → inline error
// ---------------------------------------------------------------------------

describe("Settings — Privacy open dir both-fail path", () => {
  it("shows inline error when shell open and clipboard both fail", async () => {
    mockShellOpen.mockRejectedValue(new ApiError(400, {}, "shell not configured"));
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("clipboard denied")) },
    });

    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("privacy-open-dir-btn"));

    fireEvent.click(getByTestId("privacy-open-dir-btn"));

    await waitFor(() => {
      expect(getByTestId("privacy-open-error")).toBeTruthy();
    });
    expect(document.querySelector("[data-testid='privacy-clipboard-note']")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 7. Health error state
// ---------------------------------------------------------------------------

describe("Settings — Privacy health load error", () => {
  it("renders the error state when GET /api/health throws", async () => {
    mockGetHealth.mockRejectedValue(new Error("network error"));
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("privacy-data-dir-error")).toBeTruthy();
    });
    expect(document.querySelector("[data-testid='privacy-data-dir-path']")).toBeNull();
  });
});
