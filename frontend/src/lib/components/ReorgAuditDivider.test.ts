import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ReorgAudit } from '$lib/api';

import ReorgAuditDivider from './ReorgAuditDivider.svelte';

afterEach(() => cleanup());

function audit(overrides: Partial<ReorgAudit> = {}): ReorgAudit {
  return {
    id: 42,
    source_session_id: 'src',
    target_session_id: 'dst',
    target_title_snapshot: 'Beta thread',
    message_count: 3,
    op: 'move',
    created_at: '2026-04-21T15:30:00Z',
    ...overrides
  };
}

describe('ReorgAuditDivider', () => {
  it('renders a "Moved N messages to …" line for a move', () => {
    const { getByTestId, getByText } = render(ReorgAuditDivider, {
      audit: audit({ op: 'move', message_count: 3 })
    });
    expect(getByTestId('reorg-audit-divider')).toBeInTheDocument();
    // Verb + plural + target title land as one block of text.
    expect(getByText(/Moved 3 messages to/)).toBeInTheDocument();
    expect(getByText('"Beta thread"')).toBeInTheDocument();
  });

  it('pluralizes correctly for a single-message move', () => {
    const { getByText } = render(ReorgAuditDivider, {
      audit: audit({ message_count: 1 })
    });
    // Single message → "1 message" not "1 messages".
    expect(getByText(/Moved 1 message to/)).toBeInTheDocument();
  });

  it('uses the right verb for each op', () => {
    const { getByText, unmount } = render(ReorgAuditDivider, {
      audit: audit({ op: 'split' })
    });
    expect(getByText(/Split off 3 messages to/)).toBeInTheDocument();
    unmount();

    const merged = render(ReorgAuditDivider, { audit: audit({ op: 'merge' }) });
    expect(merged.getByText(/Merged 3 messages to/)).toBeInTheDocument();
  });

  it('fires onJumpTo with the target session id when clicked', async () => {
    const onJumpTo = vi.fn();
    const { getByTestId } = render(ReorgAuditDivider, {
      audit: audit({ target_session_id: 'target-abc' }),
      onJumpTo
    });
    await fireEvent.click(getByTestId('reorg-audit-jump'));
    expect(onJumpTo).toHaveBeenCalledExactlyOnceWith('target-abc');
  });

  it('falls back to a non-clickable label when the target was deleted', () => {
    const onJumpTo = vi.fn();
    const { queryByTestId, getByTestId } = render(ReorgAuditDivider, {
      audit: audit({ target_session_id: null, target_title_snapshot: 'gone' }),
      onJumpTo
    });
    // No clickable jump button when the target is gone — rendered as
    // plain italic text with an explicit "(deleted session)" marker.
    expect(queryByTestId('reorg-audit-jump')).toBeNull();
    const deleted = getByTestId('reorg-audit-deleted-target');
    expect(deleted.textContent).toContain('(deleted session)');
    expect(deleted.textContent).toContain('gone');
  });

  it('renders "(untitled)" when the snapshot is null', () => {
    const { getByText } = render(ReorgAuditDivider, {
      audit: audit({ target_title_snapshot: null })
    });
    expect(getByText('"(untitled)"')).toBeInTheDocument();
  });

  it('tags the DOM with audit metadata for downstream queries', () => {
    const { getByTestId } = render(ReorgAuditDivider, {
      audit: audit({ id: 77, op: 'split' })
    });
    const el = getByTestId('reorg-audit-divider');
    expect(el.getAttribute('data-audit-id')).toBe('77');
    expect(el.getAttribute('data-audit-op')).toBe('split');
  });
});
