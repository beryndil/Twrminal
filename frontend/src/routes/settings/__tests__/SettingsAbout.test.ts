/**
 * Unit tests for the About section of the Settings page
 * (gap-cycle-07-005).
 *
 * Acceptance criteria covered:
 *
 * 1. Hero renders all six required elements: BearingsMark logo,
 *    "Bearings" title, release version, tagline, "by Beryndil" link,
 *    and the "Buy Me a Cup of Coffee" CTA.
 * 2. Build-token formatter: ``formatBuildMtime`` handles null, a
 *    valid finite timestamp, and non-finite inputs (NaN, Infinity).
 * 3. Identity card carries the four expected hrefs: Repository,
 *    License, Credits, and byline (developer URL).
 * 4. Version-fetch failure renders ``ABOUT_SECTION_STRINGS.versionUnavailable``
 *    rather than throwing or spinning forever.
 *
 * All API and utility functions are mocked — no real HTTP or browser APIs.
 */
import { render, waitFor } from "@testing-library/svelte";
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
vi.mock("../../../lib/components/identity/UserIdentityBlock.svelte", () => ({
  default: function UserIdentityBlockStub(_anchor: any, _props: any) {},
}));
vi.mock("../../../lib/components/icons/BearingsMark.svelte", () => ({
  default: function BearingsMarkStub(_anchor: any, _props: any) {},
}));
/* eslint-enable @typescript-eslint/no-explicit-any */

vi.mock("../../../lib/api/import", () => ({
  importFromBearings: vi.fn(),
}));

// ---- Mock the API client (getJson) ----
vi.mock("../../../lib/api/client", () => ({
  getJson: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, body: unknown, message: string) {
      super(message);
      this.status = status;
      this.body = body;
    }
  },
  postJson: vi.fn(),
  patchJson: vi.fn(),
  deleteJson: vi.fn(),
  putJson: vi.fn(),
}));

import { ABOUT_SECTION_STRINGS } from "../../../lib/config";
import { getPreferences, type PreferencesOut } from "../../../lib/api/preferences";
import { getHealth, type HealthOut } from "../../../lib/api/health";
import { getJson } from "../../../lib/api/client";
import { formatBuildMtime } from "../../../lib/utils/datetime";
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

const FAKE_BUILD_MTIME = 1_737_000_000; // 2026-01-16 UTC approx

function makeDiag(overrides: { version?: string; build_mtime?: number | null } = {}) {
  return {
    version: "0.18.0",
    uptime_s: 99.0,
    pid: 12345,
    db_configured: true,
    billing_mode: "payg",
    build_mtime: FAKE_BUILD_MTIME,
    ...overrides,
  };
}

const mockGetPrefs = getPreferences as ReturnType<typeof vi.fn>;
const mockGetHealth = getHealth as ReturnType<typeof vi.fn>;
const mockGetJson = getJson as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockGetPrefs.mockResolvedValue(makePrefs());
  mockGetHealth.mockResolvedValue(makeHealth());
  mockGetJson.mockResolvedValue(makeDiag());
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// AC2 (pure unit): formatBuildMtime — null, valid, non-finite
// ---------------------------------------------------------------------------

