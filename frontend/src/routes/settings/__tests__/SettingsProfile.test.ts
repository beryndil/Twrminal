/**
 * Unit tests for the Profile section of the Settings page
 * (gap-cycle-03-011).
 *
 * Acceptance criteria covered:
 *
 * 1. Profile section renders (data-testid="settings-profile").
 * 2. Upload input triggers ``uploadAvatar`` (POST avatar).
 * 3. Sync button triggers ``syncFromSystem`` (POST sync_from_system).
 * 4. Remove button triggers ``deleteAvatar`` (DELETE avatar).
 * 5. Save button triggers ``patchPreferences`` with ``display_name``.
 * 6. ``UserIdentityBlock`` is mounted inside the profile section.
 *
 * All API functions are mocked — no real HTTP requests are issued.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- Mock the API module before the page component imports it ----
vi.mock("../../../lib/api/preferences", () => ({
  getPreferences: vi.fn(),
  patchPreferences: vi.fn(),
  uploadAvatar: vi.fn(),
  deleteAvatar: vi.fn(),
  syncFromSystem: vi.fn(),
}));

// Mock heavy child components that require WS / routing / theme-store infra.
// In Svelte 5, components are functions — the mock default must be callable.
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
  deleteAvatar,
  getPreferences,
  patchPreferences,
  syncFromSystem,
  uploadAvatar,
  type PreferencesOut,
} from "../../../lib/api/preferences";
import SettingsPage from "../+page.svelte";

function makePrefs(overrides: Partial<PreferencesOut> = {}): PreferencesOut {
  return {
    theme: "default",
    default_model: null,
    default_permission_mode: null,
    default_working_dir: null,
    display_name: null,
    avatar_url: null,
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const mockGet = getPreferences as ReturnType<typeof vi.fn>;
const mockPatch = patchPreferences as ReturnType<typeof vi.fn>;
const mockUpload = uploadAvatar as ReturnType<typeof vi.fn>;
const mockDelete = deleteAvatar as ReturnType<typeof vi.fn>;
const mockSync = syncFromSystem as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockGet.mockResolvedValue(makePrefs());
  mockPatch.mockResolvedValue(makePrefs({ display_name: "Test" }));
  mockUpload.mockResolvedValue(makePrefs({ avatar_url: "/api/preferences/avatar" }));
  mockDelete.mockResolvedValue(makePrefs());
  mockSync.mockResolvedValue(makePrefs({ display_name: "syncuser" }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Settings — Profile section renders", () => {
  it("mounts the profile section", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("settings-profile")).toBeTruthy();
    });
  });

  it("shows UserIdentityBlock inside profile section", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("user-identity-block")).toBeTruthy();
    });
  });
});

describe("Settings — Profile: upload triggers POST avatar", () => {
  it("calls uploadAvatar when a file is selected", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("settings-profile"));

    const input = getByTestId("profile-avatar-upload") as HTMLInputElement;
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "photo.jpg", {
      type: "image/jpeg",
    });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    fireEvent.change(input);

    await waitFor(() => {
      expect(mockUpload).toHaveBeenCalledWith(file);
    });
  });
});

describe("Settings — Profile: sync triggers POST sync_from_system", () => {
  it("calls syncFromSystem when Sync button is clicked", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("profile-sync"));

    fireEvent.click(getByTestId("profile-sync"));

    await waitFor(() => {
      expect(mockSync).toHaveBeenCalled();
    });
  });
});

describe("Settings — Profile: remove triggers DELETE avatar", () => {
  it("calls deleteAvatar when Remove button is clicked", async () => {
    // Pre-load prefs with an avatar so the Remove button renders.
    mockGet.mockResolvedValue(makePrefs({ avatar_url: "/api/preferences/avatar" }));

    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("profile-avatar-remove"));

    fireEvent.click(getByTestId("profile-avatar-remove"));

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalled();
    });
  });
});

describe("Settings — Profile: save triggers PATCH display_name", () => {
  it("calls patchPreferences with display_name on form submit", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("profile-save"));

    const nameInput = getByTestId("profile-display-name") as HTMLInputElement;
    fireEvent.input(nameInput, { target: { value: "Alice" } });
    fireEvent.click(getByTestId("profile-save"));

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        expect.objectContaining({ display_name: expect.any(String) }),
      );
    });
  });
});
