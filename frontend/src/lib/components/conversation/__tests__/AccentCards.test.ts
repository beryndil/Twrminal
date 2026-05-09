/**
 * Unit tests for ``AccentCards`` (gap-cycle-01-019).
 *
 * Acceptance criteria covered:
 * 1. Card 1 (cache) is hidden when ``sessionCacheReadTokens === 0``.
 * 2. Card 1 shows the correct savings percentage and N vs M token
 *    counts for a known ``sessionCacheReadTokens`` / ``sessionInputTokens``
 *    combination.
 * 3. Card 2 (recovery) renders unconditionally with the ring-buffer
 *    cap label.
 */
import { render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- Store mock ------------------------------------------------------------

let _cacheReadTokens = 0;
let _inputTokens = 0;

vi.mock("../../../stores/conversation.svelte", () => ({
  conversationStore: {
    get sessionCacheReadTokens() {
      return _cacheReadTokens;
    },
    get sessionInputTokens() {
      return _inputTokens;
    },
  },
}));

import AccentCards from "../AccentCards.svelte";
import { ACCENT_CARDS_STRINGS, WS_RING_BUFFER_CAP } from "../../../config";

// ---- helpers ---------------------------------------------------------------

function renderCards(cacheRead: number, input: number) {
  _cacheReadTokens = cacheRead;
  _inputTokens = input;
  return render(AccentCards);
}

// ---- tests -----------------------------------------------------------------

beforeEach(() => {
  _cacheReadTokens = 0;
  _inputTokens = 0;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AccentCards", () => {
  // AC1: card 1 absent when cache_read = 0 ----------------------------------

  it("does NOT render card 1 when sessionCacheReadTokens is 0", () => {
    const { queryByTestId } = renderCards(0, 500);
    expect(queryByTestId("accent-card-cache")).toBeNull();
  });

  it("renders card 2 even when sessionCacheReadTokens is 0", () => {
    const { getByTestId } = renderCards(0, 500);
    expect(getByTestId("accent-card-recovery")).toBeDefined();
  });

  // AC2: card 1 content for known cache_read --------------------------------

  it("renders card 1 when sessionCacheReadTokens > 0", () => {
    const { getByTestId } = renderCards(1_000, 2_000);
    expect(getByTestId("accent-card-cache")).toBeDefined();
  });

  it("computes and renders the correct savings percentage", () => {
    // cache_read=1000, input=2000 → total=3000
    // pct = round(1000 * 0.9 / 3000 * 100) = round(30) = 30%
    const { getByTestId } = renderCards(1_000, 2_000);
    const pctEl = getByTestId("accent-card-cache-pct");
    expect(pctEl.textContent).toContain("30");
    expect(pctEl.textContent).toContain(ACCENT_CARDS_STRINGS.cachePctSuffix);
  });

  it("renders savings-percentage span with correct label tokens", () => {
    const { getByTestId } = renderCards(1_000, 2_000);
    const pctEl = getByTestId("accent-card-cache-pct");
    expect(pctEl.textContent).toContain(ACCENT_CARDS_STRINGS.cacheSavedLabel);
    expect(pctEl.textContent).toContain(ACCENT_CARDS_STRINGS.cacheSavingsLabel);
  });

  it("renders the ratio span with N vs M cached tokens", () => {
    // cache_read=1000, input=2000
    // N (actual cost) = round(2000 + 1000*0.1) = 2100 → "2.1k"
    // M (without cache) = 3000 → "3.0k"
    const { getByTestId } = renderCards(1_000, 2_000);
    const ratioEl = getByTestId("accent-card-cache-ratio");
    expect(ratioEl.textContent).toContain("2.1k");
    expect(ratioEl.textContent).toContain("3.0k");
    expect(ratioEl.textContent).toContain(ACCENT_CARDS_STRINGS.cacheVsLabel);
    expect(ratioEl.textContent).toContain(ACCENT_CARDS_STRINGS.cacheSuffix);
  });

  it("formats millions correctly on card 1", () => {
    // cache_read=1_300_000, input=2_100_000
    // N = round(2_100_000 + 130_000) = 2_230_000 → "2.2M"
    // M = 3_400_000 → "3.4M"
    const { getByTestId } = renderCards(1_300_000, 2_100_000);
    const ratioEl = getByTestId("accent-card-cache-ratio");
    expect(ratioEl.textContent).toContain("2.2M");
    expect(ratioEl.textContent).toContain("3.4M");
  });

  // AC3: card 2 unconditionally renders the buffer cap label ----------------

  it("card 2 renders when cache_read is zero", () => {
    const { getByTestId } = renderCards(0, 0);
    expect(getByTestId("accent-card-recovery")).toBeDefined();
  });

  it("card 2 renders when cache_read is non-zero", () => {
    const { getByTestId } = renderCards(500, 1_000);
    expect(getByTestId("accent-card-recovery")).toBeDefined();
  });

  it("card 2 label contains the ring buffer cap", () => {
    const { getByTestId } = renderCards(0, 0);
    const label = getByTestId("accent-card-recovery-label");
    expect(label.textContent).toContain(String(WS_RING_BUFFER_CAP));
  });

  it("card 2 label contains the recovery-armed copy and buffer suffix", () => {
    const { getByTestId } = renderCards(0, 0);
    const label = getByTestId("accent-card-recovery-label");
    expect(label.textContent).toContain(ACCENT_CARDS_STRINGS.recoveryArmedLabel);
    expect(label.textContent).toContain(ACCENT_CARDS_STRINGS.recoveryBufferPrefix);
    expect(label.textContent).toContain(ACCENT_CARDS_STRINGS.recoveryBufferSuffix);
  });

  // Wrapper element ----------------------------------------------------------

  it("renders the cards wrapper element with aria-label", () => {
    const { getByTestId } = renderCards(0, 0);
    const wrapper = getByTestId("accent-cards");
    expect(wrapper).toBeDefined();
    expect(wrapper).toHaveAttribute("aria-label", ACCENT_CARDS_STRINGS.ariaLabel);
  });

  // A11y regression — NEW-BUG-A11Y-02 ----------------------------------------

  it("cache-ratio span does not use text-accent/70 (WCAG contrast regression)", () => {
    // text-accent/70 failed 4.5:1 on paper-light (bg-accent/10 ~3.06:1).
    // The span must NOT carry the opacity modifier; it must use text-fg-muted
    // which passes on all theme backgrounds.
    const { getByTestId } = renderCards(1_000, 2_000);
    const ratioEl = getByTestId("accent-card-cache-ratio");
    expect(ratioEl.classList.contains("text-accent/70")).toBe(false);
    expect(ratioEl.classList.contains("text-accent\\/70")).toBe(false);
    // Must carry the muted fg class instead.
    expect(ratioEl.classList.contains("text-fg-muted")).toBe(true);
  });
});
