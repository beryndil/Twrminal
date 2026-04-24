import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ApprovalRequestEvent } from '$lib/api';
import AskUserQuestionModal from './AskUserQuestionModal.svelte';

afterEach(cleanup);

// Shape AskUserQuestion actually puts on the wire — the modal parses
// `request.input.questions` and renders each entry. Test helper keeps
// the call sites terse and makes it easy to tweak per-test fixtures.
function fakeRequest(
  overrides: Partial<ApprovalRequestEvent> = {}
): ApprovalRequestEvent {
  return {
    type: 'approval_request',
    session_id: 'sess-1',
    request_id: 'req-1',
    tool_name: 'AskUserQuestion',
    input: {
      questions: [
        {
          question: 'What should I focus on?',
          header: 'Focus',
          multiSelect: false,
          options: [
            { label: 'Orient', description: 'Report where we are' },
            { label: 'Review', description: 'Check git status' }
          ]
        }
      ]
    },
    tool_use_id: 'tu_ask',
    ...overrides
  };
}

describe('AskUserQuestionModal', () => {
  it('renders each question header, text, and option label/description', () => {
    const { getByText } = render(AskUserQuestionModal, {
      request: fakeRequest(),
      connected: true,
      onRespond: vi.fn(() => true)
    });
    expect(getByText('Focus')).toBeInTheDocument();
    expect(getByText('What should I focus on?')).toBeInTheDocument();
    expect(getByText('Orient')).toBeInTheDocument();
    expect(getByText('Report where we are')).toBeInTheDocument();
    expect(getByText('Review')).toBeInTheDocument();
  });

  it('keeps Submit disabled until a question is answered', () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      request: fakeRequest(),
      connected: true,
      onRespond: vi.fn(() => true)
    });
    // No selection + no "Other" text → required answer missing →
    // Submit must stay off. Prevents an empty-answer allow that would
    // look identical to the "Approve" bug we're fixing.
    expect(getByTestId('ask-submit')).toBeDisabled();
  });

  it('submit with a selection sends allow with updated_input.answers', async () => {
    // Explicit signature so `mock.calls[0][3]` is typed as the
    // updated-input argument instead of being narrowed to an empty
    // tuple by mock's default inference.
    const onRespond = vi.fn(
      (
        _id: string,
        _decision: 'allow' | 'deny',
        _reason?: string,
        _updatedInput?: Record<string, unknown>
      ) => true
    );
    const { getByTestId } = render(AskUserQuestionModal, {
      request: fakeRequest(),
      connected: true,
      onRespond
    });
    await fireEvent.click(getByTestId('ask-option-0-0'));
    await fireEvent.click(getByTestId('ask-submit'));
    // Must pass through both the original input AND the collected
    // answers keyed by question text. The SDK re-invokes the tool
    // with this payload and the tool echoes answers to the agent.
    expect(onRespond).toHaveBeenCalledWith('req-1', 'allow', undefined, {
      questions: [
        {
          question: 'What should I focus on?',
          header: 'Focus',
          multiSelect: false,
          options: [
            { label: 'Orient', description: 'Report where we are' },
            { label: 'Review', description: 'Check git status' }
          ]
        }
      ],
      answers: { 'What should I focus on?': 'Orient' }
    });
  });

  it('"Other" free-text overrides option selection in the submitted answer', async () => {
    // Explicit signature so `mock.calls[0][3]` is typed as the
    // updated-input argument instead of being narrowed to an empty
    // tuple by mock's default inference.
    const onRespond = vi.fn(
      (
        _id: string,
        _decision: 'allow' | 'deny',
        _reason?: string,
        _updatedInput?: Record<string, unknown>
      ) => true
    );
    const { getByTestId } = render(AskUserQuestionModal, {
      request: fakeRequest(),
      connected: true,
      onRespond
    });
    // Click a pre-baked option first to prove that a typed "Other"
    // wins. Users commonly scan options, then decide none fit and
    // type their own — the typed text is the explicit signal.
    await fireEvent.click(getByTestId('ask-option-0-0'));
    await fireEvent.input(getByTestId('ask-other-0'), {
      target: { value: 'Something else entirely' }
    });
    await fireEvent.click(getByTestId('ask-submit'));
    const call = onRespond.mock.calls[0];
    expect(call[3]).toMatchObject({
      answers: { 'What should I focus on?': 'Something else entirely' }
    });
  });

  it('multiSelect joins selected labels with commas and appends Other', async () => {
    // Explicit signature so `mock.calls[0][3]` is typed as the
    // updated-input argument instead of being narrowed to an empty
    // tuple by mock's default inference.
    const onRespond = vi.fn(
      (
        _id: string,
        _decision: 'allow' | 'deny',
        _reason?: string,
        _updatedInput?: Record<string, unknown>
      ) => true
    );
    const { getByTestId } = render(AskUserQuestionModal, {
      request: fakeRequest({
        input: {
          questions: [
            {
              question: 'Which features?',
              header: 'Features',
              multiSelect: true,
              options: [
                { label: 'Alpha', description: '' },
                { label: 'Beta', description: '' }
              ]
            }
          ]
        }
      }),
      connected: true,
      onRespond
    });
    await fireEvent.click(getByTestId('ask-option-0-0'));
    await fireEvent.click(getByTestId('ask-option-0-1'));
    await fireEvent.input(getByTestId('ask-other-0'), {
      target: { value: 'Gamma' }
    });
    await fireEvent.click(getByTestId('ask-submit'));
    expect(onRespond.mock.calls[0][3]).toMatchObject({
      answers: { 'Which features?': 'Alpha, Beta, Gamma' }
    });
  });

  it('Cancel calls onRespond with deny and a reason', async () => {
    // Explicit signature so `mock.calls[0][3]` is typed as the
    // updated-input argument instead of being narrowed to an empty
    // tuple by mock's default inference.
    const onRespond = vi.fn(
      (
        _id: string,
        _decision: 'allow' | 'deny',
        _reason?: string,
        _updatedInput?: Record<string, unknown>
      ) => true
    );
    const { getByTestId } = render(AskUserQuestionModal, {
      request: fakeRequest(),
      connected: true,
      onRespond
    });
    await fireEvent.click(getByTestId('ask-cancel'));
    expect(onRespond).toHaveBeenCalledWith('req-1', 'deny', 'user cancelled');
  });

  it('disables controls when the socket is disconnected', () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      request: fakeRequest(),
      connected: false,
      onRespond: vi.fn(() => true)
    });
    expect(getByTestId('ask-submit')).toBeDisabled();
    expect(getByTestId('ask-cancel')).toBeDisabled();
  });

  it('swallows Escape so the modal cannot be dismissed without a decision', async () => {
    // Explicit signature so `mock.calls[0][3]` is typed as the
    // updated-input argument instead of being narrowed to an empty
    // tuple by mock's default inference.
    const onRespond = vi.fn(
      (
        _id: string,
        _decision: 'allow' | 'deny',
        _reason?: string,
        _updatedInput?: Record<string, unknown>
      ) => true
    );
    render(AskUserQuestionModal, {
      request: fakeRequest(),
      connected: true,
      onRespond
    });
    // If Escape propagated, the outer spy would fire. Same invariant
    // as ApprovalModal: silent-allow on dismiss is worse than a deny.
    const outer = vi.fn();
    window.addEventListener('keydown', outer);
    try {
      await fireEvent.keyDown(document.body, { key: 'Escape' });
      expect(outer).not.toHaveBeenCalled();
      expect(onRespond).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener('keydown', outer);
    }
  });

  it('surfaces a friendly error on malformed input (no questions array)', () => {
    const { getByTestId } = render(AskUserQuestionModal, {
      request: fakeRequest({ input: { not: 'questions' } }),
      connected: true,
      onRespond: vi.fn(() => true)
    });
    // Protocol-mismatch guard: rather than crash on `.map` of
    // undefined, show an explanation and let the user Cancel.
    expect(getByTestId('ask-malformed')).toBeInTheDocument();
    expect(getByTestId('ask-submit')).toBeDisabled();
    expect(getByTestId('ask-cancel')).not.toBeDisabled();
  });
});
