/**
 * Tests for :mod:`stores/checkpointBus.svelte.ts` (G6) — the small
 * shared store the composer/MessageTurn bump after creating a
 * checkpoint so that the gutter re-fetches its list.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { _resetForTests, bumpCheckpointRefresh, checkpointBus } from "../checkpointBus.svelte";

beforeEach(() => {
  _resetForTests();
});

describe("checkpoint bus", () => {
  it("starts at zero and increments monotonically on each bump", () => {
    expect(checkpointBus.refreshKey).toBe(0);
    bumpCheckpointRefresh();
    expect(checkpointBus.refreshKey).toBe(1);
    bumpCheckpointRefresh();
    bumpCheckpointRefresh();
    expect(checkpointBus.refreshKey).toBe(3);
  });

  it("_resetForTests rolls the tick back to zero", () => {
    bumpCheckpointRefresh();
    bumpCheckpointRefresh();
    expect(checkpointBus.refreshKey).toBe(2);
    _resetForTests();
    expect(checkpointBus.refreshKey).toBe(0);
  });
});
