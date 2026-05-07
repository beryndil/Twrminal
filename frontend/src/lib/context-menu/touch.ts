/**
 * Long-press FSM and Svelte action for coarse-pointer context menu
 * triggering.
 *
 * Behavior anchor: ``docs/behavior/context-menus.md`` §"Common behavior
 * — Trigger": right-click OR long-press (touch / pen) opens the menu.
 *
 * Design:
 *
 * - :func:`reduceLongPress` is a **pure** state-transition function.
 *   No timers, no side effects.  The caller (:func:`longpress`) owns
 *   scheduling.
 * - :func:`isCoarsePointer` is the single gate.  ``false`` in SSR /
 *   test environments that do not configure ``window.matchMedia``.
 * - :func:`longpress` is the Svelte action that wires pointer events and
 *   drives the FSM.  Returns a no-op ``destroy`` on fine pointers so
 *   callers never branch on pointer type themselves.
 */

/** Duration (ms) a pointer must be held before the long-press fires. */
const LONG_PRESS_DURATION_MS = 500;

/** Maximum pixel displacement before the long-press is cancelled. */
const LONG_PRESS_MOVEMENT_THRESHOLD_PX = 8;

// ---------------------------------------------------------------------------
// FSM types
// ---------------------------------------------------------------------------

/**
 * Phase of the long-press finite-state machine.
 *
 * - ``idle``  — no qualifying pointer is down.
 * - ``armed`` — a qualifying pointerdown was received; timer is running.
 */
export type LongPressPhase = "idle" | "armed";

/** Immutable FSM state record. */
export interface LongPressState {
  /** Current phase. */
  readonly phase: LongPressPhase;
  /** Viewport X of the initiating ``pointerdown`` event (0 when idle). */
  readonly startX: number;
  /** Viewport Y of the initiating ``pointerdown`` event (0 when idle). */
  readonly startY: number;
}

/** Canonical idle sentinel — reused instead of allocating a fresh object. */
export const LONG_PRESS_IDLE: LongPressState = {
  phase: "idle",
  startX: 0,
  startY: 0,
};

/** Events that the :func:`reduceLongPress` pure reducer accepts. */
export type LongPressInputEvent =
  | {
      readonly type: "pointerdown";
      readonly x: number;
      readonly y: number;
      /** The ``PointerEvent.pointerType`` string (``"touch"``, ``"pen"``, ``"mouse"``). */
      readonly pointerType: string;
    }
  | { readonly type: "pointermove"; readonly x: number; readonly y: number }
  | { readonly type: "pointerup" | "pointercancel" | "pointerleave" };

// ---------------------------------------------------------------------------
// Pure reducer
// ---------------------------------------------------------------------------

/**
 * Pure reducer for the long-press FSM.
 *
 * Returns the **next** :type:`LongPressState`.  Side effects (timer
 * scheduling / cancellation) are the caller's responsibility — inspect
 * the phase transition to decide whether to arm or disarm.
 *
 * Transition table:
 *
 * - ``pointerdown`` (touch / pen) while ``idle`` → ``armed``.
 * - ``pointerdown`` (mouse) → no transition (returns ``current``).
 * - ``pointermove`` while ``armed`` + displacement > threshold → ``idle``.
 * - ``pointerup`` / ``pointercancel`` / ``pointerleave`` while ``armed``
 *   → ``idle``.
 * - All other combinations → ``current`` (identity).
 *
 * @param current - Current FSM state.
 * @param event - Input event to process.
 * @param opts - Optional overrides (``thresholdPx`` only for now).
 */
export function reduceLongPress(
  current: LongPressState,
  event: LongPressInputEvent,
  opts: { readonly thresholdPx?: number } = {},
): LongPressState {
  const threshold = opts.thresholdPx ?? LONG_PRESS_MOVEMENT_THRESHOLD_PX;

  switch (event.type) {
    case "pointerdown": {
      // Only arm for touch and pen (stylus) — mouse always produces a
      // native ``contextmenu`` event on right-click.
      if (event.pointerType !== "touch" && event.pointerType !== "pen") {
        return current;
      }
      return { phase: "armed", startX: event.x, startY: event.y };
    }
    case "pointermove": {
      if (current.phase !== "armed") return current;
      const dx = event.x - current.startX;
      const dy = event.y - current.startY;
      // Cancel if the pointer has drifted beyond the movement threshold.
      if (Math.sqrt(dx * dx + dy * dy) > threshold) return LONG_PRESS_IDLE;
      return current;
    }
    case "pointerup":
    case "pointercancel":
    case "pointerleave": {
      return current.phase === "armed" ? LONG_PRESS_IDLE : current;
    }
  }
}

