/**
 * Contract tests for the global reduced-motion guard (gap-cycle-14-001).
 *
 * jsdom cannot apply external CSS files — ``getComputedStyle`` ignores
 * ``@media`` queries on stylesheets entirely.  These tests instead read
 * ``app.css`` source text directly and assert that the required rules are
 * present.
 *
 * This is a source-level contract: "app.css declares the
 * prefers-reduced-motion block with the four suppression properties."
 * That is sufficient to verify the CSS guard without a headless browser.
 *
 * Anchor: ``docs/behavior/themes.md`` §"Reduced motion"
 */
import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

// Resolve to frontend/src/app.css relative to the vitest working directory
// (frontend/).  process.cwd() in vitest is the directory that contains
// vite.config.ts — i.e. the frontend/ root.
const APP_CSS_PATH = join(process.cwd(), "src", "app.css");

function readAppCss(): string {
  return readFileSync(APP_CSS_PATH, "utf-8");
}

describe("app.css — global reduced-motion guard", () => {
  it("declares a @media (prefers-reduced-motion: reduce) block", () => {
    expect(readAppCss()).toContain("prefers-reduced-motion: reduce");
  });

  it("targets *, *::before, *::after inside the block", () => {
    const css = readAppCss();
    const rmIndex = css.indexOf("prefers-reduced-motion: reduce");
    const rmBlock = css.slice(rmIndex);
    expect(rmBlock).toMatch(/\*\s*,\s*\*::before\s*,\s*\*::after/);
  });

  it("sets animation-duration: 0.01ms !important inside the block", () => {
    const css = readAppCss();
    const rmIndex = css.indexOf("prefers-reduced-motion: reduce");
    const rmBlock = css.slice(rmIndex);
    expect(rmBlock).toContain("animation-duration: 0.01ms !important");
  });

  it("sets animation-iteration-count: 1 !important inside the block", () => {
    const css = readAppCss();
    const rmIndex = css.indexOf("prefers-reduced-motion: reduce");
    const rmBlock = css.slice(rmIndex);
    expect(rmBlock).toContain("animation-iteration-count: 1 !important");
  });

  it("sets transition-duration: 0.01ms !important inside the block", () => {
    const css = readAppCss();
    const rmIndex = css.indexOf("prefers-reduced-motion: reduce");
    const rmBlock = css.slice(rmIndex);
    expect(rmBlock).toContain("transition-duration: 0.01ms !important");
  });

  it("sets scroll-behavior: auto !important inside the block", () => {
    const css = readAppCss();
    const rmIndex = css.indexOf("prefers-reduced-motion: reduce");
    const rmBlock = css.slice(rmIndex);
    expect(rmBlock).toContain("scroll-behavior: auto !important");
  });

  it("the block appears outside any [data-theme] selector (global scope)", () => {
    const css = readAppCss();
    const rmIndex = css.indexOf("@media (prefers-reduced-motion: reduce)");
    // The block must not appear inside a [data-theme] block.
    // We verify this by checking no [data-theme] selector appears between
    // the last closing brace before the block and the block itself.
    const precedingCss = css.slice(0, rmIndex);
    // Count open/close braces up to the block — if balanced, we are at top level.
    const opens = (precedingCss.match(/\{/g) ?? []).length;
    const closes = (precedingCss.match(/\}/g) ?? []).length;
    expect(opens).toBe(closes);
  });
});
