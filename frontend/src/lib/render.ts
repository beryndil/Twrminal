/**
 * Markdown + code-highlight rendering primitives for the conversation
 * pane.
 *
 * `docs/behavior/chat.md` §"Conversation rendering" mandates CommonMark +
 * GFM with syntax-highlighted code blocks. Item 2.1 wires the libraries
 * (`marked` + `shiki`) so item 2.3 (Conversation + streaming) consumes
 * the same primitives without re-deciding the parser stack.
 *
 * Syntax-highlighting theme strategy:
 *
 * - `highlightCode` uses shiki's ``createCssVariablesTheme()`` so the
 *   highlighted HTML carries ``var(--shiki-token-*)`` placeholders
 *   rather than baked hex literals.  Per-theme blocks in ``app.css``
 *   (keyed on ``[data-theme]``) supply the actual palette values.
 * - Switching the active Bearings theme therefore re-tints all code
 *   blocks synchronously via a pure DOM-attribute flip — no re-render
 *   of already-highlighted markup is required.  This satisfies
 *   ``docs/behavior/themes.md`` §"What gets re-themed live".
 *
 * G5 — context-menu data attributes:
 *
 * `BearingsRenderer` extends the default marked `Renderer` to inject
 * ``data-cm-target`` attributes on fenced code blocks and links so the
 * delegating action in ``MessageTurn.svelte`` can open the correct
 * per-target context menu:
 *
 * - ``<pre data-cm-target="code_block" [data-cm-lang="<lang>"]>``
 * - ``<a data-cm-target="link" …>``
 */
import { marked, Renderer, type MarkedOptions, type Tokens } from "marked";
import { createCssVariablesTheme, createHighlighter, type Highlighter } from "shiki";

/**
 * Extends the default marked Renderer to stamp ``data-cm-target``
 * attributes on rendered code blocks and links.  The attributes are
 * read by the delegating ``markdownContextMenu`` Svelte action so
 * right-clicking those elements opens the correct Bearings menu.
 */
class BearingsRenderer extends Renderer {
  override code(token: Tokens.Code): string {
    const base = super.code(token);
    const lang = token.lang?.match(/^\S*/)?.[0] ?? "";
    const dataLang = lang ? ` data-cm-lang="${lang}"` : "";
    return base.replace(/^<pre>/, `<pre data-cm-target="code_block"${dataLang}>`);
  }

  override link(token: Tokens.Link): string {
    const base = super.link(token);
    // base returns bare text when cleanUrl returns null; only patch real anchors.
    return base.startsWith("<a ") ? base.replace(/^<a /, '<a data-cm-target="link" ') : base;
  }
}

const BEARINGS_RENDERER = new BearingsRenderer();

const DEFAULT_MARKED_OPTIONS: MarkedOptions = {
  // CommonMark + GFM per behavior/chat.md §"Conversation rendering".
  gfm: true,
  breaks: false,
  renderer: BEARINGS_RENDERER,
};

/**
 * Render a Markdown source string to HTML using marked.
 *
 * Returns a `Promise<string>` because marked may run async extensions
 * (highlight, etc.) in 2.3+; for the 2.1 wiring it resolves
 * synchronously, but consumers that await the promise won't have to
 * change shape.
 */
export async function renderMarkdown(source: string): Promise<string> {
  return marked.parse(source, DEFAULT_MARKED_OPTIONS);
}

/**
 * CSS-variables shiki theme.  Each highlighted span receives an inline
 * ``style="color: var(--shiki-token-*)"`` placeholder; ``app.css``
 * supplies per-theme values under each ``[data-theme]`` selector block.
 * Flipping ``data-theme`` on ``<html>`` is the only step required to
 * re-tint all code blocks — no re-render of existing highlighted HTML.
 */
const CSS_VARS_THEME = createCssVariablesTheme({
  name: "css-variables",
  variablePrefix: "--shiki-",
  variableDefaults: {},
  fontStyle: true,
});

let highlighterPromise: Promise<Highlighter> | null = null;

/**
 * Lazily construct (and cache) a shiki highlighter loaded with the
 * fenced-code-block languages Bearings is most likely to render in v1.
 */
function getHighlighter(): Promise<Highlighter> {
  if (highlighterPromise === null) {
    highlighterPromise = createHighlighter({
      themes: [CSS_VARS_THEME],
      langs: ["bash", "diff", "javascript", "json", "python", "shell", "svelte", "typescript"],
    });
  }
  return highlighterPromise;
}

/**
 * Highlight a code snippet to HTML using shiki's CSS-variables theme.
 *
 * The returned HTML carries ``var(--shiki-token-*)`` placeholders for
 * all token colors and ``var(--shiki-foreground)`` / ``var(--shiki-background)``
 * for the block foreground and background.  Palette values are resolved
 * by the active ``[data-theme]`` CSS block in ``app.css`` — no JS-side
 * theme reading is needed, and already-rendered blocks re-tint for free
 * when the user switches themes.
 */
export async function highlightCode(source: string, lang: string): Promise<string> {
  const hl = await getHighlighter();
  return hl.codeToHtml(source, { lang, theme: "css-variables" });
}