describe("formatBuildMtime utility", () => {
  it("returns 'dev build' for null", () => {
    expect(formatBuildMtime(null)).toBe("dev build");
  });

  it("returns 'dev build' for NaN", () => {
    expect(formatBuildMtime(NaN)).toBe("dev build");
  });

  it("returns 'dev build' for Infinity", () => {
    expect(formatBuildMtime(Infinity)).toBe("dev build");
  });

  it("returns 'dev build' for -Infinity", () => {
    expect(formatBuildMtime(-Infinity)).toBe("dev build");
  });

  it("returns a non-empty string for a valid finite timestamp", () => {
    const result = formatBuildMtime(FAKE_BUILD_MTIME);
    // Must not be the fallback string.
    expect(result).not.toBe("dev build");
    // Must be a non-empty string (locale formatting may vary by environment).
    expect(result.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// AC1: Hero renders all six required elements
// ---------------------------------------------------------------------------

describe("Settings — About section hero", () => {
  it("mounts the about section", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("settings-about")).toBeTruthy();
    });
  });

  it("renders the hero block", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("about-hero")).toBeTruthy();
    });
  });

  it("hero: renders the logo wrapper (data-testid='about-logo')", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("about-logo")).toBeTruthy();
    });
  });

  it("hero: renders the product name 'Bearings'", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const el = getByTestId("about-product-name");
      expect(el.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.productName);
    });
  });

  it("hero: renders the release version from GET /api/diag/server", async () => {
    mockGetJson.mockResolvedValue(makeDiag({ version: "0.18.5" }));
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const el = getByTestId("about-version");
      expect(el.textContent?.trim()).toContain("0.18.5");
    });
  });

  it("hero: renders the one-line tagline", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const el = getByTestId("about-tagline");
      expect(el.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.tagline);
    });
  });

  it("hero: renders the 'by Beryndil' byline link to developerUrl", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("about-byline-link"));
    const link = getByTestId("about-byline-link") as HTMLAnchorElement;
    expect(link.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.bylineLabel);
    expect(link.href).toBe(ABOUT_SECTION_STRINGS.developerUrl);
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
  });

  it("hero: renders the developer photo at 80×80", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("about-photo"));
    const img = getByTestId("about-photo") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("/about_beryndil.png");
    expect(img.getAttribute("width")).toBe("80");
    expect(img.getAttribute("height")).toBe("80");
  });

  it("hero: renders the coffee CTA linking to developerUrl", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("about-coffee-cta"));
    const link = getByTestId("about-coffee-link") as HTMLAnchorElement;
    expect(link.href).toBe(ABOUT_SECTION_STRINGS.developerUrl);
    expect(link.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.coffeeLabel);
  });
});

// ---------------------------------------------------------------------------
// AC4: Version-fetch failure → "version unavailable"
// ---------------------------------------------------------------------------

describe("Settings — About section version-fetch failure", () => {
  it("renders 'version unavailable' when GET /api/diag/server throws", async () => {
    mockGetJson.mockRejectedValue(new Error("network error"));
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const el = getByTestId("about-version");
      expect(el.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.versionUnavailable);
    });
  });
});

// ---------------------------------------------------------------------------
// AC3: Identity card carries the four expected hrefs
// ---------------------------------------------------------------------------

describe("Settings — About section identity card hrefs", () => {
  it("renders the identity card", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      expect(getByTestId("about-identity-card")).toBeTruthy();
    });
  });

  it("identity card: Build row shows formatted mtime", async () => {
    mockGetJson.mockResolvedValue(makeDiag({ build_mtime: FAKE_BUILD_MTIME }));
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const el = getByTestId("about-build-value");
      expect(el.textContent?.trim()).not.toBe("dev build");
      expect(el.textContent?.trim().length).toBeGreaterThan(0);
    });
  });

  it("identity card: Build row shows 'dev build' when build_mtime is null", async () => {
    mockGetJson.mockResolvedValue(makeDiag({ build_mtime: null }));
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => {
      const el = getByTestId("about-build-value");
      expect(el.textContent?.trim()).toBe("dev build");
    });
  });

  it("identity card: Repository link carries the correct href", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("about-repository-link"));
    const link = getByTestId("about-repository-link") as HTMLAnchorElement;
    expect(link.href).toBe(ABOUT_SECTION_STRINGS.repositoryHref);
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
  });

  it("identity card: License link carries the correct href", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("about-license-link"));
    const link = getByTestId("about-license-link") as HTMLAnchorElement;
    expect(link.href).toBe(ABOUT_SECTION_STRINGS.licenseHref);
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
  });

  it("identity card: Credits link carries the correct href", async () => {
    const { getByTestId } = render(SettingsPage);
    await waitFor(() => getByTestId("about-credits-link"));
    const link = getByTestId("about-credits-link") as HTMLAnchorElement;
    expect(link.href).toBe(ABOUT_SECTION_STRINGS.creditsHref);
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
  });
});
