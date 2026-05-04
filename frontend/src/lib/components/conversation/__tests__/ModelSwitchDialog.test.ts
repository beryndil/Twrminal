/**
 * Component tests for ``ModelSwitchDialog`` — rendered copy, recost
 * body variants (tokens known / unknown), estimated cost line, action
 * button callbacks, and error display.
 */
import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import ModelSwitchDialog from "../ModelSwitchDialog.svelte";

const baseProps = {
  fromModel: "sonnet",
  toModel: "opus",
  contextTokens: 38_000,
  switching: false,
  errorMsg: null,
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

describe("ModelSwitchDialog", () => {
  it("renders the title with from/to display labels", () => {
    const { getByTestId } = render(ModelSwitchDialog, { props: baseProps });
    expect(getByTestId("model-switch-title")).toHaveTextContent(
      "Switch executor: Sonnet 4.6 → Opus 4.7",
    );
  });

  it("renders the recost body with formatted token count when tokens known", () => {
    const { getByTestId } = render(ModelSwitchDialog, { props: baseProps });
    const body = getByTestId("model-switch-recost-body").textContent ?? "";
    expect(body).toContain("38,000");
    expect(body).toContain("Opus 4.7");
  });

  it("renders the unknown-tokens fallback when contextTokens is null", () => {
    const { getByTestId } = render(ModelSwitchDialog, {
      props: { ...baseProps, contextTokens: null },
    });
    expect(getByTestId("model-switch-recost-body")).toHaveTextContent(
      "Context window size is unknown",
    );
  });

  it("renders the estimated cost line when tokens are available", () => {
    const { getByTestId } = render(ModelSwitchDialog, { props: baseProps });
    // 38,000 × $15/M = $0.57
    expect(getByTestId("model-switch-estimated-cost")).toHaveTextContent("$0.57");
  });

  it("omits the estimated cost line when contextTokens is null", () => {
    const { queryByTestId } = render(ModelSwitchDialog, {
      props: { ...baseProps, contextTokens: null },
    });
    expect(queryByTestId("model-switch-estimated-cost")).toBeNull();
  });

  it("calls onConfirm when the Switch button is clicked", () => {
    const onConfirm = vi.fn();
    const { getByTestId } = render(ModelSwitchDialog, {
      props: { ...baseProps, onConfirm },
    });
    fireEvent.click(getByTestId("model-switch-confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when the Cancel button is clicked", () => {
    const onCancel = vi.fn();
    const { getByTestId } = render(ModelSwitchDialog, {
      props: { ...baseProps, onCancel },
    });
    fireEvent.click(getByTestId("model-switch-cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables both buttons and shows Switching… while switching=true", () => {
    const { getByTestId } = render(ModelSwitchDialog, {
      props: { ...baseProps, switching: true },
    });
    expect(getByTestId("model-switch-confirm")).toBeDisabled();
    expect(getByTestId("model-switch-cancel")).toBeDisabled();
    expect(getByTestId("model-switch-confirm")).toHaveTextContent("Switching…");
  });

  it("renders error message when errorMsg is set", () => {
    const { getByTestId } = render(ModelSwitchDialog, {
      props: { ...baseProps, errorMsg: "Couldn't switch model — try again." },
    });
    expect(getByTestId("model-switch-error")).toHaveTextContent(
      "Couldn't switch model — try again.",
    );
  });

  it("omits error element when errorMsg is null", () => {
    const { queryByTestId } = render(ModelSwitchDialog, { props: baseProps });
    expect(queryByTestId("model-switch-error")).toBeNull();
  });

  it("renders the dialog with haiku as the destination model", () => {
    const { getByTestId } = render(ModelSwitchDialog, {
      props: { ...baseProps, fromModel: "opus", toModel: "haiku", contextTokens: 10_000 },
    });
    expect(getByTestId("model-switch-title")).toHaveTextContent(
      "Switch executor: Opus 4.7 → Haiku 4.5",
    );
    // 10,000 × $0.80/M = $0.01
    expect(getByTestId("model-switch-estimated-cost")).toHaveTextContent("$0.01");
  });
});
