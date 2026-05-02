/**
 * InspectorContext tests — title / description / context-window
 * fields render from the fixture session, with the documented
 * placeholders when the wire value is null.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorContext from "../InspectorContext.svelte";
import { INSPECTOR_STRINGS } from "../../../config";
import type { SessionOut } from "../../../api/sessions";

function fakeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "Fixture title",
    description: null,
    session_instructions: null,
    working_dir: "/wd",
    model: "sonnet",
    permission_mode: null,
    max_budget_usd: null,
    total_cost_usd: 0,
    message_count: 0,
    last_context_pct: null,
    last_context_tokens: null,
    last_context_max: null,
    pinned: false,
    error_pending: false,
    checklist_item_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_viewed_at: null,
    last_completed_at: null,
    closed_at: null,
    closing_summary: null,
    ...overrides,
  };
}

describe("InspectorContext — labelled fields", () => {
  it("renders the heading and the assembled-context placeholder section", () => {
    const { getByText, getByTestId } = render(InspectorContext, {
      props: { session: fakeSession() },
    });
    expect(getByText(INSPECTOR_STRINGS.contextHeading)).toBeInTheDocument();
    expect(getByTestId("inspector-context-assembled")).toHaveTextContent(
      INSPECTOR_STRINGS.contextAssembledPlaceholder,
    );
  });

  it("renders the session title verbatim", () => {
    const { getByTestId } = render(InspectorContext, {
      props: { session: fakeSession({ title: "Designing the inspector" }) },
    });
    expect(getByTestId("inspector-context-title")).toHaveTextContent("Designing the inspector");
  });

  it("renders the description when set, the empty placeholder otherwise", () => {
    const { getByTestId, rerender } = render(InspectorContext, {
      props: { session: fakeSession({ description: "multi-line\nplug" }) },
    });
    expect(getByTestId("inspector-context-description")).toHaveTextContent("multi-line plug");

    rerender({ session: fakeSession({ description: null }) });
    expect(getByTestId("inspector-context-description")).toHaveTextContent(
      INSPECTOR_STRINGS.contextDescriptionEmpty,
    );
  });

  it("formats the last context-window pressure as a percent", () => {
    const { getByTestId, rerender } = render(InspectorContext, {
      props: { session: fakeSession({ last_context_pct: 0.42 }) },
    });
    expect(getByTestId("inspector-context-last-pct")).toHaveTextContent("42%");

    rerender({ session: fakeSession({ last_context_pct: null }) });
    expect(getByTestId("inspector-context-last-pct")).toHaveTextContent(
      INSPECTOR_STRINGS.contextLastContextNotSeen,
    );
  });

  it("formats the last context tokens with locale-grouped digits", () => {
    const { getByTestId } = render(InspectorContext, {
      props: { session: fakeSession({ last_context_tokens: 175500 }) },
    });
    // ``toLocaleString`` defaults to the runtime locale; the
    // separator glyph (comma, narrow no-break space, etc.) varies, so
    // assert the digit triplets are present with any single-character
    // separator between them rather than pinning the glyph.
    const text = getByTestId("inspector-context-last-tokens").textContent ?? "";
    expect(text).toMatch(/175.?500/);
  });

  it("renders the not-seen-yet placeholder when last_context_tokens is null", () => {
    const { getByTestId } = render(InspectorContext, {
      props: { session: fakeSession({ last_context_tokens: null }) },
    });
    expect(getByTestId("inspector-context-last-tokens")).toHaveTextContent(
      INSPECTOR_STRINGS.contextLastContextNotSeen,
    );
  });

  it("renders the context-window max with the same formatter", () => {
    const { getByTestId, rerender } = render(InspectorContext, {
      props: { session: fakeSession({ last_context_max: 200000 }) },
    });
    const text = getByTestId("inspector-context-last-max").textContent ?? "";
    expect(text).toMatch(/200.?000/);

    rerender({ session: fakeSession({ last_context_max: null }) });
    expect(getByTestId("inspector-context-last-max")).toHaveTextContent(
      INSPECTOR_STRINGS.contextLastContextNotSeen,
    );
  });
});
