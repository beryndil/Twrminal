/**
 * Unit tests for the Authentication section of the Settings page
 * (gap-cycle-07-002).
 *
 * Acceptance criteria covered:
 *
 * 1. Authentication section renders (data-testid="settings-auth").
 * 2. Token field is pre-populated from localStorage via ``getStoredToken``.
 * 3. Typing a non-empty value calls ``saveToken``.
 * 4. Clearing the field (empty value) calls ``clearToken``.
 * 5. Typing a non-empty token while ``authStore.blocking`` is true
 *    calls ``saveToken`` (gate-bypass side-effect of saveToken).
 * 6. Description lede mentions device-local storage.
 *
 * All API and store functions are mocked — no real HTTP, WS, or
 * localStorage side-effects.
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
import { authStore, clearToken, getStoredToken, saveToken } from "../../../lib/stores/auth.svelte";
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
const mockSaveToken = saveToken as ReturnType<typeof vi.fn>;
const mockClearToken = clearToken as ReturnType<typeof vi.fn>;
const mockGetStoredToken = getStoredToken as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockGet.mockResolvedValue(makePrefs());
  mockSaveToken.mockResolvedValue(undefined);
  mockClearToken.mockImplementation(() => {});
  mockGetStoredToken.mockReturnValue("");
  (authStore as { blocking: boolean }).blocking = false;
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Section renders
// ---------------------------------------------------------------------------

describe("Settings — Authentication section renders", () => {
  it("mounts the authentication section", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("settings-auth")).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// 2. Field pre-populated from localStorage via getStoredToken
// ---------------------------------------------------------------------------

describe("Settings — Authentication token pre-population", () => {
  it("pre-populates the token field with the stored token", async () => {
    mockGetStoredToken.mockReturnValue("sk-ant-existing-token");
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const input = getByTestId("auth-token-input") as HTMLInputElement;
      expect(input.value).toBe("sk-ant-existing-token");
    });
  });

  it("leaves the field empty when no token is stored", async () => {
    mockGetStoredToken.mockReturnValue("");
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const input = getByTestId("auth-token-input") as HTMLInputElement;
      expect(input.value).toBe("");
    });
  });
});

// ---------------------------------------------------------------------------
// 3. Typing a non-empty value calls saveToken
// ---------------------------------------------------------------------------

describe("Settings — Authentication: keystroke triggers saveToken", () => {
  it("calls saveToken when a non-empty token is typed", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("auth-token-input"));

    const input = getByTestId("auth-token-input");
    fireEvent.input(input, { target: { value: "sk-ant-newtoken" } });

    await waitFor(() => {
      expect(mockSaveToken).toHaveBeenCalledWith("sk-ant-newtoken");
    });
  });
});

// ---------------------------------------------------------------------------
// 4. Clearing the field calls clearToken
// ---------------------------------------------------------------------------

describe("Settings — Authentication: token-clear path", () => {
  it("calls clearToken when the field is emptied", async () => {
    mockGetStoredToken.mockReturnValue("sk-ant-existing");
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("auth-token-input"));

    // Clear any init-phase calls from Svelte 5 $effect initialization.
    mockSaveToken.mockClear();
    mockClearToken.mockClear();
    const input = getByTestId("auth-token-input");
    fireEvent.input(input, { target: { value: "" } });

    await waitFor(() => {
      expect(mockClearToken).toHaveBeenCalled();
    });
    expect(mockSaveToken).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 5. Gate-bypass: blocking=true + non-empty token → saveToken called
// ---------------------------------------------------------------------------

describe("Settings — Authentication: gate-bypass path when blocking is true", () => {
  it("calls saveToken when blocking and a non-empty token is entered", async () => {
    (authStore as { blocking: boolean }).blocking = true;
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("auth-token-input"));

    const input = getByTestId("auth-token-input");
    fireEvent.input(input, { target: { value: "sk-ant-fresh" } });

    await waitFor(() => {
      expect(mockSaveToken).toHaveBeenCalledWith("sk-ant-fresh");
    });
  });
});

// ---------------------------------------------------------------------------
// 6. Lede describes device-local storage
// ---------------------------------------------------------------------------

describe("Settings — Authentication: section lede", () => {
  it("describes device-local storage", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const section = getByTestId("settings-auth");
      expect(section.textContent).toMatch(/device/i);
    });
  });
});
