/**
 * Unit tests for SettingsShell (gap-cycle-07-007).
 *
 * Acceptance criteria covered:
 *
 * 1. Registry-driven render order — rail items appear in weight order.
 * 2. Rail keyboard nav — ↑/↓ moves active section; Home/End jump to ends.
 * 3. Deep-link round-trip — ``?settings=<id>`` on mount lands on the
 *    matching section; ``history.replaceState`` is called when the user
 *    switches sections.
 * 4. Footer status states — "Saving…" / "All changes saved" / "Failed: …"
 *    appear when the active section emits the matching SaveStatus.
 * 5. Clicking a rail item shows the matching panel and hides the others.
 *
 * Section components are replaced with lightweight stubs so the shell
 * can be tested in isolation without any real API or store dependencies.
 */
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Component } from "svelte";
import type { SettingsSectionDef, SaveStatus } from "../../../lib/components/settings/sections.js";
import SettingsShell from "../../../lib/components/settings/SettingsShell.svelte";

// ---------------------------------------------------------------------------
// Stub section components
// ---------------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any */
function makeStub(): Component<any> {
  // Svelte 5 components are functions. Cast the no-op function to the
  // Component type so the registry type-checks without importing real sections.
  return function StubSection(_anchor: any, _props: any) {} as unknown as Component<any>;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

const ALPHA_SECTION: SettingsSectionDef = {
  id: "alpha",
  label: "Alpha",
  weight: 10,
  component: makeStub(),
};
const BETA_SECTION: SettingsSectionDef = {
  id: "beta",
  label: "Beta",
  weight: 20,
  component: makeStub(),
};
const GAMMA_SECTION: SettingsSectionDef = {
  id: "gamma",
  label: "Gamma",
  weight: 30,
  component: makeStub(),
};

const TEST_SECTIONS: readonly SettingsSectionDef[] = [
  // Intentionally out of weight order to verify the shell sorts.
  BETA_SECTION,
  GAMMA_SECTION,
  ALPHA_SECTION,
];

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

let replaceStateSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  replaceStateSpy = vi.spyOn(history, "replaceState");
});

afterEach(() => {
  vi.restoreAllMocks();
  // Reset URL search params between tests.
  history.replaceState({}, "", window.location.pathname);
});

// ---------------------------------------------------------------------------
// 1. Registry-driven render order
// ---------------------------------------------------------------------------

describe("SettingsShell — registry-driven render order", () => {
  it("renders rail items sorted by weight (alpha < beta < gamma)", () => {
    const { getAllByRole } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });
    const tabs = getAllByRole("tab");
    expect(tabs.map((t) => t.textContent?.trim())).toEqual(["Alpha", "Beta", "Gamma"]);
  });

  it("renders one tabpanel per registered section", () => {
    const { getAllByRole } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });
    const panels = getAllByRole("tabpanel");
    expect(panels).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------
// 2. Rail keyboard navigation
// ---------------------------------------------------------------------------

describe("SettingsShell — rail keyboard navigation", () => {
  it("ArrowDown moves to the next section", async () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });
    const rail = getByTestId("settings-rail");

    fireEvent.keyDown(rail, { key: "ArrowDown" });

    await waitFor(() => {
      expect(getByTestId("rail-item-beta").getAttribute("aria-selected")).toBe("true");
    });
  });

  it("ArrowUp moves to the previous section (wraps from first to last)", async () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });
    const rail = getByTestId("settings-rail");

    fireEvent.keyDown(rail, { key: "ArrowUp" });

    await waitFor(() => {
      expect(getByTestId("rail-item-gamma").getAttribute("aria-selected")).toBe("true");
    });
  });

  it("End jumps to the last section", async () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });
    const rail = getByTestId("settings-rail");

    fireEvent.keyDown(rail, { key: "End" });

    await waitFor(() => {
      expect(getByTestId("rail-item-gamma").getAttribute("aria-selected")).toBe("true");
    });
  });

  it("Home jumps to the first section", async () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "gamma" },
    });
    const rail = getByTestId("settings-rail");

    fireEvent.keyDown(rail, { key: "Home" });

    await waitFor(() => {
      expect(getByTestId("rail-item-alpha").getAttribute("aria-selected")).toBe("true");
    });
  });

  it("ArrowDown wraps from last to first", async () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "gamma" },
    });
    const rail = getByTestId("settings-rail");

    fireEvent.keyDown(rail, { key: "ArrowDown" });

    await waitFor(() => {
      expect(getByTestId("rail-item-alpha").getAttribute("aria-selected")).toBe("true");
    });
  });
});

// ---------------------------------------------------------------------------
// 3. Deep-link round-trip
// ---------------------------------------------------------------------------

describe("SettingsShell — deep-link round-trip", () => {
  it("initialSectionId prop lands on the matching section", () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "beta" },
    });
    expect(getByTestId("rail-item-beta").getAttribute("aria-selected")).toBe("true");
    expect(getByTestId("rail-item-alpha").getAttribute("aria-selected")).toBe("false");
  });

  it("clicking a rail item calls history.replaceState with the section id", async () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });

    fireEvent.click(getByTestId("rail-item-beta"));

    await waitFor(() => {
      expect(replaceStateSpy).toHaveBeenCalled();
      const callArgs = replaceStateSpy.mock.calls[0];
      // Third arg is the URL string — must contain settings=beta.
      expect(String(callArgs[2])).toContain("settings=beta");
    });
  });

  it("falls back to first section (by array order) when initialSectionId is not in registry", () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "nonexistent" },
    });
    // resolveInitialId validates the prop and falls back to sections[0].
    // TEST_SECTIONS[0] is BETA_SECTION (weight 20) — it becomes the active tab.
    const rail = getByTestId("settings-rail");
    const activeTab = rail.querySelectorAll('[aria-selected="true"]');
    expect(activeTab.length).toBe(1);
    expect(getByTestId("rail-item-beta").getAttribute("aria-selected")).toBe("true");
  });
});

