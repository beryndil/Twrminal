/**
 * Unit tests for the Profile section of the Settings page.
 *
 * Acceptance criteria covered (gap-cycle-17-001):
 *
 * 1. Profile section renders (data-testid="settings-profile").
 * 2. Upload input triggers ``uploadAvatar`` (POST avatar).
 * 3. Sync button triggers ``syncFromSystem`` (POST sync_from_system).
 * 4. Remove button triggers ``deleteAvatar`` (DELETE avatar).
 * 5. Keystroke triggers debounced PATCH after ~400 ms (fake timers).
 * 6. No PATCH fired before debounce window expires.
 * 7. Display-name badge: idle → saving → saved on success.
 * 8. Display-name badge: idle → saving → error on failure.
 * 9. Avatar-upload badge: saving → saved on success.
 * 10. Avatar-upload badge: saving → error on failure.
 * 11. Avatar-remove badge: saving → saved on success.
 * 12. Avatar-remove badge: saving → error on failure.
 * 13. Sync badge: saving → saved on success.
 * 14. Sync badge: saving → error on failure.
 * 15. ``UserIdentityBlock`` is mounted inside the profile section.
 * 16. No "Save profile" button in the DOM (Save button removed).
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
import { PROFILE_AUTOSAVE_DEBOUNCE_MS } from "../../../lib/config";
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
const mockUpload = uploadAvatar as ReturnType<typeof vi.fn>;
const mockDelete = deleteAvatar as ReturnType<typeof vi.fn>;
const mockSync = syncFromSystem as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  mockGet.mockResolvedValue(makePrefs());
  mockPatch.mockResolvedValue(makePrefs({ display_name: "Test" }));
  mockUpload.mockResolvedValue(makePrefs({ avatar_url: "/api/preferences/avatar" }));
  mockDelete.mockResolvedValue(makePrefs());
  mockSync.mockResolvedValue(makePrefs({ display_name: "syncuser" }));
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Section renders
// ---------------------------------------------------------------------------

describe("Settings — Profile section renders", () => {
  it("mounts the profile section", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      expect(getByTestId("settings-profile")).toBeTruthy();
    });
  });

  it("shows UserIdentityBlock inside profile section", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      expect(getByTestId("user-identity-block")).toBeTruthy();
    });
  });

  it("does not render a Save profile button", async () => {
    const { queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => queryByTestId("settings-profile"));
    expect(queryByTestId("profile-save")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2. Upload triggers POST avatar
// ---------------------------------------------------------------------------

describe("Settings — Profile: upload triggers POST avatar", () => {
  it("calls uploadAvatar when a file is selected", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
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

// ---------------------------------------------------------------------------
// 3. Sync triggers POST sync_from_system
// ---------------------------------------------------------------------------

describe("Settings — Profile: sync triggers POST sync_from_system", () => {
  it("calls syncFromSystem when Sync button is clicked", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-sync"));

    fireEvent.click(getByTestId("profile-sync"));

    await waitFor(() => {
      expect(mockSync).toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// 4. Remove triggers DELETE avatar
// ---------------------------------------------------------------------------

describe("Settings — Profile: remove triggers DELETE avatar", () => {
  it("calls deleteAvatar when Remove button is clicked", async () => {
    mockGet.mockResolvedValue(makePrefs({ avatar_url: "/api/preferences/avatar" }));

    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-avatar-remove"));

    fireEvent.click(getByTestId("profile-avatar-remove"));

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// 5–6. Display-name autosave: debounce gates PATCH
// ---------------------------------------------------------------------------

describe("Settings — Profile: display-name autosave (debounce)", () => {
  it("does NOT call patchPreferences before the debounce window expires", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-display-name"));

    const input = getByTestId("profile-display-name") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "Ali" } });

    // Advance to just before the threshold.
    await vi.advanceTimersByTimeAsync(PROFILE_AUTOSAVE_DEBOUNCE_MS - 1);
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it("calls patchPreferences once after the debounce window", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-display-name"));

    const input = getByTestId("profile-display-name") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "Alice" } });

    await vi.advanceTimersByTimeAsync(PROFILE_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        expect.objectContaining({ display_name: expect.any(String) }),
      );
    });
    expect(mockPatch).toHaveBeenCalledTimes(1);
  });

  it("resets the debounce on each keystroke — only one PATCH for rapid typing", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-display-name"));

    // Clear any init-phase calls from Svelte 5 $effect initialization.
    mockPatch.mockClear();
    const input = getByTestId("profile-display-name") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "A" } });
    await vi.advanceTimersByTimeAsync(100);
    fireEvent.input(input, { target: { value: "Al" } });
    await vi.advanceTimersByTimeAsync(100);
    fireEvent.input(input, { target: { value: "Ali" } });
    await vi.advanceTimersByTimeAsync(100);
    fireEvent.input(input, { target: { value: "Alic" } });
    // Still inside window — no PATCH yet.
    expect(mockPatch).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(PROFILE_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledTimes(1);
    });
  });
});

// ---------------------------------------------------------------------------
// 7–8. Display-name badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Profile: display-name badge transitions", () => {
  it("shows Saving… badge while PATCH is in flight, then Saved on success", async () => {
    let resolvePatch!: (v: PreferencesOut) => void;
    mockPatch.mockImplementation(
      () =>
        new Promise<PreferencesOut>((res) => {
          resolvePatch = res;
        }),
    );

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-display-name"));

    const input = getByTestId("profile-display-name") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "Bob" } });
    await vi.advanceTimersByTimeAsync(PROFILE_AUTOSAVE_DEBOUNCE_MS);

    // PATCH in flight — badge should say "Saving…"
    await waitFor(() => {
      const badge = queryByTestId("profile-display-name-badge");
      expect(badge).not.toBeNull();
      expect(badge?.textContent).toContain("Saving");
    });

    // Resolve the PATCH — badge should flip to "Saved"
    resolvePatch(makePrefs({ display_name: "Bob" }));

    await waitFor(() => {
      const badge = queryByTestId("profile-display-name-badge");
      expect(badge?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on PATCH error", async () => {
    mockPatch.mockRejectedValue(new Error("server error"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-display-name"));

    const input = getByTestId("profile-display-name") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "Bob" } });
    await vi.advanceTimersByTimeAsync(PROFILE_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      const badge = queryByTestId("profile-display-name-badge");
      expect(badge).not.toBeNull();
      expect(badge?.textContent).toContain("Failed to save:");
    });
  });
});

// ---------------------------------------------------------------------------
// 9–10. Avatar upload badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Profile: avatar-upload badge transitions", () => {
  it("shows Saving… while upload is in flight, then Saved on success", async () => {
    let resolveUpload!: (v: PreferencesOut) => void;
    mockUpload.mockImplementation(
      () =>
        new Promise<PreferencesOut>((res) => {
          resolveUpload = res;
        }),
    );

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("settings-profile"));

    const input = getByTestId("profile-avatar-upload") as HTMLInputElement;
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e])], "img.png", {
      type: "image/png",
    });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    fireEvent.change(input);

    await waitFor(() => {
      const badge = queryByTestId("profile-avatar-upload-badge");
      expect(badge?.textContent).toContain("Saving");
    });

    resolveUpload(makePrefs({ avatar_url: "/api/preferences/avatar" }));

    await waitFor(() => {
      const badge = queryByTestId("profile-avatar-upload-badge");
      expect(badge?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on upload error", async () => {
    mockUpload.mockRejectedValue(new Error("413 too large"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("settings-profile"));

    const input = getByTestId("profile-avatar-upload") as HTMLInputElement;
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "photo.jpg", {
      type: "image/jpeg",
    });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    fireEvent.change(input);

    await waitFor(() => {
      const badge = queryByTestId("profile-avatar-upload-badge");
      expect(badge?.textContent).toContain("Failed to save:");
    });
  });
});

// ---------------------------------------------------------------------------
// 11–12. Avatar remove badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Profile: avatar-remove badge transitions", () => {
  it("shows Saving… while remove is in flight, then Saved on success", async () => {
    mockGet.mockResolvedValue(makePrefs({ avatar_url: "/api/preferences/avatar" }));
    let resolveDelete!: (v: PreferencesOut) => void;
    mockDelete.mockImplementation(
      () =>
        new Promise<PreferencesOut>((res) => {
          resolveDelete = res;
        }),
    );

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-avatar-remove"));

    fireEvent.click(getByTestId("profile-avatar-remove"));

    await waitFor(() => {
      const badge = queryByTestId("profile-avatar-remove-badge");
      expect(badge?.textContent).toContain("Saving");
    });

    resolveDelete(makePrefs());

    await waitFor(() => {
      const badge = queryByTestId("profile-avatar-remove-badge");
      expect(badge?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on remove error", async () => {
    mockGet.mockResolvedValue(makePrefs({ avatar_url: "/api/preferences/avatar" }));
    mockDelete.mockRejectedValue(new Error("network error"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-avatar-remove"));

    fireEvent.click(getByTestId("profile-avatar-remove"));

    await waitFor(() => {
      const badge = queryByTestId("profile-avatar-remove-badge");
      expect(badge?.textContent).toContain("Failed to save:");
    });
  });
});

// ---------------------------------------------------------------------------
// 13–14. Sync badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Profile: sync badge transitions", () => {
  it("shows Saving… while sync is in flight, then Saved on success", async () => {
    let resolveSync!: (v: PreferencesOut) => void;
    mockSync.mockImplementation(
      () =>
        new Promise<PreferencesOut>((res) => {
          resolveSync = res;
        }),
    );

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-sync"));

    fireEvent.click(getByTestId("profile-sync"));

    await waitFor(() => {
      const badge = queryByTestId("profile-sync-badge");
      expect(badge?.textContent).toContain("Saving");
    });

    resolveSync(makePrefs({ display_name: "syncuser" }));

    await waitFor(() => {
      const badge = queryByTestId("profile-sync-badge");
      expect(badge?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on sync error", async () => {
    mockSync.mockRejectedValue(new Error("sync failed"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("profile-sync"));

    fireEvent.click(getByTestId("profile-sync"));

    await waitFor(() => {
      const badge = queryByTestId("profile-sync-badge");
      expect(badge?.textContent).toContain("Failed to save:");
    });
  });
});
