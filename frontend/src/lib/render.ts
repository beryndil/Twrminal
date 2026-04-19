import { marked } from 'marked';
import { createHighlighter, type Highlighter } from 'shiki';

const THEME = 'github-dark';
const LANGS = [
  'python',
  'typescript',
  'javascript',
  'bash',
  'shell',
  'json',
  'html',
  'css',
  'svelte',
  'markdown',
  'yaml',
  'sql',
  'rust',
  'go',
  'toml',
  'diff'
] as const;

let highlighter: Highlighter | null = null;

async function initHighlighter(): Promise<void> {
  highlighter = await createHighlighter({
    themes: [THEME],
    langs: [...LANGS]
  });
}

// Top-level await: pay the WASM cost once at module load so
// renderMarkdown() stays synchronous for Svelte's `{@html ...}`.
await initHighlighter();

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

marked.use({
  renderer: {
    code({ text, lang }): string {
      if (highlighter && lang && (LANGS as readonly string[]).includes(lang)) {
        try {
          return highlighter.codeToHtml(text, { lang, theme: THEME });
        } catch {
          // Unknown lang edge case — fall through to plain <pre><code>.
        }
      }
      return `<pre class="shiki-fallback"><code>${escapeHtml(text)}</code></pre>`;
    }
  }
});

marked.setOptions({
  gfm: true,
  breaks: true
});

/** Renders Markdown text into an HTML string.
 *
 * Content is trusted at the localhost-only boundary in v0.1.x — originates
 * from the user or their own agent. The consumer must still use `{@html}`
 * responsibly.
 */
export function renderMarkdown(text: string): string {
  if (!text) return '';
  return marked.parse(text, { async: false }) as string;
}