// ---------------------------------------------------------------------------
// isCoarsePointer helper
// ---------------------------------------------------------------------------

/**
 * Returns ``true`` when the primary pointing device is coarse (touch or
 * stylus).
 *
 * Fallback rules:
 *
 * - SSR (``window`` not defined) → ``false``.
 * - ``window.matchMedia`` not implemented (older jsdom, some test
 *   environments) → caught by ``try/catch``, returns ``false``.
 * - Test environments that stub ``window.matchMedia`` return whatever the
 *   stub specifies for ``"(pointer: coarse)"``.
 */
export function isCoarsePointer(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.matchMedia("(pointer: coarse)").matches;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Svelte action
// ---------------------------------------------------------------------------

/** Parameters accepted by the :func:`longpress` Svelte action. */
export interface LongPressParams {
  /**
   * Callback invoked with the viewport ``(x, y)`` of the initiating
   * ``pointerdown`` when the long-press threshold is reached.
   */
  readonly onLongPress: (x: number, y: number) => void;
  /**
   * Override the default 500 ms press duration.  Useful in tests that
   * want a shorter or longer timeout.
   */
  readonly durationMs?: number;
  /** Override the default 8 px movement threshold. */
  readonly thresholdPx?: number;
}

/**
 * Svelte action — wires pointer events on ``node`` to fire ``onLongPress``
 * after a 500 ms hold without movement on coarse-pointer devices.
 *
 * Short-circuits to a no-op ``destroy`` function when
 * :func:`isCoarsePointer` returns ``false``, so the caller never needs
 * to branch on pointer type.
 *
 * Cancellation conditions: pointer moves > 8 px (Euclidean), or any of
 * ``pointerup`` / ``pointercancel`` / ``pointerleave`` fires before the
 * timer expires.
 */
export function longpress(
  node: HTMLElement,
  params: LongPressParams,
): { destroy: () => void } {
  // No-op on fine (mouse / trackpad) pointer devices.
  if (!isCoarsePointer()) {
    return { destroy(): void {} };
  }

  let fsm: LongPressState = LONG_PRESS_IDLE;
  let timerId: ReturnType<typeof setTimeout> | null = null;
  const duration = params.durationMs ?? LONG_PRESS_DURATION_MS;

  function cancelTimer(): void {
    if (timerId !== null) {
      clearTimeout(timerId);
      timerId = null;
    }
  }

  function dispatch(event: LongPressInputEvent): void {
    const prev = fsm;
    fsm = reduceLongPress(fsm, event, { thresholdPx: params.thresholdPx });

    if (prev.phase !== "armed" && fsm.phase === "armed") {
      // Transition idle → armed: schedule the callback timer.
      cancelTimer();
      const fireX = fsm.startX;
      const fireY = fsm.startY;
      timerId = setTimeout(() => {
        timerId = null;
        fsm = LONG_PRESS_IDLE;
        params.onLongPress(fireX, fireY);
      }, duration);
    } else if (prev.phase === "armed" && fsm.phase === "idle") {
      // Transition armed → idle (cancelled): discard the timer.
      cancelTimer();
    }
  }

  function onPointerDown(e: PointerEvent): void {
    dispatch({ type: "pointerdown", x: e.clientX, y: e.clientY, pointerType: e.pointerType });
  }
  function onPointerMove(e: PointerEvent): void {
    dispatch({ type: "pointermove", x: e.clientX, y: e.clientY });
  }
  function onPointerUp(): void {
    dispatch({ type: "pointerup" });
  }
  function onPointerCancel(): void {
    dispatch({ type: "pointercancel" });
  }
  function onPointerLeave(): void {
    dispatch({ type: "pointerleave" });
  }

  node.addEventListener("pointerdown", onPointerDown);
  node.addEventListener("pointermove", onPointerMove);
  node.addEventListener("pointerup", onPointerUp);
  node.addEventListener("pointercancel", onPointerCancel);
  node.addEventListener("pointerleave", onPointerLeave);

  return {
    destroy(): void {
      cancelTimer();
      node.removeEventListener("pointerdown", onPointerDown);
      node.removeEventListener("pointermove", onPointerMove);
      node.removeEventListener("pointerup", onPointerUp);
      node.removeEventListener("pointercancel", onPointerCancel);
      node.removeEventListener("pointerleave", onPointerLeave);
    },
  };
}
