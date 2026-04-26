import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Message } from '$lib/api';
import MessageTurn from './MessageTurn.svelte';

afterEach(cleanup);

function msg(overrides: Partial<Message> = {}): Message {
  return {
    id: 'm-1',
    session_id: 's-1',
    role: 'user',
    content: 'hello',
    thinking: null,
    created_at: '2026-04-21T00:00:00+00:00',
    ...overrides
  };
}

type Render = Record<string, unknown>;

function baseProps(overrides: Render = {}): Render {
  return {
    user: msg({ id: 'u-1', role: 'user', content: 'user text' }),
    assistant: msg({ id: 'a-1', role: 'assistant', content: 'assistant text' }),
    thinking: '',
    toolCalls: [],
    streamingContent: '',
    streamingThinking: '',
    isStreaming: false,
    highlightQuery: '',
    copiedMsgId: null,
    onCopyMessage: vi.fn(),
    ...overrides
  };
}

describe('MessageTurn (bulk mode)', () => {
  it('renders no bulk checkbox when bulkMode is off', () => {
    const { queryAllByTestId, getByTestId } = render(MessageTurn, baseProps());
    expect(queryAllByTestId('bulk-checkbox')).toHaveLength(0);
    // Articles still carry their data-message-id tags so the registry
    // menu and the Phase-5 scroll-into-view action can find them.
    expect(getByTestId('user-article').getAttribute('data-message-id')).toBe('u-1');
    expect(getByTestId('assistant-article').getAttribute('data-message-id')).toBe('a-1');
  });

  it('renders checkboxes when bulkMode is on', () => {
    const { getAllByTestId } = render(
      MessageTurn,
      baseProps({
        bulkMode: true,
        selectedIds: new Set<string>(),
        onToggleSelect: vi.fn()
      })
    );
    const boxes = getAllByTestId('bulk-checkbox');
    expect(boxes).toHaveLength(2);
    expect(boxes.map((b) => b.getAttribute('data-message-id'))).toEqual(['u-1', 'a-1']);
  });

  it('clicking a checkbox fires onToggleSelect with the message and shiftKey flag', async () => {
    const onToggleSelect = vi.fn();
    const { getAllByTestId } = render(
      MessageTurn,
      baseProps({
        bulkMode: true,
        selectedIds: new Set<string>(),
        onToggleSelect
      })
    );
    const boxes = getAllByTestId('bulk-checkbox');
    await fireEvent.click(boxes[0], { shiftKey: false });
    await fireEvent.click(boxes[1], { shiftKey: true });
    expect(onToggleSelect).toHaveBeenCalledTimes(2);
    expect(onToggleSelect.mock.calls[0][0].id).toBe('u-1');
    expect(onToggleSelect.mock.calls[0][1]).toBe(false);
    expect(onToggleSelect.mock.calls[1][0].id).toBe('a-1');
    expect(onToggleSelect.mock.calls[1][1]).toBe(true);
  });

  it('selected rows get an emerald highlight border', () => {
    const selected = new Set(['u-1']);
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        bulkMode: true,
        selectedIds: selected,
        onToggleSelect: vi.fn()
      })
    );
    const userArticle = getByTestId('user-article');
    expect(userArticle.className).toMatch(/border-emerald-500/);
    const assistantArticle = getByTestId('assistant-article');
    expect(assistantArticle.className).not.toMatch(/border-emerald-500/);
  });

  it('checkbox check state reflects selectedIds membership', () => {
    const selected = new Set(['a-1']);
    const { getAllByTestId } = render(
      MessageTurn,
      baseProps({
        bulkMode: true,
        selectedIds: selected,
        onToggleSelect: vi.fn()
      })
    );
    const boxes = getAllByTestId('bulk-checkbox') as HTMLInputElement[];
    // u-1 unchecked, a-1 checked
    expect(boxes[0].checked).toBe(false);
    expect(boxes[1].checked).toBe(true);
  });
});

