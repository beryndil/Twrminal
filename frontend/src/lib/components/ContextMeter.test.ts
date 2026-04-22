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

  it('renders token count + percentage under the degradation threshold', () => {
    const { getByText } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 12_000, percentage: 6 }) }
    });
    // Token formatter rounds 12_000 → "12.0k"; percentage rounds to "6%".
    expect(getByText(/ctx 12\.0k \(6%\)/)).toBeTruthy();
  });

  it('does not flash when tokens are below 32K even if percentage is moderate', () => {
    const { container } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 31_999, percentage: 16 }) }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).not.toContain('animate-flash-red');
  });

  it('flashes red at exactly 32K tokens', () => {
    const { container } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 32_000, percentage: 16 }) }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).toContain('motion-safe:animate-flash-red');
    expect(pill?.className).toContain('bg-red-900/60');
    expect(pill?.getAttribute('title') ?? '').toContain('Past 32K');
  });

  it('flashes red well past 32K and overrides the percentage band', () => {
    // 45% on its own would normally be amber; the 32K override forces red.
    const { container } = render(ContextMeter, {
      props: { context: ctx({ totalTokens: 90_000, percentage: 45 }) }
    });
    const pill = container.querySelector('span');
    expect(pill?.className).toContain('motion-safe:animate-flash-red');
    expect(pill?.className).not.toContain('bg-amber-900/60');
  });
});
