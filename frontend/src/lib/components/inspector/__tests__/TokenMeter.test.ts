/**
 * Unit tests for ``TokenMeter`` (gap-cycle-01-017).
 *
 * Acceptance criteria covered:
 * 1. When billing mode is subscription, the conversation header renders
 *    TokenMeter — tested here by rendering the component directly.
 * 2. TokenMeter shows input/output totals (fmtTokens formatting verified).
 * 3. Threshold colours fire at the right percentages:
 *    - Default (``text-fg-muted``) below 80 %.
 *    - Yellow  (``text-amber-400``) at 80 % and between 80–95 %.
 *    - Red     (``text-red-400``)  at and above 95 %.
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import TokenMeter from "../TokenMeter.svelte";
import { QUOTA_BAR_RED_PCT, QUOTA_BAR_YELLOW_PCT, TOKEN_METER_STRINGS } from "../../../config";

// ---- helpers ---------------------------------------------------------------

function renderMeter(inputTokens: number, outputTokens: number, overallUsedPct: number | null) {
  return render(TokenMeter, {
    props: { inputTokens, outputTokens, overallUsedPct },
  });
}

// ---- tests -----------------------------------------------------------------

describe("TokenMeter", () => {
  // AC: renders the meter element with testid
  it("renders the token-meter element", () => {
    const { getByTestId } = renderMeter(1000, 500, null);
    expect(getByTestId("token-meter")).toBeDefined();
  });

  // AC: shows input and output totals
  it("displays input token count with label", () => {
    const { getByTestId } = renderMeter(1200, 400, null);
    expect(getByTestId("token-meter-input")).toHaveTextContent("1.2k in");
  });

  it("displays output token count with label", () => {
    const { getByTestId } = renderMeter(1200, 400, null);
    expect(getByTestId("token-meter-output")).toHaveTextContent("400 out");
  });

  it("formats tokens in millions when >= 1 000 000", () => {
    const { getByTestId } = renderMeter(1_500_000, 2_300_000, null);
    expect(getByTestId("token-meter-input")).toHaveTextContent("1.5M in");
    expect(getByTestId("token-meter-output")).toHaveTextContent("2.3M out");
  });

  it("renders bare number when tokens < 1 000", () => {
    const { getByTestId } = renderMeter(42, 7, null);
    expect(getByTestId("token-meter-input")).toHaveTextContent("42 in");
    expect(getByTestId("token-meter-output")).toHaveTextContent("7 out");
  });

  // AC: default (muted) colour when quota pct is null
  it("applies muted colour when overallUsedPct is null", () => {
    const { getByTestId } = renderMeter(500, 200, null);
    const meter = getByTestId("token-meter");
    expect(meter.classList.contains("text-fg-muted")).toBe(true);
    expect(meter.classList.contains("text-amber-400")).toBe(false);
    expect(meter.classList.contains("text-red-400")).toBe(false);
  });

  // AC: muted colour below the yellow threshold
  it("applies muted colour when usage is below yellow threshold", () => {
    const { getByTestId } = renderMeter(500, 200, QUOTA_BAR_YELLOW_PCT - 0.01);
    const meter = getByTestId("token-meter");
    expect(meter.classList.contains("text-fg-muted")).toBe(true);
    expect(meter.classList.contains("text-amber-400")).toBe(false);
  });

  // AC: yellow colour fires at exactly the yellow threshold
  it("applies yellow colour at the yellow threshold boundary", () => {
    const { getByTestId } = renderMeter(500, 200, QUOTA_BAR_YELLOW_PCT);
    const meter = getByTestId("token-meter");
    expect(meter.classList.contains("text-amber-400")).toBe(true);
    expect(meter.classList.contains("text-fg-muted")).toBe(false);
    expect(meter.classList.contains("text-red-400")).toBe(false);
  });

  // AC: yellow colour between yellow and red thresholds
  it("applies yellow colour between 80 % and 95 %", () => {
    const { getByTestId } = renderMeter(500, 200, (QUOTA_BAR_YELLOW_PCT + QUOTA_BAR_RED_PCT) / 2);
    const meter = getByTestId("token-meter");
    expect(meter.classList.contains("text-amber-400")).toBe(true);
    expect(meter.classList.contains("text-red-400")).toBe(false);
  });

  // AC: red colour fires at exactly the red threshold
  it("applies red colour at the red threshold boundary", () => {
    const { getByTestId } = renderMeter(500, 200, QUOTA_BAR_RED_PCT);
    const meter = getByTestId("token-meter");
    expect(meter.classList.contains("text-red-400")).toBe(true);
    expect(meter.classList.contains("text-amber-400")).toBe(false);
    expect(meter.classList.contains("text-fg-muted")).toBe(false);
  });

  // AC: red colour above the red threshold
  it("applies red colour above 95 %", () => {
    const { getByTestId } = renderMeter(500, 200, 0.99);
    const meter = getByTestId("token-meter");
    expect(meter.classList.contains("text-red-400")).toBe(true);
  });

  // AC: correct aria-label by state
  it("uses the base aria-label when usage is below warn threshold", () => {
    const { getByTestId } = renderMeter(500, 200, 0.5);
    expect(getByTestId("token-meter")).toHaveAttribute("aria-label", TOKEN_METER_STRINGS.ariaLabel);
  });

  it("uses the warn aria-label in yellow state", () => {
    const { getByTestId } = renderMeter(500, 200, QUOTA_BAR_YELLOW_PCT);
    expect(getByTestId("token-meter")).toHaveAttribute(
      "aria-label",
      TOKEN_METER_STRINGS.warnAriaLabel,
    );
  });

  it("uses the danger aria-label in red state", () => {
    const { getByTestId } = renderMeter(500, 200, QUOTA_BAR_RED_PCT);
    expect(getByTestId("token-meter")).toHaveAttribute(
      "aria-label",
      TOKEN_METER_STRINGS.dangerAriaLabel,
    );
  });
});
