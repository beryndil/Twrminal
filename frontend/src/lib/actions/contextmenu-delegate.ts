/**
 * Delegating context-menu action — Phase 6.
 *
 * Message bodies render as a single `{@html renderMarkdown(content)}`
 * blob inside `CollapsibleBody`, so individual code blocks and links
 * are part of that raw HTML string — a `use:contextmenu` directive on
 * each one is impossible. This action sits on the same wrapper and
 * walks up from `e.target` at right-click time to identify the nearest
 * interesting descendant:
 *
 *   1. `[data-bearings-code-block]` → CodeBlockTarget.
 *      `renderMarkdown` wraps every fenced block in one of these (see
 *      `$lib/render.ts`). The delegate grabs `textContent` off the
 *      inner `<pre>` / `<code>` so the snapshot matches what the user
 *      can see, not the escaped HTML.
 *   2. `<a href>` → LinkTarget. `href` is whatever marked emitted; the
 *      link handlers treat it as untrusted.
 *   3. No match → fall through to the browser / parent handler.
 *
 * The action stops propagation + preventDefault on 1 and 2, letting
 * the outer article's `use:contextmenu` handle plain-text right-clicks
 * naturally. `Ctrl+Shift+right-click` always defers to the native menu
 * (§2.5) — same rule as `contextmenu.ts`.
 */

import { contextMenu } from '$lib/context-menu/store.svelte';
import { longpress } from '$lib/context-menu/touch';
import type { CodeBlockTarget, LinkTarget } from '$lib/context-menu/types';

export type ContextMenuDelegateBinding = {
  /** Used to scope the captured target to its hosting session /
   * message. Both are nullable because delegate may fire on a
   * streaming assistant turn that has no settled message id yet —
   * handlers treat null as "no context" and skip store lookups. */
  sessionId: string | null;
  messageId: string | null;
};

/** Walk from `el` up to (but not past) `root`, returning the first
 * ancestor that carries `attr`. Returns null when no match is found.
 * Used for the code-block lookup — the `<pre>` and `<code>` sit
 * inside the wrapper `<div data-bearings-code-block>`. */
function closestWithin(
  el: Element | null,
  root: Element,
  attr: string
): HTMLElement | null {
  let node: Element | null = el;
  while (node && node !== root) {
    if (node instanceof HTMLElement && node.hasAttribute(attr)) return node;
    node = node.parentElement;
  }
  return null;
}

/** Same walk, but for anchor elements. Kept separate from
 * `closestWithin` because `<a>` can be tag-matched directly, which is
 * cheaper and less error-prone than attribute sniffing. */
function closestAnchor(el: Element | null, root: Element): HTMLAnchorElement | null {
  let node: Element | null = el;
  while (node && node !== root) {
    if (node instanceof HTMLAnchorElement) return node;
    node = node.parentElement;
  }
  return null;
}

/** Extract the code-block payload from a wrapper element. Returns
 * null if the wrapper is malformed (no `<pre>` / `<code>` descendant) —
 * the caller treats that as "fall through to message menu". */
function readCodeBlock(
  wrapper: HTMLElement,
  binding: ContextMenuDelegateBinding
): CodeBlockTarget | null {
  const codeEl = wrapper.querySelector('code') ?? wrapper.querySelector('pre');
  if (!codeEl) return null;
  const text = codeEl.textContent ?? '';
  const lang = wrapper.getAttribute('data-language');
  return {
    type: 'code_block',
    text,
    language: lang && lang.length > 0 ? lang : null,
    sessionId: binding.sessionId,
    messageId: binding.messageId
  };
}

/** Extract the link payload from an anchor. `text` is the anchor's
 * visible label; for image-only links the `alt` attr is carried
 * instead so copy actions still produce something useful. */
