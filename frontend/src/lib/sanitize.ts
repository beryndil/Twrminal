/**
 * Markdown HTML sanitizer — wraps ``isomorphic-dompurify`` with the
 * Bearings policy for ``{@html …}`` insertion in the conversation
 * pane.
 *
 * Why this layer exists:
 *
 * - ``docs/behavior/chat.md`` §"Conversation rendering" mandates
 *   CommonMark + GFM rendering of message bodies. ``marked``'s output
 *   is HTML; rendering that into the DOM via ``{@html}`` without
 *   sanitization is the canonical XSS hole.
 * - Item 2.1 wired ``marked`` and ``shiki`` and left a TODO to add
 *   sanitization in 2.3 (the bubble surface that actually inserts
 *   the rendered HTML into the DOM). This module is that layer.
 *
 * Library choice:
 *
 * - **DOMPurify** is the audited, marked-recommended pairing for
 *   sanitizing HTML in browsers. It's pulled in via the
 *   ``isomorphic-dompurify`` package so vitest's jsdom environment
 *   gets a working sanitizer in tests without a separate codepath.
 * - Alternatives considered: ``sanitize-html`` (Node-targeted; less
 *   ergonomic in a SPA), bespoke ``marked`` renderer overrides
 *   (re-implementing security is a known anti-pattern).
 *
 * Policy:
 *
 * - Allow standard inline + block markdown shapes (headings, links,
 *   lists, code, tables under GFM, blockquotes).
 * - Allow shiki-emitted ``<pre>`` / ``<code>`` with the ``class``
 *   attribute that carries the language token.
 * - On anchor elements, force ``rel="noopener noreferrer"`` and
 *   ``target="_blank"`` for ``http(s)`` URLs to mirror chat.md
 *   §"Conversation rendering" — "rendered as anchors that open in a
 *   new tab".
 * - Allow ``file://`` hrefs so the linkifier's ``data-link-kind="file"``
 *   anchors produced by :func:`linkifyToHtml` survive sanitization.
 *   Bearings is a localhost-only UI; the SPA intercepts ``file://``
 *   clicks via ``data-link-kind`` before the browser can follow them.
 *   ``file://`` is added to the ``ALLOWED_URI_REGEXP`` (DOMPurify
 *   blocks it by default).
 * - Reject all on\* event handlers and ``javascript:`` / ``data:``
 *   URLs (DOMPurify defaults).
 */
import DOMPurify from "isomorphic-dompurify";

import { CHAT_LINK_REL } from "./config";

const ALLOWED_TAGS: readonly string[] = [
  "a",
  "p",
  "br",
  "hr",
  "blockquote",
  "ul",
  "ol",
  "li",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "strong",
  "em",
  "del",
  "code",
  "pre",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "span",
  "div",
  "img",
];

const ALLOWED_ATTR: readonly string[] = [
  "href",
  "title",
  "alt",
  "src",
  "class",
  "data-link-kind",
  "data-language",
  "rel",
  "target",
  "style",
];

let hookInstalled = false;

function installAnchorHook(): void {
  if (hookInstalled) {
    return;
  }
  // ``afterSanitizeAttributes`` runs after DOMPurify has finished its
  // own attribute scrub on each node. We use it to enforce the
  // anchor-policy: external http(s) links open in a new tab with the
  // ``rel`` security attribute; ``file://`` and in-app links keep
  // their attributes as authored.
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (!(node instanceof Element) || node.tagName.toLowerCase() !== "a") {
      return;
    }
    const href = node.getAttribute("href") ?? "";
    if (/^https?:\/\//iu.test(href)) {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", CHAT_LINK_REL);
    }
  });
  hookInstalled = true;
}

/**
 * Extended URI allowlist — DOMPurify's default pattern plus ``file://``
 * so that ``data-link-kind="file"`` anchors emitted by the linkifier
 * survive sanitization. Based on the DOMPurify 3.x default regexp with
 * ``file`` appended to the explicit-scheme alternation.
 *
 * ``file://`` carries no script-execution risk; the worst a malicious
 * ``file://`` link could do is expose the existence of a local path,
 * which is acceptable for a localhost-only developer tool.
 */
const ALLOWED_URI_REGEXP =
  /^(?:(?:(?:f|ht)tps?|mailto|tel|callto|cid|xmpp|file):|[^a-z]|[a-z+.-]+(?:[^a-z+.:-]|$))/iu;

/**
 * Sanitize ``html`` and return the HTML string ready to be inserted
 * via ``{@html}``. The function never throws; on a parser error
 * DOMPurify falls back to the empty string and logs to the console
 * (matching its default behaviour).
 */
export function sanitizeHtml(html: string): string {
  installAnchorHook();
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [...ALLOWED_TAGS],
    ALLOWED_ATTR: [...ALLOWED_ATTR],
    ALLOWED_URI_REGEXP,
    // Disallow ``<form>`` and other interactive shapes by default.
    FORBID_TAGS: ["form", "input", "button", "iframe", "object", "embed", "script", "style"],
    FORBID_ATTR: ["onerror", "onload", "onclick", "onmouseover", "onfocus"],
  });
}
