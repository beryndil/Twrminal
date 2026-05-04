/**
 * Component tests for ``ModelSelector`` — visibility, current-model
 * display, dialog open/close on selection, and confirm / cancel paths.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi, beforeEach } from "vitest";

import ModelSelector from "../ModelSelector.svelte";
import * as sessionsApi from "../../../api/sessions";

// ---- Store stub ----------------------------------------------------------
vi.mock("../../../stores/sessions.svelte", () => ({
  sessionsStore: {
    get sessions() {
      return _sessions;
    },
  },
}));

let _sessions: Array<{
  id: string;
  model: string;
  last_context_tokens: number | null;
}> = [];

function setSession(id: string, model: string, contextTokens: number | null = 50_000): void {
  _sessions = [{ id, model, last_context_tokens: contextTokens }];
}

// ---- API stub ------------------------------------------------------------
vi.mock("../../../api/sessions", () => ({
  patchSessionModel: vi.fn(),
}));

const mockPatch = vi.mocked(sessionsApi.patchSessionModel);

beforeEach(() => {
  _sessions = [];
  mockPatch.mockReset();
});

// --------------------------------------------------------------------------
describe("ModelSelector", () => {
  it("renders nothing when sessionId is null", () => {
    const { queryByTestId } = render(ModelSelector, { props: { sessionId: null } });
    expect(queryByTestId("model-selector")).toBeNull();
  });

  it("renders nothing when the session is not found in the store", () => {
    const { queryByTestId } = render(ModelSelector, {
      props: { sessionId: "ses_unknown" },
    });
    expect(queryByTestId("model-selector")).toBeNull();
  });

  it("renders the selector when a session exists in the store", () => {
    setSession("ses_1", "sonnet");
    const { getByTestId } = render(ModelSelector, { props: { sessionId: "ses_1" } });
    expect(getByTestId("model-selector")).toBeDefined();
  });

  it("sets the select value to the current model", () => {
    setSession("ses_1", "opus");
    const { getByTestId } = render(ModelSelector, { props: { sessionId: "ses_1" } });
    const select = getByTestId("model-select") as HTMLSelectElement;
    expect(select.value).toBe("opus");
  });

  it("opens the confirmation dialog when a different model is chosen", async () => {
    setSession("ses_1", "sonnet");
    const { getByTestId } = render(ModelSelector, { props: { sessionId: "ses_1" } });
    const select = getByTestId("model-select") as HTMLSelectElement;
    select.value = "opus";
    fireEvent.change(select);
    expect(getByTestId("model-switch-dialog")).toBeDefined();
  });

  it("does NOT open the dialog when the same model is re-selected", async () => {
    setSession("ses_1", "sonnet");
    const { queryByTestId, getByTestId } = render(ModelSelector, {
      props: { sessionId: "ses_1" },
    });
    const select = getByTestId("model-select") as HTMLSelectElement;
    select.value = "sonnet";
    fireEvent.change(select);
    expect(queryByTestId("model-switch-dialog")).toBeNull();
  });

  it("closes the dialog when Cancel is clicked", async () => {
    setSession("ses_1", "sonnet");
    const { queryByTestId, getByTestId } = render(ModelSelector, {
      props: { sessionId: "ses_1" },
    });
    const select = getByTestId("model-select") as HTMLSelectElement;
    select.value = "haiku";
    fireEvent.change(select);
    expect(getByTestId("model-switch-dialog")).toBeDefined();
    fireEvent.click(getByTestId("model-switch-cancel"));
    expect(queryByTestId("model-switch-dialog")).toBeNull();
  });

  it("calls patchSessionModel and closes dialog when Switch is confirmed", async () => {
    mockPatch.mockResolvedValue({} as sessionsApi.SessionOut);
    setSession("ses_1", "sonnet");
    const { getByTestId } = render(ModelSelector, {
      props: { sessionId: "ses_1" },
    });
    const select = getByTestId("model-select") as HTMLSelectElement;
    select.value = "opus";
    fireEvent.change(select);
    fireEvent.click(getByTestId("model-switch-confirm"));
    expect(mockPatch).toHaveBeenCalledWith("ses_1", "opus");
  });
});
