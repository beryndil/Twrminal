/**
 * Snapshot + structural tests for the five icon components in
 * ``frontend/src/lib/components/icons/``.
 *
 * Each component is a pure presentational SVG with no store access;
 * tests verify:
 *   1. Snapshot — locks the rendered HTML against unintended drift.
 *   2. Key structural invariants — ring count, petal count, etc.
 *   3. State-driven behaviour — ``loading`` animation, ``severity``
 *      colour classes.
 *
 * Acceptance criteria cross-reference: gap-cycle-01-009 §acceptance_criteria.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import BearingsMark from "../BearingsMark.svelte";
import ClaudeMark from "../ClaudeMark.svelte";
import IconX from "../IconX.svelte";
import SeverityShield from "../SeverityShield.svelte";
import TagIcon from "../TagIcon.svelte";

// ---------------------------------------------------------------------------
// BearingsMark
// ---------------------------------------------------------------------------

describe("BearingsMark", () => {
  it("matches snapshot (static, loading=false)", () => {
    const { container } = render(BearingsMark);
    expect(container).toMatchSnapshot();
  });

  it("renders three concentric ring circles", () => {
    const { getAllByTestId, getByTestId } = render(BearingsMark);
    const svg = getByTestId("bearings-mark");
    // Three <circle> elements with stroke (rings) + eight <circle> (dots).
    // The rings do not carry a testid; count via querySelectorAll.
    const allCircles = svg.querySelectorAll("circle");
    // 3 rings + 8 cardinal dots = 11
    expect(allCircles).toHaveLength(11);
    // Eight cardinal dot markers carry the testid.
    expect(getAllByTestId("bearings-mark-cardinal")).toHaveLength(8);
  });

  it("does NOT add the sweep class when loading=false", () => {
    const { getAllByTestId } = render(BearingsMark, { props: { loading: false } });
    const dots = getAllByTestId("bearings-mark-cardinal");
    for (const dot of dots) {
      expect(dot).not.toHaveClass("bearings-mark-cardinal--sweep");
    }
  });

  it("adds the sweep class to every cardinal dot when loading=true", () => {
    const { getAllByTestId } = render(BearingsMark, { props: { loading: true } });
    const dots = getAllByTestId("bearings-mark-cardinal");
    expect(dots).toHaveLength(8);
    for (const dot of dots) {
      expect(dot).toHaveClass("bearings-mark-cardinal--sweep");
    }
  });

  it("applies staggered animation-delay when loading=true", () => {
    const { getAllByTestId } = render(BearingsMark, { props: { loading: true } });
    const dots = getAllByTestId("bearings-mark-cardinal");
    // First dot: 0 ms, last dot: 700 ms (7 of 8 × 100 ms per step).
    expect(dots[0]).toHaveStyle("animation-delay: 0ms");
    expect(dots[7]).toHaveStyle("animation-delay: 700ms");
  });

  it("forwards the size prop to width/height", () => {
    const { getByTestId } = render(BearingsMark, { props: { size: 32 } });
    const svg = getByTestId("bearings-mark");
    expect(svg).toHaveAttribute("width", "32");
    expect(svg).toHaveAttribute("height", "32");
  });

  it("forwards the class prop to the root svg", () => {
    const { getByTestId } = render(BearingsMark, { props: { class: "text-accent" } });
    expect(getByTestId("bearings-mark")).toHaveClass("text-accent");
  });
});

// ---------------------------------------------------------------------------
// SeverityShield
// ---------------------------------------------------------------------------

describe("SeverityShield", () => {
  it("matches snapshot (severity=low)", () => {
    const { container } = render(SeverityShield, { props: { severity: "low" } });
    expect(container).toMatchSnapshot();
  });

  it.each([
    ["low", "fill-green-400"],
    ["medium", "fill-yellow-400"],
    ["high", "fill-orange-500"],
    ["critical", "fill-red-500"],
  ] as const)("applies %s → %s fill class", (severity: string, expectedClass: string) => {
    const { getByTestId } = render(SeverityShield, { props: { severity } });
    const shield = getByTestId("severity-shield");
    const path = shield.querySelector("path");
    expect(path).toHaveClass(expectedClass);
  });

  it("applies fill-fg-muted for an unknown severity", () => {
    const { getByTestId } = render(SeverityShield, { props: { severity: "unknown" } });
    const shield = getByTestId("severity-shield");
    expect(shield.querySelector("path")).toHaveClass("fill-fg-muted");
  });

  it("renders the severity value in the aria-label", () => {
    const { getByTestId } = render(SeverityShield, { props: { severity: "high" } });
    expect(getByTestId("severity-shield")).toHaveAttribute("aria-label", "Severity: high");
  });

  it("exposes the severity level as a data attribute", () => {
    const { getByTestId } = render(SeverityShield, { props: { severity: "critical" } });
    expect(getByTestId("severity-shield")).toHaveAttribute("data-severity", "critical");
  });

  it("forwards the size prop", () => {
    const { getByTestId } = render(SeverityShield, { props: { severity: "low", size: 20 } });
    const svg = getByTestId("severity-shield");
    expect(svg).toHaveAttribute("width", "20");
    expect(svg).toHaveAttribute("height", "20");
  });
});

// ---------------------------------------------------------------------------
// ClaudeMark
// ---------------------------------------------------------------------------

describe("ClaudeMark", () => {
  it("matches snapshot", () => {
    const { container } = render(ClaudeMark);
    expect(container).toMatchSnapshot();
  });

  it("renders exactly five petals", () => {
    const { getAllByTestId } = render(ClaudeMark);
    expect(getAllByTestId("claude-mark-petal")).toHaveLength(5);
  });

  it("petals are evenly distributed (72° rotation increments)", () => {
    const { getAllByTestId } = render(ClaudeMark);
    const petals = getAllByTestId("claude-mark-petal");
    const rotations = petals.map((el) => {
      const transform = el.getAttribute("transform") ?? "";
      const match = /rotate\((\d+)/.exec(transform);
      return match ? parseInt(match[1], 10) : -1;
    });
    expect(rotations).toEqual([0, 72, 144, 216, 288]);
  });

  it("forwards the size prop", () => {
    const { getByTestId } = render(ClaudeMark, { props: { size: 32 } });
    const svg = getByTestId("claude-mark");
    expect(svg).toHaveAttribute("width", "32");
    expect(svg).toHaveAttribute("height", "32");
  });

  it("forwards the class prop", () => {
    const { getByTestId } = render(ClaudeMark, { props: { class: "opacity-50" } });
    expect(getByTestId("claude-mark")).toHaveClass("opacity-50");
  });
});

// ---------------------------------------------------------------------------
// IconX
// ---------------------------------------------------------------------------

describe("IconX", () => {
  it("matches snapshot", () => {
    const { container } = render(IconX);
    expect(container).toMatchSnapshot();
  });

  it("renders two crossing lines", () => {
    const { getByTestId } = render(IconX);
    const svg = getByTestId("icon-x");
    expect(svg.querySelectorAll("line")).toHaveLength(2);
  });

  it("is aria-hidden (decorative — callers supply accessible labels)", () => {
    const { getByTestId } = render(IconX);
    expect(getByTestId("icon-x")).toHaveAttribute("aria-hidden", "true");
  });

  it("forwards the size prop", () => {
    const { getByTestId } = render(IconX, { props: { size: 20 } });
    const svg = getByTestId("icon-x");
    expect(svg).toHaveAttribute("width", "20");
    expect(svg).toHaveAttribute("height", "20");
  });

  it("forwards the class prop", () => {
    const { getByTestId } = render(IconX, { props: { class: "text-red-400" } });
    expect(getByTestId("icon-x")).toHaveClass("text-red-400");
  });
});

// ---------------------------------------------------------------------------
// TagIcon
// ---------------------------------------------------------------------------

describe("TagIcon", () => {
  it("matches snapshot", () => {
    const { container } = render(TagIcon);
    expect(container).toMatchSnapshot();
  });

  it("renders a tag-body path and a hole circle", () => {
    const { getByTestId } = render(TagIcon);
    const svg = getByTestId("tag-icon");
    expect(svg.querySelectorAll("path")).toHaveLength(1);
    expect(svg.querySelectorAll("circle")).toHaveLength(1);
  });

  it("is aria-hidden (decorative)", () => {
    const { getByTestId } = render(TagIcon);
    expect(getByTestId("tag-icon")).toHaveAttribute("aria-hidden", "true");
  });

  it("forwards the size prop", () => {
    const { getByTestId } = render(TagIcon, { props: { size: 20 } });
    const svg = getByTestId("tag-icon");
    expect(svg).toHaveAttribute("width", "20");
    expect(svg).toHaveAttribute("height", "20");
  });

  it("forwards the class prop", () => {
    const { getByTestId } = render(TagIcon, { props: { class: "text-fg-muted" } });
    expect(getByTestId("tag-icon")).toHaveClass("text-fg-muted");
  });
});
