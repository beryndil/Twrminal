import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import BearingsMark from './BearingsMark.svelte';

afterEach(cleanup);

describe('BearingsMark', () => {
  it('renders an SVG with the static rings, center dot, and eight markers', () => {
    const { getByTestId } = render(BearingsMark);
    const svg = getByTestId('bearings-mark');
    expect(svg.tagName.toLowerCase()).toBe('svg');
    // Three rings (fill=none) + one center dot + eight markers = 12 circles.
    expect(svg.querySelectorAll('circle').length).toBe(12);
    // The rotating group must exist — that's what the CSS animates.
    expect(svg.querySelector('g.markers')).not.toBeNull();
  });

  it('applies the requested size to width and height', () => {
    const { getByTestId } = render(BearingsMark, { size: 48 });
    const svg = getByTestId('bearings-mark');
    expect(svg.getAttribute('width')).toBe('48');
    expect(svg.getAttribute('height')).toBe('48');
  });

  it('defaults to static (no is-spinning class, data-spinning=false)', () => {
    const { getByTestId } = render(BearingsMark);
    const svg = getByTestId('bearings-mark');
    expect(svg.classList.contains('is-spinning')).toBe(false);
    expect(svg.getAttribute('data-spinning')).toBe('false');
  });

  it('adds is-spinning class and data-spinning=true when spin is set', () => {
    const { getByTestId } = render(BearingsMark, { spin: true });
    const svg = getByTestId('bearings-mark');
    expect(svg.classList.contains('is-spinning')).toBe(true);
    expect(svg.getAttribute('data-spinning')).toBe('true');
  });

  it('omits the background rect by default and includes it when asked', () => {
    const { getByTestId, rerender } = render(BearingsMark);
    expect(getByTestId('bearings-mark').querySelector('rect')).toBeNull();
    rerender({ showBackground: true });
    expect(getByTestId('bearings-mark').querySelector('rect')).not.toBeNull();
  });

  it('is decorative (aria-hidden) when no label is provided', () => {
    const { getByTestId } = render(BearingsMark);
    const svg = getByTestId('bearings-mark');
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(svg.getAttribute('role')).toBeNull();
  });

  it('exposes an accessible label and <title> when one is provided', () => {
    const { getByTestId } = render(BearingsMark, { label: 'Loading templates' });
    const svg = getByTestId('bearings-mark');
    expect(svg.getAttribute('role')).toBe('img');
    expect(svg.getAttribute('aria-label')).toBe('Loading templates');
    expect(svg.getAttribute('aria-hidden')).toBeNull();
    expect(svg.querySelector('title')?.textContent).toBe('Loading templates');
  });
});