function readLink(
  anchor: HTMLAnchorElement,
  binding: ContextMenuDelegateBinding
): LinkTarget {
  const href = anchor.getAttribute('href') ?? '';
  const visible = (anchor.textContent ?? '').trim();
  const img = visible.length === 0 ? anchor.querySelector('img') : null;
  const text = visible.length > 0 ? visible : (img?.getAttribute('alt') ?? href);
  return {
    type: 'link',
    href,
    text,
    sessionId: binding.sessionId,
    messageId: binding.messageId
  };
}

/** Shared ancestor walk used by both right-click and long-press. The
 * long-press path tracks the initial pointerdown target (not the
 * element the finger released on, which would be wrong for the
 * start-position semantics), so both code paths call this with the
 * Element they want to resolve, NOT directly with the DOM event. */
function resolvePayload(
  startTarget: Element,
  node: HTMLElement,
  binding: ContextMenuDelegateBinding
): CodeBlockTarget | LinkTarget | null {
  const anchor = closestAnchor(startTarget, node);
  if (anchor) return readLink(anchor, binding);
  const wrapper = closestWithin(startTarget, node, 'data-bearings-code-block');
  if (wrapper) return readCodeBlock(wrapper, binding);
  return null;
}

export function contextmenuDelegate(
  node: HTMLElement,
  binding: ContextMenuDelegateBinding
): { update: (next: ContextMenuDelegateBinding) => void; destroy: () => void } {
  let current: ContextMenuDelegateBinding = binding;
  // Element under the pointer at the last pointerdown — stashed here
  // so the long-press callback can walk from the press location, not
  // from wherever the finger happens to have drifted. Reset on every
  // down so a cancelled gesture doesn't poison the next one.
  let pressedOn: Element | null = null;

  function onContextMenu(e: MouseEvent): void {
    // Ctrl+Shift+right-click → let Chrome's native menu fire. Same
    // escape hatch as `$lib/actions/contextmenu.ts`.
    if (e.ctrlKey && e.shiftKey) return;
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;
    const payload = resolvePayload(target, node, current);
    if (!payload) return; // fall through — message menu takes over
    e.preventDefault();
    // `stopImmediatePropagation` (not just `stopPropagation`) so a
    // sibling `use:contextmenu` directive on the SAME element doesn't
    // also fire its handler. Required for the tool-output `<pre>` in
    // `MessageTurn.svelte`, which co-locates this delegate (for
    // anchors inside) with a `tool_call` `use:contextmenu` (for the
    // pre itself). Plain `stopPropagation` only blocks ancestor
    // listeners; same-element ones still fire.
    e.stopImmediatePropagation();
    contextMenu.open(payload, e.clientX, e.clientY, e.shiftKey);
  }

  function onPointerDown(e: PointerEvent): void {
    // Only coarse-pointer presses are relevant — on desktop the
    // contextmenu path already handled it and we don't want to steal
    // primary-click behaviour. `longpress` below performs the same
    // gating, but stashing `pressedOn` is cheap and makes the delegate
    // robust against the user drifting onto a different child mid-press.
    pressedOn = e.target instanceof Element ? e.target : null;
  }

  const longpressHandle = longpress(node, {
    onLongPress: (x, y) => {
      if (!pressedOn) return;
      const payload = resolvePayload(pressedOn, node, current);
      pressedOn = null;
      if (!payload) return; // fall through to outer article menu
      contextMenu.open(payload, x, y, false);
    }
  });

  node.addEventListener('contextmenu', onContextMenu);
  // `capture: true` so we see the pointerdown before the long-press
  // action's own listener — otherwise `pressedOn` would lag by one
  // event and the first long-press after attach would resolve against
  // a stale target.
  node.addEventListener('pointerdown', onPointerDown, { capture: true });

  return {
    update(next: ContextMenuDelegateBinding): void {
      current = next;
    },
    destroy(): void {
      node.removeEventListener('contextmenu', onContextMenu);
      node.removeEventListener('pointerdown', onPointerDown, { capture: true });
      longpressHandle.destroy();
    }
  };
}