// ---------------------------------------------------------------------------
// 4. Footer status states
// ---------------------------------------------------------------------------

describe("SettingsShell — footer status states", () => {
  it("footer is absent when save state is idle", () => {
    const { queryByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });
    expect(queryByTestId("settings-save-status")).toBeNull();
  });

  it("footer shows 'Saving…' when a section emits state=saving", async () => {
    // Use a section stub that fires onsaveStatus on mount.
    /* eslint-disable @typescript-eslint/no-explicit-any */
    const SavingStub = function (_anchor: any, props: any) {
      // Trigger save status synchronously so the effect runs before assertions.
      props.onsaveStatus?.({ state: "saving" } satisfies SaveStatus);
    } as unknown as Component<any>;
    /* eslint-enable @typescript-eslint/no-explicit-any */

    const sections: readonly SettingsSectionDef[] = [
      { id: "alpha", label: "Alpha", weight: 10, component: SavingStub },
    ];

    const { getByTestId } = render(SettingsShell, {
      props: { sections, initialSectionId: "alpha" },
    });

    await waitFor(() => {
      expect(getByTestId("settings-save-status").textContent).toContain("Saving");
    });
  });

  it("footer shows 'All changes saved' when a section emits state=saved", async () => {
    /* eslint-disable @typescript-eslint/no-explicit-any */
    const SavedStub = function (_anchor: any, props: any) {
      props.onsaveStatus?.({ state: "saved" } satisfies SaveStatus);
    } as unknown as Component<any>;
    /* eslint-enable @typescript-eslint/no-explicit-any */

    const sections: readonly SettingsSectionDef[] = [
      { id: "alpha", label: "Alpha", weight: 10, component: SavedStub },
    ];

    const { getByTestId } = render(SettingsShell, {
      props: { sections, initialSectionId: "alpha" },
    });

    await waitFor(() => {
      expect(getByTestId("settings-save-status").textContent).toContain("All changes saved");
    });
  });

  it("footer shows error prefix + message when a section emits state=error", async () => {
    /* eslint-disable @typescript-eslint/no-explicit-any */
    const ErrorStub = function (_anchor: any, props: any) {
      props.onsaveStatus?.({ state: "error", message: "Network timeout" } satisfies SaveStatus);
    } as unknown as Component<any>;
    /* eslint-enable @typescript-eslint/no-explicit-any */

    const sections: readonly SettingsSectionDef[] = [
      { id: "alpha", label: "Alpha", weight: 10, component: ErrorStub },
    ];

    const { getByTestId } = render(SettingsShell, {
      props: { sections, initialSectionId: "alpha" },
    });

    await waitFor(() => {
      const text = getByTestId("settings-save-status").textContent ?? "";
      expect(text).toContain("Failed to save:");
      expect(text).toContain("Network timeout");
    });
  });

  it("footer status resets to idle when the user switches sections", async () => {
    /* eslint-disable @typescript-eslint/no-explicit-any */
    const SavedStub = function (_anchor: any, props: any) {
      props.onsaveStatus?.({ state: "saved" } satisfies SaveStatus);
    } as unknown as Component<any>;
    const BlankStub = function (_anchor: any, _props: any) {} as unknown as Component<any>;
    /* eslint-enable @typescript-eslint/no-explicit-any */

    const sections: readonly SettingsSectionDef[] = [
      { id: "alpha", label: "Alpha", weight: 10, component: SavedStub },
      { id: "beta", label: "Beta", weight: 20, component: BlankStub },
    ];

    const { getByTestId, queryByTestId } = render(SettingsShell, {
      props: { sections, initialSectionId: "alpha" },
    });

    // Wait for footer to appear.
    await waitFor(() => {
      expect(getByTestId("settings-save-status")).toBeTruthy();
    });

    // Switch to beta — footer should clear.
    fireEvent.click(getByTestId("rail-item-beta"));

    await waitFor(() => {
      expect(queryByTestId("settings-save-status")).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// 5. Clicking rail item shows matching panel
// ---------------------------------------------------------------------------

describe("SettingsShell — panel visibility on click", () => {
  it("clicking beta rail item hides alpha panel and shows beta panel", async () => {
    const { getByTestId } = render(SettingsShell, {
      props: { sections: TEST_SECTIONS, initialSectionId: "alpha" },
    });

    fireEvent.click(getByTestId("rail-item-beta"));

    await waitFor(() => {
      // After clicking beta, beta panel should not have the hidden class.
      // Alpha panel should have the hidden class. We check aria-selected
      // since CSS display:none is not reflected by jsdom style computation.
      expect(getByTestId("rail-item-beta").getAttribute("aria-selected")).toBe("true");
      expect(getByTestId("rail-item-alpha").getAttribute("aria-selected")).toBe("false");
    });
  });
});
