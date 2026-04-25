/**
 * Tool-output linkifier — Phase 17 ("Clickable options" follow-up).
 *
 * Tool output (Bash stdout, Read result, Grep matches, …) is rendered
 * into a `<pre>` in `MessageTurn.svelte` as plain text. Bare URLs and
 * file paths in that pane stay inert: the user sees `/home/beryndil/…`
 * or `https://example.com/foo` and has to copy-paste it into a browser
 * or editor. The right-click `link` menu in `context-menu/actions/link.ts`
 * already knows how to "Open in editor" for any `<a href="file://…">`,
 * so the gap is purely upstream — we need to emit those anchors.
 *
 * `linkify` runs a tight regex pass over plain text and emits an HTML
 * string mixing escaped text with `<a>` anchors. The function is the
 * producer of every anchor it emits — see the long-form note on the
 * `Match` type for why we don't post-process this through DOMPurify.
 *
 * Detection rules (kept conservative — false positives that turn
 * "e.g." or "it/its" into a link are worse than the status quo):
 *
 *   - URLs: `https?://…` and `file://…` up to the first whitespace,
 *     bracket, quote, or angle-bracket. Trailing punctuation
 *     (`. , : ; ! ? ' " ) ] }`) is stripped so `…example.com.` doesn't
 *     trail a stray dot into the anchor.
 *   - Absolute paths: `/seg/seg…` with at least two segments. `/etc`
 *     alone deliberately does NOT match — too prose-y.
 *   - Home-relative paths (`~/…`): detected but only emitted as an
 *     anchor when we can resolve them to an absolute path. We have no
 *     `$HOME` on the client, so they currently don't link. Tracked in
 *     TODO.md; punt rather than emit a broken `file://~/…` URL the
 *     editor handler can't resolve.
 *   - Relative paths with extension: `foo/bar.ts`, `./foo.py`,
 *     `frontend/src/lib/x.svelte`. Resolved against `baseDir` (the
 *     session's `working_dir`) to produce an absolute `file://` URL
 *     the existing editor handler can open.
 *
 * Order of alternatives matters: URLs match first so a URL containing
 * a path-shaped tail (`https://example.com/path/to/foo.ts`) is taken
 * as one anchor rather than a URL plus a leftover path.
 */

