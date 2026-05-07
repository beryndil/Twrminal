/**
 * Tests for the markdown + syntax-highlight rendering primitives.
 *
 * `renderMarkdown` contract:
 * - Runs `marked` against CommonMark + GFM input.
 * - `BearingsRenderer` stamps `data-cm-target` on code blocks and links.
 *
 * `highlightCode` contract (gap-cycle-04-002):
 * - Uses shiki's CSS-variables theme so every highlighted span carries
 *   ``var(--shiki-token-*)`` placeholders rather than baked hex literals.
 * - Per-theme CSS blocks in ``app.css`` supply the actual palette values
 *   keyed on ``[data-theme]``; switching themes is therefore a pure DOM
 *   attribute flip — no re-render of already-highlighted blocks required.
 */
import { afterEach, describe, expect, it } from "vitest";

import { THEME_EVERGREEN, THEME_PAPER_LIGHT } from "../config";
import { highlightCode, renderMarkdown } from "../render";
import { _resetForTests } from "../themes/store.svelte";

describe("renderMarkdown", () => {
  it("renders bold inline as <strong>", async () => {
    const html = await renderMarkdown("Hello **world**.");
    expect(html).toContain("<strong>world</strong>");
  });

  it("renders fenced code blocks with data-cm-target", async () => {
    const html = await renderMarkdown("```\nhi\n```");
    expect(html).toContain('data-cm-target="code_block"');
    expect(html).toContain("hi");
  });

  it("adds data-cm-lang on fenced blocks with a language identifier", async () => {
    const html = await renderMarkdown("```python\nprint(1)\n```");
    expect(html).toContain('data-cm-target="code_block"');
    expect(html).toContain('data-cm-lang="python"');
  });

  it("adds data-cm-target on Markdown links", async () => {
    const html = await renderMarkdown("[click](https://example.com)");
    expect(html).toContain('data-cm-target="link"');
    expect(html).toContain('href="https://example.com"');
  });
});

afterEach(() => {
  _resetForTests(THEME_EVERGREEN);
});

describe("highlightCode", () => {
  it("returns shiki-highlighted HTML for a python snippet", async () => {
    const html = await highlightCode("print(1)", "python");
    expect(html).toContain("<pre");
    expect(html).toContain("print");
  });

  it("output carries CSS-var foreground and token placeholders, not baked hex", async () => {
    // paper-light is active — without the CSS-vars approach this would bake
    // dark-on-dark shiki colors onto a light background.
    _resetForTests(THEME_PAPER_LIGHT);
    const html = await highlightCode("x = 1\n# comment", "python");

    // The CSS-variables theme embeds placeholders resolved by [data-theme] CSS.
    expect(html).toContain("var(--shiki-foreground)");
    expect(html).toContain("var(--shiki-token-");

    // Ensure no github-dark baked hex leaks through (would be dark-on-light).
    // github-dark comment color is a known sentinel; its presence proves the old path.
    expect(html).not.toContain("#6e7781");
  });

  it("output is identical across themes — re-tinting is CSS-only, no re-render needed", async () => {
    // The same source highlighted under paper-light and evergreen must produce
    // identical HTML structure: theme palette is resolved by CSS custom properties,
    // not baked at highlight time.  Already-rendered blocks re-tint for free when
    // data-theme flips on <html>.
    _resetForTests(THEME_PAPER_LIGHT);
    const htmlPaperLight = await highlightCode("x = 1", "python");

    _resetForTests(THEME_EVERGREEN);
    const htmlEvergreen = await highlightCode("x = 1", "python");

    expect(htmlPaperLight).toEqual(htmlEvergreen);
    // Both carry the same CSS-var placeholders; the CSS layer resolves the difference.
    expect(htmlEvergreen).toContain("var(--shiki-foreground)");
  });
});
