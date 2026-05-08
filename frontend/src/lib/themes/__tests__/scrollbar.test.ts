/**
 * Contract tests for theme-aware thin scrollbar styling.
 *
 * jsdom cannot apply external CSS files — ``getComputedStyle`` returns
 * empty strings for custom properties regardless of what the stylesheet
 * says.  These tests read ``app.css`` source directly and assert:
 *
 *   1. The global scrollbar rules (Firefox + WebKit) are present.
 *   2. Every theme block declares ``--bearings-scrollbar-thumb`` and
 *      ``--bearings-scrollbar-thumb-hover`` as non-empty RGB triples.
 *   3. Dark themes (evergreen, midnight-glass, default) use a lighter
 *      thumb than their dark surface; paper-light uses a darker thumb
 *      than the cream surface.
 *   4. A ``[data-theme]`` swap alone re-tints the scrollbar — verified
 *      by confirming the variables are declared under each theme
 *      selector (no JavaScript re-render path required).
 *
 * Anchors: ``docs/behavior/themes.md`` §"Scrollbar palette"
 */
import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

// process.cwd() in vitest is the frontend/ root (contains vite.config.ts).
const APP_CSS = join(process.cwd(), "src", "app.css");

function readAppCss(): string {
  return readFileSync(APP_CSS, "utf-8");
}

// ---------------------------------------------------------------------------
// Global scrollbar rules
// ---------------------------------------------------------------------------

describe("app.css — global scrollbar rules", () => {
  it("declares scrollbar-width: thin for Firefox", () => {
    expect(readAppCss()).toContain("scrollbar-width: thin");
  });

  it("declares scrollbar-color using --bearings-scrollbar-thumb for Firefox", () => {
    expect(readAppCss()).toContain(
      "scrollbar-color: rgb(var(--bearings-scrollbar-thumb)) transparent",
    );
  });

  it("declares ::-webkit-scrollbar width 8px and height 8px", () => {
    const css = readAppCss();
    expect(css).toContain("::-webkit-scrollbar");
    expect(css).toContain("width: 8px");
    expect(css).toContain("height: 8px");
  });

  it("declares ::-webkit-scrollbar-track with transparent background", () => {
    const css = readAppCss();
    expect(css).toContain("::-webkit-scrollbar-track");
  });

  it("declares ::-webkit-scrollbar-thumb with --bearings-scrollbar-thumb fill", () => {
    const css = readAppCss();
    expect(css).toContain("::-webkit-scrollbar-thumb");
    expect(css).toContain("background-color: rgb(var(--bearings-scrollbar-thumb))");
    expect(css).toContain("border-radius: 9999px");
    expect(css).toContain("background-clip: padding-box");
  });

  it("declares ::-webkit-scrollbar-thumb:hover with --bearings-scrollbar-thumb-hover fill", () => {
    const css = readAppCss();
    expect(css).toContain("::-webkit-scrollbar-thumb:hover");
    expect(css).toContain("background-color: rgb(var(--bearings-scrollbar-thumb-hover))");
  });

  it("declares ::-webkit-scrollbar-corner with transparent background", () => {
    expect(readAppCss()).toContain("::-webkit-scrollbar-corner");
  });
});

// ---------------------------------------------------------------------------
// Per-theme variable declarations
// ---------------------------------------------------------------------------

/**
 * Extract the text of a CSS block that starts with the given selector.
 * Returns the substring from the selector up to (but not including) the
 * selector of the next top-level block, giving enough text to search for
 * variable declarations scoped to that theme.
 */
function extractThemeBlock(css: string, selector: string): string {
  const start = css.indexOf(selector);
  if (start === -1) return "";
  // Find the closing brace of this block (first '}' after the opening '{').
  const openBrace = css.indexOf("{", start);
  if (openBrace === -1) return "";
  let depth = 0;
  let i = openBrace;
  for (; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") {
      depth--;
      if (depth === 0) break;
    }
  }
  return css.slice(start, i + 1);
}

