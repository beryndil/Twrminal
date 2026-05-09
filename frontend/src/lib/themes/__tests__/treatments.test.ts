/**
 * Contract tests for per-theme CSS treatment files.
 *
 * jsdom cannot apply external CSS files — ``getComputedStyle`` returns
 * empty strings for ``backdrop-filter`` and ``background`` regardless of
 * what the stylesheet says.  These tests instead read the CSS source
 * files directly and assert that the right properties appear under the
 * right ``[data-theme]`` selectors.
 *
 * This is a source-level contract: "midnight-glass.css declares
 * backdrop-filter on aside; evergreen.css does not."  That contract is
 * sufficient to verify the data-theme→treatment mapping that the
 * acceptance criteria require.
 *
 * Anchors: ``docs/behavior/themes.md`` §"Per-theme visual treatments"
 */
import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

// Resolve to frontend/src/lib/themes/ relative to the vitest working
// directory (frontend/).  process.cwd() in vitest is the directory that
// contains vite.config.ts — i.e. the frontend/ root.
const THEMES_DIR = join(process.cwd(), "src", "lib", "themes");
const APP_CSS_PATH = join(process.cwd(), "src", "app.css");
const CONVERSATION_SVELTE_PATH = join(
  process.cwd(),
  "src",
  "lib",
  "components",
  "conversation",
  "Conversation.svelte",
);

function readAppCss(): string {
  return readFileSync(APP_CSS_PATH, "utf-8");
}

function readThemeCss(name: string): string {
  return readFileSync(join(THEMES_DIR, `${name}.css`), "utf-8");
}

// ---------------------------------------------------------------------------
// Midnight Glass — glass panels + aurora wash
// ---------------------------------------------------------------------------

describe("midnight-glass.css — glass + aurora treatment", () => {
  it("contains radial-gradient aurora body wash", () => {
    expect(readThemeCss("midnight-glass")).toContain("radial-gradient");
  });

  it("contains background-attachment: fixed for depth effect", () => {
    expect(readThemeCss("midnight-glass")).toContain("background-attachment: fixed");
  });

  it("contains backdrop-filter on aside panels", () => {
    expect(readThemeCss("midnight-glass")).toContain("backdrop-filter");
  });

  it('is scoped under [data-theme="midnight-glass"]', () => {
    expect(readThemeCss("midnight-glass")).toContain('[data-theme="midnight-glass"]');
  });

  it("contains prefers-reduced-motion guard for animated button transitions", () => {
    expect(readThemeCss("midnight-glass")).toContain("prefers-reduced-motion");
  });

  it("contains transition-duration: 0.01ms inside the reduced-motion block", () => {
    const css = readThemeCss("midnight-glass");
    const rmBlock = css.slice(css.indexOf("prefers-reduced-motion"));
    expect(rmBlock).toContain("0.01ms");
  });
});

// ---------------------------------------------------------------------------
// Evergreen — flat (no glass, no aurora)
// ---------------------------------------------------------------------------

describe("evergreen.css — flat surface, no glass", () => {
  it("does NOT contain backdrop-filter", () => {
    expect(readThemeCss("evergreen")).not.toContain("backdrop-filter");
  });

  it("does NOT contain radial-gradient aurora", () => {
    expect(readThemeCss("evergreen")).not.toContain("radial-gradient");
  });

  it("contains a subtle body gradient (linear-gradient)", () => {
    expect(readThemeCss("evergreen")).toContain("linear-gradient");
  });

  it('is scoped under [data-theme="evergreen"] or :root', () => {
    const css = readThemeCss("evergreen");
    expect(css.includes('[data-theme="evergreen"]') || css.includes(":root")).toBe(true);
  });

  it("contains a selected-row accent treatment (nav-link--active)", () => {
    expect(readThemeCss("evergreen")).toContain("nav-link--active");
  });
});

// ---------------------------------------------------------------------------
// Paper Light — flat (no glass, no aurora)
// ---------------------------------------------------------------------------

describe("paper-light.css — flat surface, no glass", () => {
  it("does NOT contain backdrop-filter", () => {
    expect(readThemeCss("paper-light")).not.toContain("backdrop-filter");
  });

  it("does NOT contain radial-gradient aurora", () => {
    expect(readThemeCss("paper-light")).not.toContain("radial-gradient");
  });

  it('is scoped under [data-theme="paper-light"]', () => {
    expect(readThemeCss("paper-light")).toContain('[data-theme="paper-light"]');
  });

  it("contains a selected-row accent treatment (nav-link--active)", () => {
    expect(readThemeCss("paper-light")).toContain("nav-link--active");
  });
});

// ---------------------------------------------------------------------------
// Default — flat (no glass, no aurora)
// ---------------------------------------------------------------------------

describe("default.css — flat surface, no glass", () => {
  it("does NOT contain backdrop-filter", () => {
    expect(readThemeCss("default")).not.toContain("backdrop-filter");
  });

  it("does NOT contain radial-gradient aurora", () => {
    expect(readThemeCss("default")).not.toContain("radial-gradient");
  });

  it('is scoped under [data-theme="default"]', () => {
    expect(readThemeCss("default")).toContain('[data-theme="default"]');
  });

  it("contains a selected-row accent treatment (nav-link--active)", () => {
    expect(readThemeCss("default")).toContain("nav-link--active");
  });
});