describe('MessageTurn (more-info button)', () => {
  it('renders ℹ MORE only when isLatestAssistant is true and not streaming', () => {
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onMoreInfo: vi.fn(), isLatestAssistant: true })
    );
    const btn = queryByTestId('more-info-button');
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toContain('ℹ');
    expect(btn!.textContent!.toLowerCase()).toContain('more');
  });

  it('hides ℹ MORE on non-latest turns (older history rows)', () => {
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onMoreInfo: vi.fn(), isLatestAssistant: false })
    );
    expect(queryByTestId('more-info-button')).toBeNull();
  });

  it('hides ℹ MORE while the turn is still streaming', () => {
    // The contract is "elaborate on your previous response" — that's
    // incoherent before the response itself has finished.
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({
        onMoreInfo: vi.fn(),
        isLatestAssistant: true,
        isStreaming: true
      })
    );
    expect(queryByTestId('more-info-button')).toBeNull();
  });

  it('hides ℹ MORE when no onMoreInfo handler is provided', () => {
    // Defensive: callers that haven't wired the handler shouldn't
    // render a dead button. Conversation.svelte always wires it,
    // but legacy callers / tests passing a partial prop set don't.
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ isLatestAssistant: true })
    );
    expect(queryByTestId('more-info-button')).toBeNull();
  });

  it('clicking ℹ MORE fires onMoreInfo with the assistant message', async () => {
    const onMoreInfo = vi.fn();
    const { getByTestId } = render(
      MessageTurn,
      baseProps({ onMoreInfo, isLatestAssistant: true })
    );
    await fireEvent.click(getByTestId('more-info-button'));
    expect(onMoreInfo).toHaveBeenCalledTimes(1);
    expect(onMoreInfo.mock.calls[0][0].id).toBe('a-1');
    expect(onMoreInfo.mock.calls[0][0].role).toBe('assistant');
  });
});

describe('MessageTurn (spawn button)', () => {
  // L4.3.1 / Wave 2 lane 1. The `＋ SPAWN` button renders on every
  // finished assistant reply (not gated on `isLatestAssistant`, unlike
  // `ℹ MORE`) so older replies remain spawnable. Hidden during streaming
  // and when no `onSpawn` handler is wired.
  it('renders ＋ SPAWN on a finished assistant reply when onSpawn is wired', () => {
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onSpawn: vi.fn() })
    );
    const btn = queryByTestId('spawn-button');
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toContain('＋');
    expect(btn!.textContent!.toLowerCase()).toContain('spawn');
  });

  it('renders ＋ SPAWN even on non-latest turns', () => {
    // Distinct from ℹ MORE which is latest-only; spawning off a
    // historical reply is a legitimate workflow.
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onSpawn: vi.fn(), isLatestAssistant: false })
    );
    expect(queryByTestId('spawn-button')).not.toBeNull();
  });

  it('hides ＋ SPAWN while the turn is still streaming', () => {
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onSpawn: vi.fn(), isStreaming: true })
    );
    expect(queryByTestId('spawn-button')).toBeNull();
  });

  it('hides ＋ SPAWN when no onSpawn handler is provided', () => {
    const { queryByTestId } = render(MessageTurn, baseProps());
    expect(queryByTestId('spawn-button')).toBeNull();
  });

  it('clicking ＋ SPAWN fires onSpawn with the assistant message', async () => {
    const onSpawn = vi.fn();
    const { getByTestId } = render(MessageTurn, baseProps({ onSpawn }));
    await fireEvent.click(getByTestId('spawn-button'));
    expect(onSpawn).toHaveBeenCalledTimes(1);
    expect(onSpawn.mock.calls[0][0].id).toBe('a-1');
    expect(onSpawn.mock.calls[0][0].role).toBe('assistant');
  });
});

