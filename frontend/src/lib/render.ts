/**
 * Markdown + code-highlight rendering primitives for the conversation
 * pane and vault reader.
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
 *
 * Vault linkifier (F7-RT-01):
 *
 * ``renderMarkdownWithLinkifier`` extends the standard renderer with two
 * inline marked extensions so the vault reading panel auto-links bare
 * ``https?://`` URLs and ``ses_<hex>`` session-id references per
 * ``docs/behavior/vault.md`` §"When the user opens the vault" and
 * §"Tag association".  Uses a private :class:`Marked` instance so the
 * global ``marked`` singleton stays unmodified.
 */
import { Marked, marked, Renderer, type MarkedOptions, type Tokens } from "marked";
import type { Highlighter } from "shiki";
import { CHAT_LINK_REL } from "./config";

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

// ---------------------------------------------------------------------------
// Vault linkifier extensions (F7-RT-01)
// ---------------------------------------------------------------------------

/**
 * Escape HTML entities in ``text`` for safe interpolation into HTML
 * content or attribute slots.  Used by the vault-linkifier extension
 * renderers which produce raw HTML strings outside Svelte's template
 * escaping layer.
 */
function escVaultHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/**
 * Matches a bare ``https?://`` URL at the start of the tokenizer input.
 * Stops at whitespace, angle brackets, quotes, or parentheses so a URL
 * embedded in prose ("see https://x.com.") doesn't slurp trailing
 * punctuation. The ``start`` hook handles the forward-scan.
 */
const VAULT_BARE_URL_RE = /^https?:\/\/[^\s<>"'()]+/;

/**
 * Matches a Bearings session ID at the start of the tokenizer input.
 * Accepts the canonical ``ses_<hex>`` form used throughout the UI (e.g.
 * ``ses_19a99d945d553189176f00be1afb3e6b``).  Plain 32-hex strings are
 * intentionally excluded to avoid false positives on commit hashes and
 * other hex-shaped values in plan files.
 */
const VAULT_SESSION_ID_RE = /^ses_[0-9a-f]+/;

/**
 * Private :class:`Marked` instance with vault-specific inline
 * extensions.  Constructed once at module load; kept separate from the
 * global ``marked`` singleton so conversation rendering is unaffected.
 */
const VAULT_MARKED: Marked = (() => {
  const instance = new Marked();
  // setOptions (not the constructor or use()) is the correct API for
  // applying a renderer class instance on a Marked instance — the
  // constructor and use() paths do not wire the class methods correctly
  // in marked v14.
  instance.setOptions({ gfm: true, breaks: false, renderer: BEARINGS_RENDERER });
  instance.use({
    extensions: [
      {
        name: "vaultBareUrl",
        level: "inline" as const,
        start(src: string): number | undefined {
          const idx = src.search(/https?:\/\//);
          return idx >= 0 ? idx : undefined;
        },
        tokenizer(src: string): Tokens.Generic | undefined {
          const match = VAULT_BARE_URL_RE.exec(src);
          if (match === null) return undefined;
          return { type: "vaultBareUrl", raw: match[0], href: match[0], text: match[0] };
        },
        renderer(token: Tokens.Generic): string {
          const href = escVaultHtml(String(token.href));
          const text = escVaultHtml(String(token.text));
          return `<a href="${href}" target="_blank" rel="${CHAT_LINK_REL}" data-cm-target="link">${text}</a>`;
        },
      },
      {
        name: "vaultSessionId",
        level: "inline" as const,
        start(src: string): number | undefined {
          const idx = src.search(/ses_[0-9a-f]/);
          return idx >= 0 ? idx : undefined;
        },
        tokenizer(src: string): Tokens.Generic | undefined {
          const match = VAULT_SESSION_ID_RE.exec(src);
          if (match === null) return undefined;
          return { type: "vaultSessionId", raw: match[0], id: match[0], text: match[0] };
        },
        renderer(token: Tokens.Generic): string {
          const id = escVaultHtml(String(token.id));
          const text = escVaultHtml(String(token.text));
          return `<a href="/sessions/${id}" data-cm-target="link">${text}</a>`;
        },
      },
    ],
  });
  return instance;
})();

/**
 * Render a Markdown source string to HTML with the vault linkifier
 * applied (F7-RT-01).
 *
 * Identical to :func:`renderMarkdown` except two additional inline
 * extensions are active:
 *
 * - **vaultBareUrl** — bare ``https?://`` URLs become ``<a
 *   target="_blank">`` anchors (vault.md §"When the user opens the
 *   vault" — "the body renders as Markdown … including the linkifier").
 * - **vaultSessionId** — ``ses_<hex>`` session-id references become
 *   ``<a href="/sessions/<id>">`` anchors for in-app navigation
 *   (vault.md §"Tag association").
 *
 * Used by :class:`VaultPanel` for the reading-panel body.  Chat
 * conversation rendering uses :func:`renderMarkdown`; the linkifier
 * there lives in ``linkify.ts`` and operates on plaintext turns before
 * they reach marked.
 */
export async function renderMarkdownWithLinkifier(source: string): Promise<string> {
  return VAULT_MARKED.parse(source);
}

let highlighterPromise: Promise<Highlighter> | null = null;

/**
 * Lazily construct (and cache) a shiki highlighter loaded with the
 * fenced-code-block languages Bearings is most likely to render in v1.
 *
 * Uses a dynamic ``import("shiki")`` so the shiki module is code-split
 * from the initial app bundle — it only downloads when the first code
 * block is encountered (conversation pane or vault reader).  Every page
 * that does not render a fenced code block pays zero shiki parse cost at
 * startup, which directly reduces Time-to-Interactive / TBT across the
 * sidebar, settings, vault, new-session, and analytics routes.
 *
 * The CSS-variables theme is constructed inside the dynamic import so that
 * ``createCssVariablesTheme`` (also from shiki) is never referenced at
 * module load time.  The resulting :class:`Highlighter` is cached via the
 * module-level ``highlighterPromise`` so subsequent calls are free.
 */
function getHighlighter(): Promise<Highlighter> {
  if (highlighterPromise === null) {
    highlighterPromise = import("shiki").then(({ createCssVariablesTheme, createHighlighter }) => {
      /**
       * CSS-variables shiki theme.  Each highlighted span receives an inline
       * ``style="color: var(--shiki-token-*)"`` placeholder; ``app.css``
       * supplies per-theme values under each ``[data-theme]`` selector block.
       * Flipping ``data-theme`` on ``<html>`` is the only step required to
       * re-tint all code blocks — no re-render of existing highlighted HTML.
       */
      const cssVarsTheme = createCssVariablesTheme({
        name: "css-variables",
        variablePrefix: "--shiki-",
        variableDefaults: {},
        fontStyle: true,
      });
      return createHighlighter({
        themes: [cssVarsTheme],
        langs: ["bash", "diff", "javascript", "json", "python", "shell", "svelte", "typescript"],
      });
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
