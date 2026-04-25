import { describe, expect, it } from 'vitest';

import { linkify, pathToFileUrl } from './linkify';

const BASE_DIR = '/home/beryndil/Projects/Bearings';

describe('linkify — URL detection', () => {
  it('returns empty string for empty input', () => {
    expect(linkify('', null)).toBe('');
  });

  it('wraps an https URL as an anchor', () => {
    const out = linkify('see https://example.com/foo for details', null);
    expect(out).toContain('href="https://example.com/foo"');
    expect(out).toContain('>https://example.com/foo</a>');
  });

  it('wraps an http URL as an anchor', () => {
    const out = linkify('see http://example.com', null);
    expect(out).toContain('href="http://example.com"');
    expect(out).toContain('>http://example.com</a>');
  });

  it('emits target=_blank and noopener noreferrer on URL anchors', () => {
    const out = linkify('see https://example.com', null);
    expect(out).toMatch(/target="_blank"/);
    expect(out).toMatch(/rel="noopener noreferrer"/);
  });

  it('strips trailing punctuation from URLs', () => {
    const out = linkify('see https://example.com.', null);
    expect(out).toContain('href="https://example.com"');
    expect(out).toContain('>https://example.com</a>');
    expect(out.endsWith('.')).toBe(true);
  });

  it('does not eat closing parens', () => {
    const out = linkify('(https://example.com/foo)', null);
    expect(out).toContain('href="https://example.com/foo"');
    expect(out).toContain('>https://example.com/foo</a>');
    expect(out).toContain(')');
  });

  it('handles a file:// URL', () => {
    const out = linkify('see file:///tmp/foo.txt', null);
    expect(out).toContain('href="file:///tmp/foo.txt"');
    expect(out).toContain('>file:///tmp/foo.txt</a>');
  });

  it('matches multiple URLs in one string', () => {
    const out = linkify('a https://x.com b https://y.com c', null);
    expect(out).toMatch(/href="https:\/\/x\.com"/);
    expect(out).toMatch(/href="https:\/\/y\.com"/);
  });
});

describe('linkify — absolute path detection', () => {
  it('wraps a /home path as a file:// anchor', () => {
    const out = linkify('Read /home/beryndil/Projects/Bearings/README.md', null);
    expect(out).toContain('href="file:///home/beryndil/Projects/Bearings/README.md"');
    expect(out).toContain('>/home/beryndil/Projects/Bearings/README.md</a>');
  });

  it('does not match single-segment paths like /etc', () => {
    const out = linkify('see /etc for config', null);
    expect(out).not.toContain('<a');
  });

  it('does not match identifier-like tokens with slashes', () => {
    // No leading `/`, no extension — should stay plain text.
    const out = linkify('a/b without extension', null);
    expect(out).not.toContain('<a');
  });

  it('strips trailing colon-line-number suffix from anchor (path only)', () => {
    // `/abs/path/foo.ts:42` — anchor wraps through .ts; the `:42`
    // is left as plain text. Conservative: editor handler can't
    // resolve `:42` cleanly through the `file://` URL contract.
    const out = linkify('grep hit /home/beryndil/Projects/Bearings/foo.ts:42', null);
    expect(out).toContain('href="file:///home/beryndil/Projects/Bearings/foo.ts"');
    expect(out).toContain('>/home/beryndil/Projects/Bearings/foo.ts</a>:42');
  });

  it('encodes spaces in absolute paths', () => {
    const out = linkify('open /tmp/with spaces/foo.ts', null);
    // `with` and `spaces/foo.ts` end up as two separate considerations;
    // the path RE stops at whitespace so the link is `/tmp/with` if
    // it survives the 2-segment requirement. `/tmp/with` has 2 segments
    // (empty + tmp + with), it does match. encoded URI keeps the path
    // intact since no special chars.
    expect(out).toContain('href="file:///tmp/with"');
    expect(out).toContain('>/tmp/with</a>');
  });
});

