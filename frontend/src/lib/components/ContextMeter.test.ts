import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import ContextMeter from './ContextMeter.svelte';

afterEach(cleanup);

/** Build a ContextUsageState with sensible defaults so each test only
 * has to name the field it's exercising. */
function ctx(overrides: {
  totalTokens?: number;
  maxTokens?: number;
  percentage?: number;
  isAutoCompactEnabled?: boolean;
}) {
  return {
    totalTokens: overrides.totalTokens ?? 0,
    maxTokens: overrides.maxTokens ?? 200_000,
    percentage: overrides.percentage ?? 0,
    isAutoCompactEnabled: overrides.isAutoCompactEnabled ?? true
  };
}

describe('ContextMeter', () => {
  it('renders nothing when context is null', () => {
    const { container } = render(ContextMeter, { props: { context: null } });
    expect(container.textContent?.trim()).toBe('');
  });

  it('renders token count + percentage in the pill', () => {
    const { getByText } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 12_000, percentage: 6 }) }
    });
    // Token formatter rounds 12_000 → "12.0k"; percentage rounds to "6%".
    expect(getByText(/ctx 12\.0k \(6%\)/)).toBeTruthy();
  });

  it('does not flash below the red band (auto-compact on, 89%)', () => {
    const { container } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 178_000, percentage: 89 }) }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).not.toContain('animate-flash-red');
    // Still orange at 89%.
    expect(pill?.className).toContain('bg-orange-900/60');
  });

  it('flashes at the red-band boundary (auto-compact on, 90%)', () => {
    const { container } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 180_000, percentage: 90 }) }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).toContain('motion-safe:animate-flash-red');
    expect(pill?.className).toContain('bg-red-900/60');
    expect(pill?.getAttribute('title') ?? '').toContain('Auto-compact imminent');
  });

  it('flashes earlier when auto-compact is off (80% boundary)', () => {
    const { container } = render(ContextMeter, {
      props: {
        context: ctx({
          totalTokens: 160_000,
          percentage: 80,
          isAutoCompactEnabled: false
        })
      }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).toContain('motion-safe:animate-flash-red');
    expect(pill?.className).toContain('bg-red-900/60');
    expect(pill?.getAttribute('title') ?? '').toContain('hard cap');
  });

  it('does not flash at 79% with auto-compact off', () => {
    const { container } = render(ContextMeter, {
      props: {
        context: ctx({
          totalTokens: 158_000,
          percentage: 79,
          isAutoCompactEnabled: false
        })
      }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).not.toContain('animate-flash-red');
  });

  it('does not flash at low token counts regardless of raw size', () => {
    // Regression guard: a previous (wrong) implementation flashed at a
    // hardcoded 32K tokens even when the window was nowhere near full.
    // 50k tokens on a 200K window is 25% — nowhere near the red band.
    const { container } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 50_000, percentage: 25 }) }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).not.toContain('animate-flash-red');
  });
});
