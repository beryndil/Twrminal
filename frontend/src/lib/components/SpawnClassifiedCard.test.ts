/**
 * Wave 3 — SpawnClassifiedCard component tests.
 *
 * Covers:
 *   - loading spinner renders when loading=true
 *   - single_chat shape: badge, reason, title + description preview
 *   - multi_chat shape: badge + N item list
 *   - checklist shape: badge + N label list with checkbox glyphs
 *   - Apply button calls onApply with the result
 *   - Cancel button calls onCancel
 *   - shape badge has correct label text per shape
 */
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { SpawnClassifyResult } from '$lib/api/sessions';
import SpawnClassifiedCard from './SpawnClassifiedCard.svelte';

afterEach(() => cleanup());

const SINGLE: SpawnClassifyResult = {
  shape: 'single_chat',
  reason: 'One coherent reply.',
  suggested_single: { title: 'My title', description: 'My description here.' },
  suggested_multi: null,
  suggested_checklist: null,
};

const MULTI: SpawnClassifyResult = {
  shape: 'multi_chat',
  reason: 'Three independent approaches.',
  suggested_single: null,
  suggested_multi: [
    { title: 'Approach A', description: 'da' },
    { title: 'Approach B', description: 'db' },
    { title: 'Approach C', description: 'dc' },
  ],
  suggested_checklist: null,
};

const CHECKLIST: SpawnClassifyResult = {
  shape: 'checklist',
  reason: 'Sequential migration steps.',
  suggested_single: null,
  suggested_multi: null,
  suggested_checklist: [
    { label: 'Step 1: Install', notes: 'run npm install' },
    { label: 'Step 2: Migrate', notes: 'run db migrate' },
  ],
};

describe('SpawnClassifiedCard', () => {
  it('shows loading spinner when loading=true', () => {
    const { getByTestId } = render(SpawnClassifiedCard, {
      props: { result: null, loading: true, onApply: vi.fn(), onCancel: vi.fn() },
    });
    expect(getByTestId('classify-loading')).toBeTruthy();
  });

  it('hides spinner when loading=false', () => {
    const { queryByTestId } = render(SpawnClassifiedCard, {
      props: { result: SINGLE, loading: false, onApply: vi.fn(), onCancel: vi.fn() },
    });
    expect(queryByTestId('classify-loading')).toBeNull();
  });

  it('renders single_chat shape with badge, reason, title, description', () => {
    const { getByTestId, getByText } = render(SpawnClassifiedCard, {
      props: { result: SINGLE, loading: false, onApply: vi.fn(), onCancel: vi.fn() },
    });
    expect(getByTestId('shape-badge').textContent).toContain('Single chat');
    expect(getByTestId('classify-reason').textContent).toBe('One coherent reply.');
    const preview = getByTestId('preview-single');
    expect(preview.textContent).toContain('My title');
    expect(preview.textContent).toContain('My description here.');
    getByText('Apply');
  });

  it('renders multi_chat shape with N items', () => {
    const { getByTestId } = render(SpawnClassifiedCard, {
      props: { result: MULTI, loading: false, onApply: vi.fn(), onCancel: vi.fn() },
    });
    expect(getByTestId('shape-badge').textContent).toContain('Multiple chats');
    const preview = getByTestId('preview-multi');
    expect(preview.textContent).toContain('Approach A');
    expect(preview.textContent).toContain('Approach B');
    expect(preview.textContent).toContain('Approach C');
  });

  it('renders checklist shape with item labels', () => {
    const { getByTestId } = render(SpawnClassifiedCard, {
      props: { result: CHECKLIST, loading: false, onApply: vi.fn(), onCancel: vi.fn() },
    });
    expect(getByTestId('shape-badge').textContent).toContain('Checklist');
    const preview = getByTestId('preview-checklist');
    expect(preview.textContent).toContain('Step 1: Install');
    expect(preview.textContent).toContain('Step 2: Migrate');
    // Each item has a checkbox glyph
    expect(preview.textContent).toContain('☐');
  });

  it('calls onApply with the result when Apply is clicked', async () => {
    const onApply = vi.fn();
    const { getByTestId } = render(SpawnClassifiedCard, {
      props: { result: SINGLE, loading: false, onApply, onCancel: vi.fn() },
    });
    await fireEvent.click(getByTestId('classify-apply'));
    expect(onApply).toHaveBeenCalledOnce();
    expect(onApply).toHaveBeenCalledWith(SINGLE);
  });

  it('calls onCancel when Cancel is clicked', async () => {
    const onCancel = vi.fn();
    const { getByTestId } = render(SpawnClassifiedCard, {
      props: { result: SINGLE, loading: false, onApply: vi.fn(), onCancel },
    });
    await fireEvent.click(getByTestId('classify-cancel'));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