// ---------------------------------------------------------------------------
// Cross-theme distinguishability
// ---------------------------------------------------------------------------

describe("all four themes are visually distinguishable", () => {
  const THEME_NAMES = ["midnight-glass", "evergreen", "paper-light", "default"] as const;

  it("each treatment file exists and is non-empty", () => {
    for (const name of THEME_NAMES) {
      const css = readThemeCss(name);
      expect(css.length, `${name}.css should be non-empty`).toBeGreaterThan(100);
    }
  });

  it("midnight-glass is the only theme with glass panel effects", () => {
    const glass = readThemeCss("midnight-glass");
    expect(glass).toContain("backdrop-filter");

    for (const name of THEME_NAMES.filter((n) => n !== "midnight-glass")) {
      expect(readThemeCss(name), `${name}.css must not contain backdrop-filter`).not.toContain(
        "backdrop-filter",
      );
    }
  });

  it("midnight-glass is the only theme with aurora radial-gradients", () => {
    const glass = readThemeCss("midnight-glass");
    expect(glass).toContain("radial-gradient");

    for (const name of THEME_NAMES.filter((n) => n !== "midnight-glass")) {
      expect(
        readThemeCss(name),
        `${name}.css must not contain radial-gradient aurora`,
      ).not.toContain("radial-gradient");
    }
  });

  it("each flat theme has its own selected-row colour (distinct from each other)", () => {
    // Pull the inset bar colour from each flat theme's nav-link--active block.
    // Not an exact pixel assertion — just proves each file has a unique accent value.
    const evergreenCss = readThemeCss("evergreen");
    const paperLightCss = readThemeCss("paper-light");
    const defaultCss = readThemeCss("default");

    // Evergreen: emerald rgb(37, 136, 70)
    expect(evergreenCss).toContain("rgb(37, 136, 70)");
    // Paper Light: Prussian blue rgb(25, 91, 168)
    expect(paperLightCss).toContain("rgb(25, 91, 168)");
    // Default: sky blue rgb(96, 165, 250)
    expect(defaultCss).toContain("rgb(96, 165, 250)");
  });
});

// ---------------------------------------------------------------------------
// app.css structural invariants (theme-sweep-001, theme-sweep-004)
// ---------------------------------------------------------------------------

describe("app.css — @import placement (theme-sweep-001)", () => {
  it("all four @import directives precede the first @tailwind directive", () => {
    const lines = readAppCss().split("\n");
    const firstImportLine = lines.findIndex((l) => l.startsWith("@import "));
    const firstTailwindLine = lines.findIndex((l) => l.startsWith("@tailwind "));
    expect(firstImportLine, "@import must exist").toBeGreaterThanOrEqual(0);
    expect(firstTailwindLine, "@tailwind must exist").toBeGreaterThanOrEqual(0);
    expect(firstImportLine).toBeLessThan(firstTailwindLine);
  });

  it("imports all four treatment files", () => {
    const css = readAppCss();
    expect(css).toContain('@import "./lib/themes/midnight-glass.css"');
    expect(css).toContain('@import "./lib/themes/evergreen.css"');
    expect(css).toContain('@import "./lib/themes/paper-light.css"');
    expect(css).toContain('@import "./lib/themes/default.css"');
  });
});

describe("app.css — semantic state tokens per theme (theme-sweep-004)", () => {
  const STATE_TOKENS = [
    "--bearings-accent-info",
    "--bearings-accent-ok",
    "--bearings-accent-warn",
    "--bearings-accent-error",
  ] as const;
  const THEMES = ["evergreen", "midnight-glass", "default", "paper-light"] as const;

  for (const token of STATE_TOKENS) {
    it(`${token} is defined in each theme block`, () => {
      const css = readAppCss();
      for (const theme of THEMES) {
        const anchor = theme === "evergreen" ? ":root," : `[data-theme="${theme}"]`;
        const blockStart = css.indexOf(anchor);
        expect(blockStart, `${theme} block must exist`).toBeGreaterThanOrEqual(0);
        const blockEnd = css.indexOf("}", blockStart);
        const block = css.slice(blockStart, blockEnd);
        expect(block, `${token} must be in ${theme} block`).toContain(token);
      }
    });
  }
});

// ---------------------------------------------------------------------------
// Conversation.svelte error bubble — no Tailwind dark: modifier
// (theme-sweep-002)
// ---------------------------------------------------------------------------

describe("Conversation.svelte error bubble — theme-sweep-002", () => {
  function readConversation(): string {
    return readFileSync(CONVERSATION_SVELTE_PATH, "utf-8");
  }

  it("does not use dark: Tailwind modifier near the conversation-error element", () => {
    const src = readConversation();
    const idx = src.indexOf('data-testid="conversation-error"');
    expect(idx, "conversation-error testid must exist").toBeGreaterThanOrEqual(0);
    const block = src.slice(Math.max(0, idx - 300), idx + 500);
    expect(block).not.toMatch(/\bdark:/);
  });

  it("uses theme-token error classes (bg-error or text-error)", () => {
    const src = readConversation();
    const idx = src.indexOf('data-testid="conversation-error"');
    const block = src.slice(Math.max(0, idx - 300), idx + 500);
    expect(block).toMatch(/\b(bg-error|text-error)/);
  });
});
