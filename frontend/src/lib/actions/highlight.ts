/**
 * Svelte action that walks text nodes inside `node` and wraps each
 * case-insensitive occurrence of `query` in a `<mark class="search-mark">`
 * element. On each update the previous marks are unwrapped so the DOM
 * stays stable across query changes.
 *
 * Run after the caller's markdown has rendered — no escaping is needed
 * because we only touch text nodes, not tag structure. On the first
 * successful highlight the action also scrolls the first mark into
 * view to help the user land on the right message when jumping from a
 * search hit.
 */
const MARK_CLASS = 'search-mark';

function unwrap(node: HTMLElement): void {
  const existing = node.querySelectorAll(`mark.${MARK_CLASS}`);
  existing.forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parent.normalize();
  });
}

function wrapTextNode(textNode: Text, queryLower: string, len: number): number {
  const text = textNode.textContent ?? '';
  const lower = text.toLowerCase();
  let idx = 0;
  let pos = lower.indexOf(queryLower, idx);
  if (pos < 0) return 0;

  const parent = textNode.parentNode;
  if (!parent) return 0;

  const fragments: Node[] = [];
  let matches = 0;
  while (pos >= 0) {
    if (pos > idx) {
      fragments.push(document.createTextNode(text.slice(idx, pos)));
    }
    const mark = document.createElement('mark');
    mark.className = MARK_CLASS;
    mark.textContent = text.slice(pos, pos + len);
    fragments.push(mark);
    matches += 1;
    idx = pos + len;
    pos = lower.indexOf(queryLower, idx);
  }
  if (idx < text.length) {
    fragments.push(document.createTextNode(text.slice(idx)));
  }
  for (const frag of fragments) parent.insertBefore(frag, textNode);
  parent.removeChild(textNode);
  return matches;
}

function apply(node: HTMLElement, query: string): void {
  unwrap(node);
  const trimmed = query.trim();
  if (!trimmed) return;
  const lower = trimmed.toLowerCase();
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
    acceptNode(candidate: Node): number {
      // Skip empty / whitespace-only nodes; they can't match and
      // wrapping them would pollute the DOM.
      if (!candidate.textContent?.trim()) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  const texts: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    texts.push(current as Text);
    current = walker.nextNode();
  }
  let total = 0;
  for (const t of texts) total += wrapTextNode(t, lower, trimmed.length);
  if (total > 0) {
    const first = node.querySelector(`mark.${MARK_CLASS}`);
    if (first) {
      (first as HTMLElement).scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }
}

export function highlight(node: HTMLElement, query: string) {
  apply(node, query);
  return {
    update(next: string) {
      apply(node, next);
    },
    destroy() {
      // Node is going away — nothing to clean up explicitly.
    }
  };
}