describe('MessageTurn (tool-call rows)', () => {
  function call(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
    return {
      id: 'tc-1',
      messageId: 'a-1',
      name: 'Read',
      input: { path: '/tmp/x' },
      output: 'ok',
      error: null,
      ok: true,
      startedAt: 0,
      finishedAt: 1,
      outputTruncated: false,
      lastProgressMs: null,
      ...overrides
    };
  }

  it('tags each tool-call row with its id so the registry can target it', () => {
    const { getAllByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [call(), call({ id: 'tc-2', name: 'Grep' })]
      })
    );
    const rows = getAllByTestId('tool-call-row');
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.getAttribute('data-tool-call-id'))).toEqual(['tc-1', 'tc-2']);
  });

  it('finished calls render no pulse, no elapsed readout, no running flag', () => {
    const { queryByTestId, getByTestId } = render(
      MessageTurn,
      baseProps({ toolCalls: [call()] })
    );
    expect(getByTestId('tool-call-row').getAttribute('data-running')).toBe('false');
    expect(queryByTestId('tool-call-pulse')).toBeNull();
    expect(queryByTestId('tool-call-elapsed')).toBeNull();
    expect(queryByTestId('tool-call-subagent')).toBeNull();
  });

  it('running calls get the pulse + live elapsed readout', () => {
    // startedAt 45s before a fixed "now" so the formatter produces
    // a deterministic string without fake timers.
    const fixedNow = 1_700_000_000_000;
    vi.setSystemTime(new Date(fixedNow));
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({ id: 'tc-run', ok: null, finishedAt: null, startedAt: fixedNow - 45_000 })
        ]
      })
    );
    expect(getByTestId('tool-call-row').getAttribute('data-running')).toBe('true');
    expect(getByTestId('tool-call-pulse')).not.toBeNull();
    expect(getByTestId('tool-call-elapsed').textContent).toBe('45s');
    vi.useRealTimers();
  });

  it('running sub-agent calls carry the "running sub-agent" subtitle with description', () => {
    const fixedNow = 1_700_000_000_000;
    vi.setSystemTime(new Date(fixedNow));
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-sub',
            name: 'Agent',
            input: { description: 'research the codebase' },
            ok: null,
            finishedAt: null,
            startedAt: fixedNow - 3_000
          })
        ]
      })
    );
    const subtitle = getByTestId('tool-call-subagent');
    expect(subtitle.textContent).toContain('running sub-agent');
    expect(subtitle.textContent).toContain('research the codebase');
    expect(getByTestId('tool-call-elapsed').textContent).toBe('3s');
    vi.useRealTimers();
  });

  it('sub-agent subtitle is hidden on non-Agent tools even while running', () => {
    const fixedNow = 1_700_000_000_000;
    vi.setSystemTime(new Date(fixedNow));
    const { queryByTestId, getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-read',
            name: 'Read',
            ok: null,
            finishedAt: null,
            startedAt: fixedNow
          })
        ]
      })
    );
    expect(getByTestId('tool-call-pulse')).not.toBeNull();
    expect(queryByTestId('tool-call-subagent')).toBeNull();
    vi.useRealTimers();
  });

  // The summary row surfaces a running sub-agent's description so
  // users with the tool-work `<details>` collapsed still see *what*
  // a long-running Agent/Task call is doing. The in-pre `tool-call-
  // subagent` subtitle only renders when the block is expanded;
  // `tool-work-subagent-subtitle` is the always-visible mirror.
  it('summary row surfaces the first running sub-agent description', () => {
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-sub',
            name: 'Agent',
            input: { description: 'research the codebase' },
            ok: null,
            finishedAt: null
          })
        ]
      })
    );
    const subtitle = getByTestId('tool-work-subagent-subtitle');
    expect(subtitle.textContent).toContain('research the codebase');
    expect(subtitle.getAttribute('title')).toBe('research the codebase');
  });

  it('summary subtitle prefers the first running sub-agent when several are in flight', () => {
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-sub-1',
            name: 'Agent',
            input: { description: 'first job' },
            ok: null,
            finishedAt: null
          }),
          call({
            id: 'tc-sub-2',
            name: 'Task',
            input: { description: 'second job' },
            ok: null,
            finishedAt: null
          })
        ]
      })
    );
    const subtitle = getByTestId('tool-work-subagent-subtitle');
    expect(subtitle.textContent).toContain('first job');
    expect(subtitle.textContent).not.toContain('second job');
  });

  it('summary subtitle skips finished sub-agents and hides when none are running', () => {
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-sub-done',
            name: 'Agent',
            input: { description: 'already finished' },
            ok: true,
            finishedAt: 2000,
            startedAt: 1000
          })
        ]
      })
    );
    expect(queryByTestId('tool-work-subagent-subtitle')).toBeNull();
  });

  it('summary subtitle is absent when only non-Agent tools are running', () => {
    const { queryByTestId, getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-read',
            name: 'Read',
            ok: null,
            finishedAt: null
          })
        ]
      })
    );
    // Running badge is still present (there's a running tool), but
    // there's no sub-agent to describe.
    expect(getByTestId('tool-work-running-badge')).not.toBeNull();
    expect(queryByTestId('tool-work-subagent-subtitle')).toBeNull();
  });

  it('lastProgressMs floors the readout when the local clock is stale', () => {
    // Simulates a backgrounded tab: the local `now` is only 2s past
    // startedAt (setInterval was throttled), but the server's
    // tool_progress keepalives reported 40s of elapsed work. The
    // readout must honor the server floor, not the stale local delta.
    const fixedNow = 1_700_000_000_000;
    vi.setSystemTime(new Date(fixedNow));
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-floor',
            name: 'Agent',
            ok: null,
            finishedAt: null,
            startedAt: fixedNow - 2_000,
            lastProgressMs: 40_000
          })
        ]
      })
    );
    expect(getByTestId('tool-call-elapsed').textContent).toBe('40s');
    vi.useRealTimers();
  });

  it('local clock wins when it is ahead of the server floor', () => {
    // Foreground tab — the local tick has already advanced past the
    // last keepalive, which is the common case. Readout uses the
    // local delta.
    const fixedNow = 1_700_000_000_000;
    vi.setSystemTime(new Date(fixedNow));
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-live',
            name: 'Agent',
            ok: null,
            finishedAt: null,
            startedAt: fixedNow - 10_000,
            lastProgressMs: 6_000
          })
        ]
      })
    );
    expect(getByTestId('tool-call-elapsed').textContent).toBe('10s');
    vi.useRealTimers();
  });

  it('formats elapsed >=60s as m+ss', () => {
    const fixedNow = 1_700_000_000_000;
    vi.setSystemTime(new Date(fixedNow));
    const { getByTestId } = render(
      MessageTurn,
      baseProps({
        toolCalls: [
          call({
            id: 'tc-long',
            name: 'Agent',
            ok: null,
            finishedAt: null,
            // 82s — matches the transcript gap in the silence-gap entry.
            startedAt: fixedNow - 82_000
          })
        ]
      })
    );
    expect(getByTestId('tool-call-elapsed').textContent).toBe('1m22s');
    vi.useRealTimers();
  });
});

