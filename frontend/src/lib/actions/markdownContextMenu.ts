/**
 * Svelte action — event-delegation context-menu handler for markdown-
 * rendered HTML containers.
 *
 * Usage:
 * ```svelte
 * <div use:markdownContextMenu>{@html bodyHtml}</div>
 * ```
 *
 * The action attaches a single ``contextmenu`` listener to the
 * container.  When a right-click occurs, it walks up from the event
 * target to find an element with ``data-cm-target``.  Matching
 * elements open the Bearings context menu with the appropriate target
 * and handlers; non-matching clicks bubble up to any parent
 * ``use:contextMenu`` handler (e.g. the message-level menu).
 *
 * Data attributes injected by :func:`renderMarkdown` via
 * ``BearingsRenderer``:
 *
 * - ``data-cm-target="code_block"`` + optional ``data-cm-lang`` on
 *   ``<pre>`` wrappers.
 * - ``data-cm-target="link"`` on ``<a>`` anchors.
 *
 * Behavior anchors:
 * - ``docs/behavior/context-menus.md`` §"Code block" and §"Link".
 * - ``docs/behavior/context-menus.md`` §"Where context menus do NOT appear" —
 *   plain-text linkified spans inside tool-output blocks are excluded.
 */
import {
  MENU_ACTION_CODE_BLOCK_COPY,
  MENU_ACTION_CODE_BLOCK_COPY_WITH_FENCE,
  MENU_ACTION_CODE_BLOCK_OPEN_IN_EDITOR,
  MENU_ACTION_CODE_BLOCK_SAVE_TO_FILE,
  MENU_ACTION_LINK_COPY_TEXT,
  MENU_ACTION_LINK_COPY_URL,
  MENU_ACTION_LINK_OPEN_IN_EDITOR,
  MENU_ACTION_LINK_OPEN_NEW_TAB,
  MENU_TARGET_CODE_BLOCK,
  MENU_TARGET_LINK,
} from "../config";
import { openMenu } from "../context-menu/store.svelte";
import { shellOpenInEditor } from "../api/shell";
import { showShellOpError } from "../stores/shellOpNotification.svelte";

/**
 * Return the absolute path from a ``file://`` URL or a bare absolute
 * path string, or ``null`` when neither pattern matches.
 */
function fileUrlToPath(href: string): string | null {
  if (href.startsWith("file://")) {
    try {
      return decodeURIComponent(new URL(href).pathname);
    } catch {
      return null;
    }
  }
  if (href.startsWith("/")) return href;
  return null;
}

/**
 * Return ``true`` when the trimmed code content looks like a single
 * absolute file path (no newlines, starts with ``/``).  Used to gate
 * the "Open in editor" action on code blocks that contain a path
 * rather than multi-line source code.
 */
function looksLikePath(code: string): boolean {
  const trimmed = code.trim();
  return trimmed.startsWith("/") && !trimmed.includes("\n");
}

/**
 * Maps common fenced-code language identifiers to file extensions for
 * the "Save to file…" action.  Falls back to ``.txt`` for unknown
 * languages.
 */
const LANG_TO_EXT: Readonly<Record<string, string>> = {
  bash: "sh",
  sh: "sh",
  shell: "sh",
  zsh: "sh",
  fish: "fish",
  python: "py",
  py: "py",
  typescript: "ts",
  ts: "ts",
  javascript: "js",
  js: "js",
  jsx: "jsx",
  tsx: "tsx",
  json: "json",
  html: "html",
  css: "css",
  scss: "scss",
  svelte: "svelte",
  rust: "rs",
  go: "go",
  java: "java",
  kotlin: "kt",
  swift: "swift",
  c: "c",
  cpp: "cpp",
  "c++": "cpp",
  "c#": "cs",
  cs: "cs",
  sql: "sql",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  markdown: "md",
  md: "md",
  diff: "diff",
  xml: "xml",
  dockerfile: "dockerfile",
};

/**
 * Trigger a browser download of ``code`` with a filename derived from
 * ``lang``.  Uses a temporary object URL; the URL is revoked after a
 * short delay to avoid memory leaks.
 */