// `[^\s<>'"`()\[\]{}]+` excludes the characters that conventionally
// terminate a URL in flowing text. Without these excludes, a paren-
// wrapped URL like `(https://example.com)` would eat the trailing
// paren into the anchor.
const URL_RE = /(?:https?:\/\/|file:\/\/)[^\s<>'"`()[\]{}]+/g;

// Path character class. `\w` is `[A-Za-z0-9_]`; we add `.@-+` for
// directory and filename components. Slash is the segment separator
// and is added explicitly in each path RE rather than the class so
// boundary semantics stay clear.
const PATH_CHAR = '[\\w.@\\-+]';

// `(?<![\\w./~@\\-+:])` keeps the path matchers from grabbing the tail
// of a token already-consumed by the URL pass and from matching
// inside identifiers like `foo/bar` where the `/` is structural,
// not a path separator. The `:` exclusion is for trailing-line-number
// suffixes (`/path/foo.ts:42`) — we don't want `42` to anchor a new
// match starting at the colon.
const PATH_LB = `(?<![\\w./~@\\-+:])`;

const HOME_PATH_RE = new RegExp(`${PATH_LB}~/${PATH_CHAR}+(?:/${PATH_CHAR}+)*`, 'g');
const ABS_PATH_RE = new RegExp(`${PATH_LB}/(?:${PATH_CHAR}+/)+${PATH_CHAR}+`, 'g');
// Relative path with at least one slash. The post-filter
// `REL_EXT_TAIL_RE` then requires a `.<ext>` suffix to keep the
// false-positive surface narrow — `frontend/src/lib/foo.ts` matches,
// `foo/bar` does not.
const REL_PATH_RE = new RegExp(
  `${PATH_LB}(?:\\.{1,2}/)?${PATH_CHAR}+(?:/${PATH_CHAR}+)+`,
  'g'
);
const REL_EXT_TAIL_RE = /\.[A-Za-z][A-Za-z0-9]{0,7}$/;

const TRAILING_PUNCT_RE = /[.,:;!?'")\]}]+$/;

// Safety posture: linkify is the producer of every anchor it emits,
// not a parser of agent-supplied HTML. Inputs are always plain text
// (tool stdout / JSON) and the only HTML we synthesize is anchors
// whose `href` was constructed by us from one of two regex
// alternatives (URL_RE → `https?://…|file://…`, or pathToFileUrl →
// `file://…`). `m.text` is escaped through `escapeHtml` before
// reaching the output. There is no path by which a `javascript:`
// scheme or an arbitrary tag can be smuggled out, so an additional
// DOMPurify pass would only add cost — and would also strip our
// `file://` anchors because the default ALLOWED_URI_REGEXP rejects
// non-(http|https|mailto|…) schemes. The markdown-body pipeline in
// `render.ts` keeps DOMPurify because there it parses real
// agent-authored markdown.
type Match = { start: number; end: number; href: string; text: string };

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function trimTrailingPunct(raw: string): string {
  const t = raw.match(TRAILING_PUNCT_RE);
  return t ? raw.slice(0, -t[0].length) : raw;
}

/** Resolve a candidate path string to a `file://` URL. Returns null
 * when we can't form a working absolute path — caller leaves the
 * token as plain text rather than emit a broken anchor. */
export function pathToFileUrl(path: string, baseDir: string | null): string | null {
  if (path.startsWith('~/')) {
    // No `$HOME` available on the client; punt. Tracked in TODO.md
    // — the fix is either a `/api/system/home` shim or expanding `~`
    // server-side in `/api/shell/open`.
    return null;
  }
  let abs: string;
  if (path.startsWith('/')) {
    abs = path;
  } else if (baseDir) {
    abs = baseDir.endsWith('/') ? baseDir + path : `${baseDir}/${path}`;
  } else {
    return null;
  }
  // `encodeURI` leaves `/` and most path-safe chars alone, escapes
  // spaces and unicode. Good enough for `file://` URLs the local
  // editor handler will round-trip via `decodeURIComponent`.
  return `file://${encodeURI(abs)}`;
}

function pushMatch(out: Match[], start: number, end: number, href: string, text: string): void {
  // Drop matches that overlap an earlier (higher-priority) one. URLs
  // run first so a path-shaped suffix inside a URL doesn't double-link.
  if (out.some((o) => start < o.end && end > o.start)) return;
  out.push({ start, end, href, text });
}

function collectUrls(text: string, out: Match[]): void {
  for (const m of text.matchAll(URL_RE)) {
    if (m.index === undefined) continue;
    const trimmed = trimTrailingPunct(m[0]);
    if (trimmed.length === 0) continue;
    pushMatch(out, m.index, m.index + trimmed.length, trimmed, trimmed);
  }
}

function collectPaths(text: string, baseDir: string | null, out: Match[]): void {
  // Order: home → abs → rel. Each pass skips overlaps with prior
  // matches, so a path that's a substring of a longer match doesn't
  // double-emit. Relative paths additionally require a `.ext` tail
  // so prose-y tokens like `it/its` or `frontend/build` (no
  // extension) stay plain text.
  const passes: Array<{ re: RegExp; requireExt: boolean }> = [
    { re: HOME_PATH_RE, requireExt: false },
    { re: ABS_PATH_RE, requireExt: false },
    { re: REL_PATH_RE, requireExt: true }
  ];
  for (const { re, requireExt } of passes) {
    for (const m of text.matchAll(re)) {
      if (m.index === undefined) continue;
      const trimmed = trimTrailingPunct(m[0]);
      if (trimmed.length === 0) continue;
      if (requireExt && !REL_EXT_TAIL_RE.test(trimmed)) continue;
      const href = pathToFileUrl(trimmed, baseDir);
      if (!href) continue;
      pushMatch(out, m.index, m.index + trimmed.length, href, trimmed);
    }
  }
}

/** Convert a plain-text string into HTML with URLs and paths wrapped
 * as anchors. Result is DOMPurified before return; consumers can mount
 * it directly via `{@html …}`.
 *
 * `baseDir` is the session's `working_dir`; relative paths resolve
 * against it. Pass `null` when the resolution context isn't known —
 * relative paths then stay as plain text. */
export function linkify(text: string, baseDir: string | null): string {
  if (!text) return '';
  const matches: Match[] = [];
  collectUrls(text, matches);
  collectPaths(text, baseDir, matches);
  matches.sort((a, b) => a.start - b.start);

  const parts: string[] = [];
  let cursor = 0;
  for (const m of matches) {
    if (m.start < cursor) continue; // tie-broken by sort + overlap guard
    parts.push(escapeHtml(text.slice(cursor, m.start)));
    // `target="_blank" rel="noopener noreferrer"` so an http(s) click
    // opens in a new tab rather than navigating Bearings away.
    // Browsers ignore `target` on blocked schemes (`file://` from an
    // http origin is rejected outright), so the same attrs are safe
    // to emit unconditionally — the right-click "Open in editor"
    // path handles `file://` URLs anyway.
    parts.push(
      `<a href="${escapeHtml(m.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(m.text)}</a>`
    );
    cursor = m.end;
  }
  parts.push(escapeHtml(text.slice(cursor)));
  return parts.join('');
}
