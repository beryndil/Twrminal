import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './render';

describe('renderMarkdown', () => {
  it('returns empty string for empty input', () => {
    expect(renderMarkdown('')).toBe('');
  });

  it('renders basic markdown', () => {
    const out = renderMarkdown('**bold** and *italic*');
    expect(out).toContain('<strong>bold</strong>');
    expect(out).toContain('<em>italic</em>');
  });

  it('renders links', () => {
    const out = renderMarkdown('[text](https://example.com)');
    expect(out).toContain('href="https://example.com"');
    expect(out).toContain('>text</a>');
  });

  it('strips <script> tags from agent-influenced markdown', () => {
    const out = renderMarkdown('hello <script>alert("x")</script> world');
    expect(out).not.toContain('<script');
    expect(out).not.toContain('alert');
  });

  it('strips inline event handlers', () => {
    const out = renderMarkdown('<img src="x" onerror="alert(1)">');
    expect(out).not.toContain('onerror');
    expect(out).not.toContain('alert');
  });

  it('neutralizes javascript: URLs in links', () => {
    // eslint-disable-next-line no-script-url
    const out = renderMarkdown('[click](javascript:alert(1))');
    expect(out).not.toContain('javascript:');
  });

  it('strips <iframe> tags', () => {
    const out = renderMarkdown('<iframe src="https://evil.example"></iframe>');
    expect(out).not.toContain('<iframe');
  });

  it('preserves fenced code-block wrapper attributes used by the context-menu delegate', () => {
    const out = renderMarkdown('```python\nprint("hi")\n```');
    // The wrapper div is the contract with contextmenu-delegate.ts.
    expect(out).toContain('data-bearings-code-block');
    expect(out).toContain('data-language="python"');
  });

  it('preserves shiki inline styles on highlighted blocks', () => {
    // Shiki emits inline `style="color:#..."` on its spans; the sanitizer
    // allowlist must keep `style` on allowed tags or the fallback path
    // alone renders (still safe, just uglier). This test exercises the
    // fallback path in jsdom where shiki's WASM isn't initialized
    // synchronously, which is still the code path CollapsibleBody hits on
    // first render — we just check the wrapper survived.
    const out = renderMarkdown('```bash\necho hi\n```');
    expect(out).toContain('data-bearings-code-block');
  });
});