describe('MessageTurn (critique button)', () => {
  // L4.3.3 / Wave 2 lane 3. The `⚔ CRIT` button mirrors `✂ TLDR`'s
  // visibility contract: every finished assistant reply, every turn
  // (latest or historical), hidden during streaming and when no
  // `onCritique` handler is wired. The visual differentiation from
  // TL;DR comes from the modal's catalog-driven label badge — the
  // button itself uses the same compact action-row styling.
  it('renders ⚔ CRIT on a finished assistant reply when onCritique is wired', () => {
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onCritique: vi.fn() })
    );
    const btn = queryByTestId('critique-button');
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toContain('⚔');
    expect(btn!.textContent!.toLowerCase()).toContain('crit');
  });

  it('renders ⚔ CRIT even on non-latest turns', () => {
    // Critiquing an older reply is a legitimate workflow — same
    // rationale as ＋ SPAWN and ✂ TLDR, distinct from latest-only
    // ℹ MORE.
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onCritique: vi.fn(), isLatestAssistant: false })
    );
    expect(queryByTestId('critique-button')).not.toBeNull();
  });

  it('hides ⚔ CRIT while the turn is still streaming', () => {
    const { queryByTestId } = render(
      MessageTurn,
      baseProps({ onCritique: vi.fn(), isStreaming: true })
    );
    expect(queryByTestId('critique-button')).toBeNull();
  });

  it('hides ⚔ CRIT when no onCritique handler is provided', () => {
    const { queryByTestId } = render(MessageTurn, baseProps());
    expect(queryByTestId('critique-button')).toBeNull();
  });

  it('clicking ⚔ CRIT fires onCritique with the assistant message', async () => {
    const onCritique = vi.fn();
    const { getByTestId } = render(MessageTurn, baseProps({ onCritique }));
    await fireEvent.click(getByTestId('critique-button'));
    expect(onCritique).toHaveBeenCalledTimes(1);
    expect(onCritique.mock.calls[0][0].id).toBe('a-1');
    expect(onCritique.mock.calls[0][0].role).toBe('assistant');
  });
});