function saveToFile(code: string, lang: string): void {
  const ext = LANG_TO_EXT[lang.toLowerCase()] ?? "txt";
  const blob = new Blob([code], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `code.${ext}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a generous window so the download can start.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/**
 * Walk up from ``start`` toward ``container`` (exclusive) looking for
 * the first element with a ``data-cm-target`` attribute.  Returns
 * ``null`` when no such element exists in the subtree.
 */
function findCmTarget(start: EventTarget | null, container: HTMLElement): Element | null {
  let node: Element | null = start instanceof Element ? start : null;
  while (node !== null && node !== container) {
    if (node.hasAttribute("data-cm-target")) return node;
    node = node.parentElement;
  }
  return null;
}

/**
 * Svelte action that installs a delegating right-click handler on a
 * container that holds ``{@html …}``-injected Markdown HTML.
 *
 * No parameters required — the action is purely additive (adds one
 * event listener, tears it down on ``destroy``).
 */
export function markdownContextMenu(container: HTMLElement): { destroy: () => void } {
  function handleContextMenu(event: MouseEvent): void {
    const target = findCmTarget(event.target, container);
    if (target === null) return;

    const cmTarget = target.getAttribute("data-cm-target");

    if (cmTarget === "code_block") {
      event.preventDefault();
      event.stopPropagation();

      const codeEl = target.querySelector("code");
      const code = codeEl?.textContent ?? target.textContent ?? "";
      const lang = target.getAttribute("data-cm-lang") ?? "";
      const fence = lang ? `\`\`\`${lang}\n${code}\n\`\`\`` : `\`\`\`\n${code}\n\`\`\``;

      openMenu({
        target: MENU_TARGET_CODE_BLOCK,
        handlers: {
          [MENU_ACTION_CODE_BLOCK_COPY]: () => {
            void navigator.clipboard.writeText(code);
          },
          [MENU_ACTION_CODE_BLOCK_COPY_WITH_FENCE]: () => {
            void navigator.clipboard.writeText(fence);
          },
          [MENU_ACTION_CODE_BLOCK_SAVE_TO_FILE]: () => {
            saveToFile(code, lang);
          },
          // MENU_ACTION_CODE_BLOCK_OPEN_IN_EDITOR — advanced, wired when
          // the code content is a single-line absolute path.
          ...(looksLikePath(code)
            ? {
                [MENU_ACTION_CODE_BLOCK_OPEN_IN_EDITOR]: () => {
                  void shellOpenInEditor(code.trim()).catch((err: unknown) => {
                    const detail =
                      err instanceof Error ? err.message : "unknown error";
                    showShellOpError(detail);
                  });
                },
              }
            : {}),
        },
        data: { lang },
        x: event.clientX,
        y: event.clientY,
        advancedRevealed: event.shiftKey,
        stale: false,
      });
    } else if (cmTarget === "link") {
      event.preventDefault();
      event.stopPropagation();

      // Use .href (absolute) for the URL exposed to the user; fall back
      // to the raw attribute when the element is not an HTMLAnchorElement
      // (shouldn't happen but satisfies strict null checks).
      const href =
        target instanceof HTMLAnchorElement ? target.href : (target.getAttribute("href") ?? "");
      const text = target.textContent ?? "";
      // Resolve local path from file:// URL or bare absolute path once;
      // used to gate the open-in-editor handler below.
      const localHrefPath = fileUrlToPath(href);

      openMenu({
        target: MENU_TARGET_LINK,
        handlers: {
          [MENU_ACTION_LINK_COPY_URL]: () => {
            void navigator.clipboard.writeText(href);
          },
          [MENU_ACTION_LINK_COPY_TEXT]: () => {
            void navigator.clipboard.writeText(text);
          },
          [MENU_ACTION_LINK_OPEN_NEW_TAB]: () => {
            window.open(href, "_blank", "noopener,noreferrer");
          },
          // MENU_ACTION_LINK_OPEN_IN_EDITOR — advanced, wired for file://
          // URLs and bare absolute paths; disabled with tooltip for http(s):// links.
          [MENU_ACTION_LINK_OPEN_IN_EDITOR]:
            localHrefPath !== null
              ? () => {
                  void shellOpenInEditor(localHrefPath).catch((err: unknown) => {
                    const detail =
                      err instanceof Error ? err.message : "unknown error";
                    showShellOpError(detail);
                  });
                }
              : { disabledReason: "Editor open only works for file:// URLs" },
        },
        data: { href, text },
        x: event.clientX,
        y: event.clientY,
        advancedRevealed: event.shiftKey,
        stale: false,
      });
    }
  }

  container.addEventListener("contextmenu", handleContextMenu);

  return {
    destroy(): void {
      container.removeEventListener("contextmenu", handleContextMenu);
    },
  };
}
