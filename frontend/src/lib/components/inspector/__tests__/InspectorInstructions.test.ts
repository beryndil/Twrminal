/**
 * InspectorInstructions tests — read-only render of
 * ``session_instructions`` plus the empty-state branch.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import InspectorInstructions from "../InspectorInstructions.svelte";
import { INSPECTOR_STRINGS } from "../../../config";
import type { SessionOut } from "../../../api/sessions";

function fakeSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: "ses_a",
    kind: "chat",
    title: "Fixture",
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

describe("InspectorInstructions", () => {
  it("renders the heading from the string table", () => {
    const { getByText } = render(InspectorInstructions, {
      props: { session: fakeSession() },
    });
    expect(getByText(INSPECTOR_STRINGS.instructionsHeading)).toBeInTheDocument();
  });

  it("renders the empty-state copy when session_instructions is null", () => {
    const { getByTestId, queryByTestId } = render(InspectorInstructions, {
      props: { session: fakeSession({ session_instructions: null }) },
    });
    expect(getByTestId("inspector-instructions-empty")).toHaveTextContent(
      INSPECTOR_STRINGS.instructionsEmpty,
    );
    expect(queryByTestId("inspector-instructions-body")).toBeNull();
  });

  it("renders the empty-state copy when session_instructions is whitespace-only", () => {
    const { getByTestId } = render(InspectorInstructions, {
      props: { session: fakeSession({ session_instructions: "   \n\n  " }) },
    });
    expect(getByTestId("inspector-instructions-empty")).toHaveTextContent(
      INSPECTOR_STRINGS.instructionsEmpty,
    );
  });

  it("renders the instructions body verbatim, preserving line breaks", () => {
    const body = "first line\nsecond line\n  - bullet";
    const { getByTestId, queryByTestId } = render(InspectorInstructions, {
      props: { session: fakeSession({ session_instructions: body }) },
    });
    const bodyEl = getByTestId("inspector-instructions-body");
    expect(bodyEl.textContent).toBe(body);
    expect(queryByTestId("inspector-instructions-empty")).toBeNull();
  });

  it("labels the body with the documented aria-label", () => {
    const { getByTestId } = render(InspectorInstructions, {
      props: { session: fakeSession({ session_instructions: "x" }) },
    });
    expect(getByTestId("inspector-instructions-body")).toHaveAttribute(
      "aria-label",
      INSPECTOR_STRINGS.instructionsBodyLabel,
    );
  });
});
