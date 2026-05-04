/**
 * Smoke tests for the markdown + syntax-highlight primitives wired
 * in item 2.1. Item 2.3 will extend with conversation-specific
 * sanitization + theme-tracking behavior; these tests lock the v1
 * contract:
 *
 * - `renderMarkdown` runs `marked` against CommonMark + GFM input.
 * - `highlightCode` resolves shiki and returns a `<pre>`-wrapped HTML
 *   string, proving the WASM grammar load works in the test env.
 */
import { describe, expect, it } from "vitest";

import { highlightCode, renderMarkdown } from "../render";

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

describe("highlightCode", () => {
  it("returns shiki-highlighted HTML for a python snippet", async () => {
    const html = await highlightCode("print(1)", "python");
    expect(html).toContain("<pre");
    expect(html).toContain("print");
  });

  it("respects the requested theme", async () => {
    const dark = await highlightCode("x", "javascript", "github-dark");
    const light = await highlightCode("x", "javascript", "github-light");
    expect(dark).not.toEqual(light);
  });
});
