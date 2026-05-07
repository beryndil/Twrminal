/**
 * Component tests for ``ToolOutput`` — header, status pip, output
 * stream, truncation marker, error block.
 *
 * The "live clock" describe block covers gap-cycle-06-001:
 * elapsed counter ticks every second via ``setInterval`` while in
 * flight, and the ``liveElapsedMs`` floor from ``tool_progress``
 * events prevents a throttled local clock from showing a stale value.
 */
import { render } from "@testing-library/svelte";
import { flushSync } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ToolOutput from "../ToolOutput.svelte";
import type { ToolCallView } from "../../../stores/conversation.svelte";

function tool(overrides: Partial<ToolCallView> = {}): ToolCallView {
  return {
    id: "t1",
    name: "Bash",
    inputJson: "{}",
    output: "",
    rawLength: 0,
    done: false,
    ok: null,
    durationMs: null,
    errorMessage: null,
    liveElapsedMs: 0,
    startedAt: 0,
    ...overrides,
  };
}

describe("ToolOutput", () => {
  it("renders the tool name and an in-flight status pip", () => {
    const { getByTestId } = render(ToolOutput, { props: { call: tool() } });
    expect(getByTestId("tool-output-name")).toHaveTextContent("Bash");
    expect(getByTestId("tool-output-status-pip")).toHaveAttribute("aria-label", "Running");
  });

  it("renders streamed output verbatim", () => {
    const { getByTestId } = render(ToolOutput, {
      props: { call: tool({ output: "hello\nworld\n" }) },
    });
    expect(getByTestId("tool-output-stream")).toHaveTextContent("hello world");
  });

  it("flips the status pip green on a successful end", () => {
    const { getByTestId } = render(ToolOutput, {
      props: { call: tool({ done: true, ok: true, durationMs: 10 }) },
    });
    expect(getByTestId("tool-output-status-pip")).toHaveAttribute("aria-label", "Completed");
  });

  it("flips the status pip red and renders the error block on a failed end", () => {
    const { getByTestId } = render(ToolOutput, {
      props: {
        call: tool({
          done: true,
          ok: false,
          durationMs: 5,
          errorMessage: "boom",
          output: "partial\n",
        }),
      },
    });
    expect(getByTestId("tool-output-status-pip")).toHaveAttribute("aria-label", "Failed");
    expect(getByTestId("tool-output-error")).toHaveTextContent("boom");
    // Partial output stays visible per behavior doc §"Partial-output behavior on tool failure".
    expect(getByTestId("tool-output-stream")).toHaveTextContent("partial");
  });

  it("shows the truncation marker when output was elided", () => {
    const { getByTestId } = render(ToolOutput, {
      props: {
        call: tool({
          output: "tail",
          rawLength: 10_000,
        }),
      },
    });
    expect(getByTestId("tool-output-truncated")).toHaveTextContent("9996");
  });
});

/**
 * Live-clock behaviour (gap-cycle-06-001).
 *
 * The three sub-cases mirror the acceptance criteria directly:
 *   (a) elapsed display advances via ``setInterval`` ticks while in flight.
 *   (b) interval is cleared when the call completes (``done=true``).
 *   (c) ``liveElapsedMs`` floors the local clock when the server's
 *       keepalive value exceeds ``nowMs - startedAt`` (e.g. backgrounded tab).
 */
describe("ToolOutput — live clock", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("(a) elapsed display advances across two 1-second ticks while in flight", () => {
    const startedAt = Date.now();
    const { getByTestId } = render(ToolOutput, {
      props: { call: tool({ startedAt, liveElapsedMs: 0 }) },
    });

    // At t=0: both nowMs and startedAt are the same → 0 ms → "00:00".
    flushSync();
    expect(getByTestId("tool-output-elapsed")).toHaveTextContent("00:00");

    // Advance 1 s → setInterval fires → nowMs = startedAt + 1000 → "00:01".
    vi.advanceTimersByTime(1000);
    flushSync();
    expect(getByTestId("tool-output-elapsed")).toHaveTextContent("00:01");

    // Advance another 1 s → "00:02".
    vi.advanceTimersByTime(1000);
    flushSync();
    expect(getByTestId("tool-output-elapsed")).toHaveTextContent("00:02");
  });

  it("(b) interval is cleared once done=true", () => {
    const clearSpy = vi.spyOn(window, "clearInterval");
    const startedAt = Date.now();

    const { rerender } = render(ToolOutput, {
      props: { call: tool({ startedAt, done: false }) },
    });

    // Verify the interval was registered (setInterval fired).
    vi.advanceTimersByTime(1000);
    flushSync();

    // Transition to done — the $effect cleanup should clear the interval.
    rerender({ call: tool({ startedAt, done: true, ok: true, durationMs: 1200 }) });
    flushSync();

    expect(clearSpy).toHaveBeenCalled();
  });

  it("(c) liveElapsedMs floors the display when it exceeds nowMs-startedAt", () => {
    // Local clock says 2 s have elapsed; server's keepalive says 5 s.
    // The larger (server) value must win.
    const startedAt = Date.now() - 2000;
    const { getByTestId } = render(ToolOutput, {
      props: { call: tool({ startedAt, liveElapsedMs: 5000 }) },
    });

    flushSync();
    // Math.max(2000, 5000) = 5000 → "00:05".
    expect(getByTestId("tool-output-elapsed")).toHaveTextContent("00:05");
  });
});
