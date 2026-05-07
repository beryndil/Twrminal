/**
 * Unit tests for the Notifications section of the Settings page
 * (gap-cycle-07-001).
 *
 * Acceptance criteria covered:
 *
 * 1. Notifications section renders (data-testid="settings-notifications").
 * 2. Toggle renders unchecked by default (notify_on_complete: false).
 * 3. Toggle renders checked when preferences carry notify_on_complete: true.
 * 4. Flipping ON calls requestNotifyPermission and patchPreferences on grant.
 * 5. Flipping ON rolls back and shows error when permission is denied.
 * 6. Unsupported footnote renders and toggle is disabled when
 *    supportsNotifications returns false.
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

import {
  getPreferences,
  patchPreferences,
  type PreferencesOut,
} from "../../../lib/api/preferences";
import {
  requestNotifyPermission,
  setNotifyOnComplete,
  supportsNotifications,
} from "../../../lib/utils/notify";
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

const mockGet = getPreferences as ReturnType<typeof vi.fn>;
const mockPatch = patchPreferences as ReturnType<typeof vi.fn>;
const mockRequestPermission = requestNotifyPermission as ReturnType<typeof vi.fn>;
const mockSetNotify = setNotifyOnComplete as ReturnType<typeof vi.fn>;
const mockSupports = supportsNotifications as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockGet.mockResolvedValue(makePrefs());
  mockPatch.mockResolvedValue(makePrefs({ notify_on_complete: true }));
  mockRequestPermission.mockResolvedValue("granted");
  mockSetNotify.mockImplementation(() => {});
  mockSupports.mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Section renders
// ---------------------------------------------------------------------------

describe("Settings — Notifications section renders", () => {
  it("mounts the notifications section", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("settings-notifications")).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// 2. Toggle unchecked by default
// ---------------------------------------------------------------------------

describe("Settings — Notifications toggle default state", () => {
  it("renders toggle unchecked when notify_on_complete is false", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("notify-toggle"));
    const toggle = getByTestId("notify-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 3. Toggle checked when pref is true
// ---------------------------------------------------------------------------

describe("Settings — Notifications toggle checked state", () => {
  it("renders toggle checked when notify_on_complete is true", async () => {
    mockGet.mockResolvedValue(makePrefs({ notify_on_complete: true }));
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const toggle = getByTestId("notify-toggle") as HTMLInputElement;
      expect(toggle.checked).toBe(true);
    });
  });
});

// ---------------------------------------------------------------------------
// 4. Flipping ON — requests permission then patches
// ---------------------------------------------------------------------------

describe("Settings — Notifications toggle ON triggers patch", () => {
  it("calls requestNotifyPermission then patchPreferences on grant", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("notify-toggle"));

    fireEvent.change(getByTestId("notify-toggle"), { target: { checked: true } });

    await waitFor(() => {
      expect(mockRequestPermission).toHaveBeenCalled();
      expect(mockPatch).toHaveBeenCalledWith(
        expect.objectContaining({ notify_on_complete: true }),
      );
    });
  });
});

// ---------------------------------------------------------------------------
// 5. Permission denied → rollback + error
// ---------------------------------------------------------------------------

describe("Settings — Notifications toggle ON denied rolls back", () => {
  it("rolls back and shows error when permission denied", async () => {
    mockRequestPermission.mockResolvedValue("denied");
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("notify-toggle"));

    fireEvent.change(getByTestId("notify-toggle"), { target: { checked: true } });

    await waitFor(() => {
      expect(getByTestId("notify-error")).toBeTruthy();
      const toggle = getByTestId("notify-toggle") as HTMLInputElement;
      expect(toggle.checked).toBe(false);
    });
    expect(mockPatch).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 6. Unsupported — footnote visible + toggle disabled
// ---------------------------------------------------------------------------

describe("Settings — Notifications unsupported state", () => {
  it("shows unsupported footnote and disables toggle", async () => {
    mockSupports.mockReturnValue(false);
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("notify-toggle"));

    expect(getByTestId("notify-unsupported")).toBeTruthy();
    const toggle = getByTestId("notify-toggle") as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 7. Steady-state description renders (gap-cycle-17-003)
// ---------------------------------------------------------------------------

describe("Settings — Notifications description renders in default state", () => {
  it("shows the toggle description when notifications are supported and not denied", async () => {
    mockSupports.mockReturnValue(true);
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("notify-description"));
    const desc = getByTestId("notify-description");
    expect(desc.textContent).toContain("hidden or unfocused");
  });
});