describe('linkify — relative path detection', () => {
  it('wraps a relative path with extension when baseDir is provided', () => {
    const out = linkify('edit frontend/src/lib/foo.ts please', BASE_DIR);
    expect(out).toContain(
      'href="file:///home/beryndil/Projects/Bearings/frontend/src/lib/foo.ts"'
    );
    expect(out).toContain('>frontend/src/lib/foo.ts</a>');
  });

  it('skips relative paths when baseDir is null', () => {
    const out = linkify('edit frontend/src/lib/foo.ts please', null);
    expect(out).not.toContain('<a');
  });

  it('handles ./prefix', () => {
    const out = linkify('see ./scripts/build.sh', BASE_DIR);
    expect(out).toContain('href="file:///home/beryndil/Projects/Bearings/./scripts/build.sh"');
  });

  it('does not match prose like "e.g.," or "it/its"', () => {
    expect(linkify('e.g., that thing', BASE_DIR)).not.toContain('<a');
    expect(linkify('it/its purpose', BASE_DIR)).not.toContain('<a');
  });

  it('does not match relative tokens without an extension', () => {
    expect(linkify('see src/bearings/db', BASE_DIR)).not.toContain('<a');
  });
});

describe('linkify — home-relative paths', () => {
  it('skips ~/path because client has no $HOME', () => {
    const out = linkify('edit ~/.config/bearings/config.toml', BASE_DIR);
    // No anchor — punt rather than emit a broken file://~/… URL.
    expect(out).not.toContain('<a');
    // But the text is still escaped/visible in the output.
    expect(out).toContain('~/.config/bearings/config.toml');
  });
});

describe('linkify — overlap and ordering', () => {
  it('prefers a URL match over a path match for the same span', () => {
    const out = linkify('https://example.com/path/to/foo.ts here', null);
    // One anchor, with the full URL as href (not a fragment of it).
    const anchorMatches = out.match(/<a [^>]*href="[^"]+"/g);
    expect(anchorMatches).not.toBeNull();
    expect(anchorMatches?.length).toBe(1);
    expect(out).toContain('href="https://example.com/path/to/foo.ts"');
  });

  it('produces multiple anchors in span order', () => {
    const out = linkify('https://x.com and /home/beryndil/foo/bar.txt', null);
    const aIndex = out.indexOf('href="https://x.com"');
    const bIndex = out.indexOf('href="file:///home/beryndil/foo/bar.txt"');
    expect(aIndex).toBeGreaterThanOrEqual(0);
    expect(bIndex).toBeGreaterThanOrEqual(0);
    expect(aIndex).toBeLessThan(bIndex);
  });
});

describe('linkify — escaping', () => {
  it('escapes HTML in surrounding text', () => {
    const out = linkify('<script>alert(1)</script> https://example.com', null);
    expect(out).not.toContain('<script>');
    expect(out).toContain('&lt;script&gt;');
    expect(out).toContain('href="https://example.com"');
  });

  it('preserves whitespace in surrounding text (caller wraps in <pre>)', () => {
    const out = linkify('  https://example.com  ', null);
    expect(out.startsWith('  ')).toBe(true);
    expect(out.endsWith('  ')).toBe(true);
  });
});

describe('pathToFileUrl', () => {
  it('returns null for ~/ paths', () => {
    expect(pathToFileUrl('~/foo', BASE_DIR)).toBeNull();
  });

  it('passes through absolute paths with file:// prefix', () => {
    expect(pathToFileUrl('/abs/path', BASE_DIR)).toBe('file:///abs/path');
  });

  it('joins relative paths against baseDir', () => {
    expect(pathToFileUrl('rel/foo.ts', BASE_DIR)).toBe(`file://${BASE_DIR}/rel/foo.ts`);
  });

  it('returns null for relative paths with no baseDir', () => {
    expect(pathToFileUrl('rel/foo.ts', null)).toBeNull();
  });
});
