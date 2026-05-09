/**
 * Unit tests for the Defaults section of the Settings page.
 *
 * Acceptance criteria covered (gap-cycle-17-002):
 *
 * 1. Defaults section renders (data-testid="settings-defaults").
 * 2. No "Save preferences" button in the DOM.
 * 3. Theme select onChange fires immediate PATCH with {theme}.
 * 4. Model select onChange fires immediate PATCH with {default_model}.
 * 5. Permission-mode select onChange fires immediate PATCH with
 *    {default_permission_mode}.
 * 6. Working-dir keystroke triggers debounced PATCH after ~400 ms.
 * 7. No PATCH fired for working-dir before debounce window expires.
 * 8. Theme badge: idle → saving → saved on success.
 * 9. Theme badge: idle → saving → error on failure.
 * 10. Model badge: saving → saved on success.
 * 11. Model badge: saving → error on failure.
 * 12. Permission-mode badge: saving → saved on success.
 * 13. Permission-mode badge: saving → error on failure.
 * 14. Working-dir badge: saving → saved on success.
 * 15. Working-dir badge: saving → error on failure.
 * 16. Theme change in Defaults updates themeStore (ThemePicker reflects it).
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
  getPreferences,
  patchPreferences,
  type PreferencesOut,
} from "../../../lib/api/preferences";
import { DEFAULTS_AUTOSAVE_DEBOUNCE_MS, KNOWN_THEMES } from "../../../lib/config";
import { themeStore, _resetForTests as resetThemeStore } from "../../../lib/themes/store.svelte";
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

beforeEach(() => {
  vi.useFakeTimers();
  mockGet.mockResolvedValue(makePrefs());
  mockPatch.mockResolvedValue(makePrefs());
  // Reset themeStore to a known state so tests are independent.
  resetThemeStore("default");
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1–2. Section renders; no Save button
// ---------------------------------------------------------------------------

describe("Settings — Defaults section renders", () => {
  it("mounts the defaults section", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      expect(getByTestId("settings-defaults")).toBeTruthy();
    });
  });

  it("does not render a Save preferences button", async () => {
    const { queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => queryByTestId("settings-defaults"));
    expect(queryByTestId("prefs-save")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. Theme select — immediate PATCH on change
// ---------------------------------------------------------------------------

describe("Settings — Defaults: theme select fires immediate PATCH", () => {
  it("calls patchPreferences immediately when theme changes", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-theme"));

    const select = getByTestId("prefs-theme") as HTMLSelectElement;
    // Pick a theme that is different from the current store value.
    const nextTheme = KNOWN_THEMES.find((t) => t !== themeStore.theme) ?? KNOWN_THEMES[1];
    fireEvent.change(select, { target: { value: nextTheme } });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(expect.objectContaining({ theme: nextTheme }));
    });
    // No debounce — should have fired in the same tick, not after a delay.
    expect(mockPatch).toHaveBeenCalledTimes(1);
  });

  it("updates themeStore.theme when theme select changes", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-theme"));

    const select = getByTestId("prefs-theme") as HTMLSelectElement;
    const nextTheme = KNOWN_THEMES.find((t) => t !== themeStore.theme) ?? KNOWN_THEMES[1];
    fireEvent.change(select, { target: { value: nextTheme } });

    // setTheme() is called synchronously — themeStore updates immediately.
    expect(themeStore.theme).toBe(nextTheme);
  });
});

// ---------------------------------------------------------------------------
// 4. Model select — immediate PATCH on change
// ---------------------------------------------------------------------------

describe("Settings — Defaults: model select fires immediate PATCH", () => {
  it("calls patchPreferences immediately when model changes", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-model"));

    // Clear any init-phase calls from Svelte 5 $effect initialization.
    mockPatch.mockClear();
    const select = getByTestId("prefs-model") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "sonnet" } });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(expect.objectContaining({ default_model: "sonnet" }));
    });
    expect(mockPatch).toHaveBeenCalledTimes(1);
  });

  it("sends null for default_model when empty option is selected", async () => {
    mockGet.mockResolvedValue(makePrefs({ default_model: "sonnet" }));

    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-model"));

    const select = getByTestId("prefs-model") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "" } });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(expect.objectContaining({ default_model: null }));
    });
  });
});

// ---------------------------------------------------------------------------
// 5. Permission-mode select — immediate PATCH on change
// ---------------------------------------------------------------------------

describe("Settings — Defaults: permission-mode select fires immediate PATCH", () => {
  it("calls patchPreferences immediately when permission mode changes", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-permission-mode"));

    // Clear any init-phase calls from Svelte 5 $effect initialization.
    mockPatch.mockClear();
    const select = getByTestId("prefs-permission-mode") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "bypassPermissions" } });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        expect.objectContaining({ default_permission_mode: "bypassPermissions" }),
      );
    });
    expect(mockPatch).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// 6–7. Working-dir text input — debounced PATCH
// ---------------------------------------------------------------------------

describe("Settings — Defaults: working-dir input autosave (debounce)", () => {
  it("does NOT call patchPreferences before the debounce window expires", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-working-dir"));

    // Clear any init-phase calls from Svelte 5 $effect initialization.
    mockPatch.mockClear();
    const input = getByTestId("prefs-working-dir") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "/home/user" } });

    await vi.advanceTimersByTimeAsync(DEFAULTS_AUTOSAVE_DEBOUNCE_MS - 1);
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it("calls patchPreferences once after the debounce window", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-working-dir"));

    // Clear any init-phase calls from Svelte 5 $effect initialization.
    mockPatch.mockClear();
    const input = getByTestId("prefs-working-dir") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "/home/user/project" } });

    await vi.advanceTimersByTimeAsync(DEFAULTS_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        expect.objectContaining({ default_working_dir: "/home/user/project" }),
      );
    });
    expect(mockPatch).toHaveBeenCalledTimes(1);
  });

  it("resets the debounce on each keystroke — only one PATCH for rapid typing", async () => {
    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-working-dir"));

    // Clear any init-phase calls from Svelte 5 $effect initialization.
    mockPatch.mockClear();
    const input = getByTestId("prefs-working-dir") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "/h" } });
    await vi.advanceTimersByTimeAsync(100);
    fireEvent.input(input, { target: { value: "/ho" } });
    await vi.advanceTimersByTimeAsync(100);
    fireEvent.input(input, { target: { value: "/hom" } });
    await vi.advanceTimersByTimeAsync(100);
    fireEvent.input(input, { target: { value: "/home" } });
    // Still inside window — no PATCH yet.
    expect(mockPatch).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(DEFAULTS_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledTimes(1);
    });
  });

  it("sends null for default_working_dir when input is cleared", async () => {
    mockGet.mockResolvedValue(makePrefs({ default_working_dir: "/existing" }));

    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-working-dir"));

    const input = getByTestId("prefs-working-dir") as HTMLInputElement;
    fireEvent.input(input, { target: { value: "" } });

    await vi.advanceTimersByTimeAsync(DEFAULTS_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        expect.objectContaining({ default_working_dir: null }),
      );
    });
  });
});

// ---------------------------------------------------------------------------
// 8–9. Theme badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Defaults: theme badge transitions", () => {
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
    await waitFor(() => getByTestId("prefs-theme"));

    const select = getByTestId("prefs-theme") as HTMLSelectElement;
    const nextTheme = KNOWN_THEMES.find((t) => t !== themeStore.theme) ?? KNOWN_THEMES[1];
    fireEvent.change(select, { target: { value: nextTheme } });

    await waitFor(() => {
      const badge = queryByTestId("prefs-theme-badge");
      expect(badge).not.toBeNull();
      expect(badge?.textContent).toContain("Saving");
    });

    resolvePatch(makePrefs({ theme: nextTheme }));

    await waitFor(() => {
      const badge = queryByTestId("prefs-theme-badge");
      expect(badge?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on PATCH error", async () => {
    mockPatch.mockRejectedValue(new Error("server error"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-theme"));

    const select = getByTestId("prefs-theme") as HTMLSelectElement;
    const nextTheme = KNOWN_THEMES.find((t) => t !== themeStore.theme) ?? KNOWN_THEMES[1];
    fireEvent.change(select, { target: { value: nextTheme } });

    await waitFor(() => {
      const badge = queryByTestId("prefs-theme-badge");
      expect(badge).not.toBeNull();
      expect(badge?.textContent).toContain("Failed to save:");
    });
  });
});

// ---------------------------------------------------------------------------
// 10–11. Model badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Defaults: model badge transitions", () => {
  it("shows Saving… while PATCH is in flight, then Saved on success", async () => {
    let resolvePatch!: (v: PreferencesOut) => void;
    mockPatch.mockImplementation(
      () =>
        new Promise<PreferencesOut>((res) => {
          resolvePatch = res;
        }),
    );

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-model"));

    fireEvent.change(getByTestId("prefs-model"), { target: { value: "sonnet" } });

    await waitFor(() => {
      expect(queryByTestId("prefs-model-badge")?.textContent).toContain("Saving");
    });

    resolvePatch(makePrefs({ default_model: "sonnet" }));

    await waitFor(() => {
      expect(queryByTestId("prefs-model-badge")?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on PATCH error", async () => {
    mockPatch.mockRejectedValue(new Error("network error"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-model"));

    fireEvent.change(getByTestId("prefs-model"), { target: { value: "sonnet" } });

    await waitFor(() => {
      expect(queryByTestId("prefs-model-badge")?.textContent).toContain("Failed to save:");
    });
  });
});

// ---------------------------------------------------------------------------
// 12–13. Permission-mode badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Defaults: permission-mode badge transitions", () => {
  it("shows Saving… while PATCH is in flight, then Saved on success", async () => {
    let resolvePatch!: (v: PreferencesOut) => void;
    mockPatch.mockImplementation(
      () =>
        new Promise<PreferencesOut>((res) => {
          resolvePatch = res;
        }),
    );

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-permission-mode"));

    fireEvent.change(getByTestId("prefs-permission-mode"), {
      target: { value: "bypassPermissions" },
    });

    await waitFor(() => {
      expect(queryByTestId("prefs-permission-mode-badge")?.textContent).toContain("Saving");
    });

    resolvePatch(makePrefs({ default_permission_mode: "bypassPermissions" }));

    await waitFor(() => {
      expect(queryByTestId("prefs-permission-mode-badge")?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on PATCH error", async () => {
    mockPatch.mockRejectedValue(new Error("network error"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-permission-mode"));

    fireEvent.change(getByTestId("prefs-permission-mode"), {
      target: { value: "bypassPermissions" },
    });

    await waitFor(() => {
      expect(queryByTestId("prefs-permission-mode-badge")?.textContent).toContain(
        "Failed to save:",
      );
    });
  });
});

// ---------------------------------------------------------------------------
// 14–15. Working-dir badge transitions
// ---------------------------------------------------------------------------

describe("Settings — Defaults: working-dir badge transitions", () => {
  it("shows Saving… while PATCH is in flight, then Saved on success", async () => {
    let resolvePatch!: (v: PreferencesOut) => void;
    mockPatch.mockImplementation(
      () =>
        new Promise<PreferencesOut>((res) => {
          resolvePatch = res;
        }),
    );

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-working-dir"));

    fireEvent.input(getByTestId("prefs-working-dir"), { target: { value: "/projects/foo" } });
    await vi.advanceTimersByTimeAsync(DEFAULTS_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      expect(queryByTestId("prefs-working-dir-badge")?.textContent).toContain("Saving");
    });

    resolvePatch(makePrefs({ default_working_dir: "/projects/foo" }));

    await waitFor(() => {
      expect(queryByTestId("prefs-working-dir-badge")?.textContent).toContain("Saved");
    });
  });

  it("shows Failed to save: badge on PATCH error", async () => {
    mockPatch.mockRejectedValue(new Error("server error"));

    const { getByTestId, queryByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-working-dir"));

    fireEvent.input(getByTestId("prefs-working-dir"), { target: { value: "/projects/bar" } });
    await vi.advanceTimersByTimeAsync(DEFAULTS_AUTOSAVE_DEBOUNCE_MS);

    await waitFor(() => {
      expect(queryByTestId("prefs-working-dir-badge")?.textContent).toContain("Failed to save:");
    });
  });
});

// ---------------------------------------------------------------------------
// 16. Theme select reflects themeStore (cross-sync with ThemePicker)
// ---------------------------------------------------------------------------

describe("Settings — Defaults: theme select reflects themeStore", () => {
  it("theme select value tracks themeStore.theme on mount", async () => {
    // Set a specific theme in the store before mounting.
    resetThemeStore("evergreen");

    const { getByTestId } = render(SettingsPage);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => getByTestId("prefs-theme"));

    const select = getByTestId("prefs-theme") as HTMLSelectElement;
    expect(select.value).toBe("evergreen");
  });
});
