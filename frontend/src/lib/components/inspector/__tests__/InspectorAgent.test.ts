/**
 * InspectorAgent tests — renders against a fixture ``SessionOut``,
 * verifies each labelled field carries the right wire value (and the
 * documented empty-state copy when the field is null).
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorAgent from "../InspectorAgent.svelte";
import { INSPECTOR_STRINGS, NEW_SESSION_STRINGS } from "../../../config";
import type { SessionOut } from "../../../api/sessions";

function fakeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "Fixture",
    description: null,
    session_instructions: null,
    working_dir: "/home/user/project",
    model: "sonnet",
    permission_mode: null,
    max_budget_usd: null,
    total_cost_usd: 1.234,
    message_count: 7,
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

describe("InspectorAgent — labelled fields", () => {
  it("renders the heading from the string table", () => {
    const { getByText } = render(InspectorAgent, { props: { session: fakeSession() } });
    expect(getByText(INSPECTOR_STRINGS.agentHeading)).toBeInTheDocument();
  });

  it("renders the executor model via the new-session dialog's display label", () => {
    const { getByTestId } = render(InspectorAgent, {
      props: { session: fakeSession({ model: "sonnet" }) },
    });
    expect(getByTestId("inspector-agent-model")).toHaveTextContent(
      NEW_SESSION_STRINGS.executorLabels["sonnet"],
    );
  });

  it("falls back to the raw wire value for an unknown model id", () => {
    const { getByTestId } = render(InspectorAgent, {
      props: { session: fakeSession({ model: "future-model-9000" }) },
    });
    expect(getByTestId("inspector-agent-model")).toHaveTextContent("future-model-9000");
  });

  it("renders permission_mode when set, falling back to the documented placeholder otherwise", () => {
    const { getByTestId, rerender } = render(InspectorAgent, {
      props: { session: fakeSession({ permission_mode: "ask" }) },
    });
    expect(getByTestId("inspector-agent-permission-mode")).toHaveTextContent("ask");

    rerender({ session: fakeSession({ permission_mode: null }) });
    expect(getByTestId("inspector-agent-permission-mode")).toHaveTextContent(
      INSPECTOR_STRINGS.agentPermissionModeUnset,
    );
  });

  it("renders the working directory verbatim", () => {
    const wd = "/home/dave/projects/foo";
    const { getByTestId } = render(InspectorAgent, {
      props: { session: fakeSession({ working_dir: wd }) },
    });
    expect(getByTestId("inspector-agent-working-dir")).toHaveTextContent(wd);
  });

  it("renders max_budget_usd as a 2-decimal string when set, 'no cap' otherwise", () => {
    const { getByTestId, rerender } = render(InspectorAgent, {
      props: { session: fakeSession({ max_budget_usd: 12.5 }) },
    });
    expect(getByTestId("inspector-agent-max-budget")).toHaveTextContent("12.50");

    rerender({ session: fakeSession({ max_budget_usd: null }) });
    expect(getByTestId("inspector-agent-max-budget")).toHaveTextContent(
      INSPECTOR_STRINGS.agentMaxBudgetUnset,
    );
  });

  it("renders total_cost_usd to 2 decimals", () => {
    const { getByTestId } = render(InspectorAgent, {
      props: { session: fakeSession({ total_cost_usd: 1.234 }) },
    });
    expect(getByTestId("inspector-agent-total-cost")).toHaveTextContent("1.23");
  });

  it("renders the message count verbatim", () => {
    const { getByTestId } = render(InspectorAgent, {
      props: { session: fakeSession({ message_count: 42 }) },
    });
    expect(getByTestId("inspector-agent-message-count")).toHaveTextContent("42");
  });
});