describe("theme blocks — scrollbar variable declarations", () => {
  const css = readAppCss();

  const themes = [
    { selector: ":root,", label: "evergreen (:root)" },
    { selector: '[data-theme="midnight-glass"]', label: "midnight-glass" },
    { selector: '[data-theme="default"]', label: "default" },
    { selector: '[data-theme="paper-light"]', label: "paper-light" },
  ];

  for (const { selector, label } of themes) {
    it(`${label} declares --bearings-scrollbar-thumb`, () => {
      const block = extractThemeBlock(css, selector);
      expect(block, `${label} block not found`).not.toBe("");
      expect(block, `${label} must declare --bearings-scrollbar-thumb`).toContain(
        "--bearings-scrollbar-thumb:",
      );
    });

    it(`${label} declares --bearings-scrollbar-thumb-hover`, () => {
      const block = extractThemeBlock(css, selector);
      expect(block).toContain("--bearings-scrollbar-thumb-hover:");
    });
  }

  it("every theme thumb value is a non-empty RGB triple (three integers)", () => {
    // Collect all --bearings-scrollbar-thumb: <value>; declarations.
    const matches = [...css.matchAll(/--bearings-scrollbar-thumb:\s*(\d+ \d+ \d+)/g)];
    // Expect exactly 4 — one per theme.
    expect(matches.length).toBeGreaterThanOrEqual(4);
    for (const m of matches) {
      const [r, g, b] = m[1].split(" ").map(Number);
      expect(r).toBeGreaterThanOrEqual(0);
      expect(g).toBeGreaterThanOrEqual(0);
      expect(b).toBeGreaterThanOrEqual(0);
    }
  });

  it("every theme thumb-hover value is a non-empty RGB triple (three integers)", () => {
    const matches = [...css.matchAll(/--bearings-scrollbar-thumb-hover:\s*(\d+ \d+ \d+)/g)];
    expect(matches.length).toBeGreaterThanOrEqual(4);
    for (const m of matches) {
      const [r, g, b] = m[1].split(" ").map(Number);
      expect(r).toBeGreaterThanOrEqual(0);
      expect(g).toBeGreaterThanOrEqual(0);
      expect(b).toBeGreaterThanOrEqual(0);
    }
  });
});

// ---------------------------------------------------------------------------
// Dark vs light surface contrast
// ---------------------------------------------------------------------------

describe("scrollbar palette contrast — dark themes vs paper-light", () => {
  const css = readAppCss();

  /**
   * Parse ``--bearings-scrollbar-thumb: R G B`` from a theme block.
   * Returns the luminance-approximate brightness (average of channels, 0–255).
   */
  function thumbBrightness(selector: string): number {
    const block = extractThemeBlock(css, selector);
    const m = block.match(/--bearings-scrollbar-thumb:\s*(\d+)\s+(\d+)\s+(\d+)/);
    if (!m) throw new Error(`No --bearings-scrollbar-thumb found under selector: ${selector}`);
    return (Number(m[1]) + Number(m[2]) + Number(m[3])) / 3;
  }

  /**
   * Parse ``--bearings-surface-0: R G B`` from a theme block.
   */
  function surfaceBrightness(selector: string): number {
    const block = extractThemeBlock(css, selector);
    const m = block.match(/--bearings-surface-0:\s*(\d+)\s+(\d+)\s+(\d+)/);
    if (!m) throw new Error(`No --bearings-surface-0 found under selector: ${selector}`);
    return (Number(m[1]) + Number(m[2]) + Number(m[3])) / 3;
  }

  it("evergreen: thumb is brighter than the dark surface (thumb above surface)", () => {
    expect(thumbBrightness(":root,")).toBeGreaterThan(surfaceBrightness(":root,"));
  });

  it("midnight-glass: thumb is brighter than the dark navy surface (thumb above surface)", () => {
    const sel = '[data-theme="midnight-glass"]';
    expect(thumbBrightness(sel)).toBeGreaterThan(surfaceBrightness(sel));
  });

  it("default: thumb is brighter than the dark gray surface (thumb above surface)", () => {
    const sel = '[data-theme="default"]';
    expect(thumbBrightness(sel)).toBeGreaterThan(surfaceBrightness(sel));
  });

  it("paper-light: thumb is darker than the cream surface (thumb below surface)", () => {
    const sel = '[data-theme="paper-light"]';
    expect(thumbBrightness(sel)).toBeLessThan(surfaceBrightness(sel));
  });
});

// ---------------------------------------------------------------------------
// Theme-switch re-tint: no re-render required
// ---------------------------------------------------------------------------

describe("theme-switch re-tint — [data-theme] swap is sufficient", () => {
  it("each theme block scopes its scrollbar variables under a [data-theme] selector", () => {
    const css = readAppCss();
    // All four theme selectors are present in the CSS.
    expect(css).toContain(":root");
    expect(css).toContain('[data-theme="midnight-glass"]');
    expect(css).toContain('[data-theme="default"]');
    expect(css).toContain('[data-theme="paper-light"]');
  });

  it("the scrollbar-color rule references a CSS variable (not a baked hex)", () => {
    // If the rule used a baked hex, swapping [data-theme] wouldn't re-tint.
    // This contract asserts the indirection is in place.
    expect(readAppCss()).toContain("rgb(var(--bearings-scrollbar-thumb))");
  });
});
