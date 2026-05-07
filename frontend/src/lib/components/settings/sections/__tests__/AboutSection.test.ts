/**
 * Unit tests for the About section component (gap-cycle-17-005).
 *
 * Acceptance criteria covered:
 *
 * 1. Every identity-card row renders its one-line description sourced from
 *    ``ABOUT_SECTION_STRINGS``.
 * 2. All four description strings are present verbatim (Build, Repository,
 *    License, Credits).
 * 3. Existing data-testid selectors (about-build-row, about-build-value,
 *    about-repository-row, about-repository-link, about-license-row,
 *    about-license-link, about-credits-row, about-credits-link) continue to
 *    resolve.
 *
 * All runtime dependencies are mocked — no real network or browser APIs.
 */
import { render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- Mock the API client so loadAboutInfo doesn't throw ----
vi.mock("../../../../api/client", () => ({
  getJson: vi.fn().mockResolvedValue({ version: "0.18.0", build_mtime: null }),
}));

import { ABOUT_SECTION_STRINGS } from "../../../../config";
import AboutSection from "../AboutSection.svelte";

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
// AC3 (backward-compat): existing data-testid selectors resolve
// ---------------------------------------------------------------------------

describe("AboutSection — existing data-testid selectors", () => {
  it("renders the identity card wrapper", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      expect(getByTestId("about-identity-card")).toBeTruthy();
    });
  });

  it("renders about-build-row and about-build-value", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      expect(getByTestId("about-build-row")).toBeTruthy();
      expect(getByTestId("about-build-value")).toBeTruthy();
    });
  });

  it("renders about-repository-row and about-repository-link", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      expect(getByTestId("about-repository-row")).toBeTruthy();
      expect(getByTestId("about-repository-link")).toBeTruthy();
    });
  });

  it("renders about-license-row and about-license-link", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      expect(getByTestId("about-license-row")).toBeTruthy();
      expect(getByTestId("about-license-link")).toBeTruthy();
    });
  });

  it("renders about-credits-row and about-credits-link", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      expect(getByTestId("about-credits-row")).toBeTruthy();
      expect(getByTestId("about-credits-link")).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// AC1 + AC2: Descriptions render for every row
// ---------------------------------------------------------------------------

describe("AboutSection — row descriptions", () => {
  it("Build row renders its description", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      const el = getByTestId("about-build-desc");
      expect(el.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.buildDescription);
    });
  });

  it("Repository row renders its description", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      const el = getByTestId("about-repository-desc");
      expect(el.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.repositoryDescription);
    });
  });

  it("License row renders its description", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      const el = getByTestId("about-license-desc");
      expect(el.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.licenseDescription);
    });
  });

  it("Credits row renders its description", async () => {
    const { getByTestId } = render(AboutSection);
    await waitFor(() => {
      const el = getByTestId("about-credits-desc");
      expect(el.textContent?.trim()).toBe(ABOUT_SECTION_STRINGS.creditsDescription);
    });
  });
});

// ---------------------------------------------------------------------------
// Verify description strings match the acceptance criteria verbatim
// ---------------------------------------------------------------------------

describe("AboutSection — description string content", () => {
  it("Build description matches AC verbatim", () => {
    expect(ABOUT_SECTION_STRINGS.buildDescription).toBe(
      "Identifies the running frontend bundle. Bumps on every npm run build.",
    );
  });

  it("Repository description matches AC verbatim", () => {
    expect(ABOUT_SECTION_STRINGS.repositoryDescription).toBe(
      "Source, issues, and releases on GitHub.",
    );
  });

  it("License description matches AC verbatim", () => {
    expect(ABOUT_SECTION_STRINGS.licenseDescription).toBe(
      "Bearings is released under the MIT License.",
    );
  });

  it("Credits description matches AC verbatim", () => {
    expect(ABOUT_SECTION_STRINGS.creditsDescription).toBe(
      "Open-source projects Bearings is built on.",
    );
  });
});
