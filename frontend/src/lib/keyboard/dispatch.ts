/**
 * Keybinding dispatch — the single window-level keydown listener that
 * matches an event against the static binding table and fires the
 * registered handler.
 *
 * Behavior anchors:
 *
 * - ``docs/behavior/keyboard-shortcuts.md`` §"Conflict resolution" —
 *   a duplicate registration crashes early in development; the
 *   :func:`buildRegistry` helper enforces this at construction.
 * - §"Contexts" — composer-focused / modal-open suppression on
 *   non-``global`` bindings.
 * - §"What the user sees" — a duplicate chord registration MUST throw
 *   so a typo cannot silently shadow a working chord in production.
 */
import { KEYBOARD_SHORTCUT_STRINGS } from "../config";
import { chordKey, eventToCodeKey, eventToNamedKey, type ChordMatch } from "./chord";
import { KEYBINDINGS, type KeybindingSpec } from "./bindings";
import { getHandler, keybindingsState } from "./store.svelte";

/**
 * Lookup table — chord-key → spec. Two entries per non-``displayOnly``
 * binding when the chord uses ``key`` (so the shift-stripped fallback
 * also matches). ``displayOnly`` bindings (e.g. Ctrl+K wired by the
 * sidebar search component itself) are NOT inserted; the cheat sheet
 * still renders them, but the global dispatcher does not consume them.
 */
type Registry = ReadonlyMap<string, KeybindingSpec>;

/**
 * Build the registry from a binding list. Throws on duplicate chord
 * keys. The build runs once at module-load (see :data:`registry`); the
 * exported function is reachable from tests so a stub list can be used
 * to assert the conflict-detection path.
 */
export function buildRegistry(bindings: readonly KeybindingSpec[]): Registry {
  const map = new Map<string, KeybindingSpec>();
  for (const binding of bindings) {
    if (binding.displayOnly === true) {
      continue;
    }
    insertOrThrow(map, chordKey(binding.chord), binding);
    // For named-key chords, also insert a shift-agnostic entry so a
    // layout that produces ``?`` without Shift still matches.
    if (binding.chord.key !== undefined && binding.chord.shift !== true) {
      const shiftVariant: ChordMatch = { ...binding.chord, shift: true };
      insertOrThrow(map, chordKey(shiftVariant), binding);
    }
  }
  return map;
}

function insertOrThrow(
  map: Map<string, KeybindingSpec>,
  key: string,
  binding: KeybindingSpec,
): void {
  if (map.has(key)) {
    throw new Error(
      `${KEYBOARD_SHORTCUT_STRINGS.duplicateChordError} (chord=${key}, action=${binding.id})`,
    );
  }
  map.set(key, binding);
}

/** The single registry the runtime dispatcher reads. */
const registry: Registry = buildRegistry(KEYBINDINGS);

/**
 * Look up a binding for a keyboard event. Returns ``undefined`` when
 * no binding matches the chord — the caller defaults to native
 * behavior in that case (e.g. PgUp scrolls).
 *
 * Probes in order:
 *
 * 1. Code-based key (``KeyC`` etc.) — letter / digit chords.
 * 2. Named-key (``Escape``, ``[``, ``?``, etc.) — symbol / named
 *    chords. The registry has been pre-populated with both
 *    shift-on and shift-off variants for chords that did not pin
 *    Shift explicitly, so a single named-key probe matches both
 *    layouts where ``?`` requires Shift to type and layouts where
 *    it does not.
 */
export function lookupBindingForEvent(event: KeyboardEvent): KeybindingSpec | undefined {
  const codeKey = eventToCodeKey(event);
  const codeMatch = registry.get(codeKey);
  if (codeMatch !== undefined) return codeMatch;

  const namedKey = eventToNamedKey(event);
  const namedMatch = registry.get(namedKey);
  if (namedMatch !== undefined) return namedMatch;

  return undefined;
}

/**
 * Whether the given binding is allowed to fire under the current
 * focus / modal context. The rules:
 *
 * - ``global: true`` always fires.
 * - ``allowInModalContext: true`` fires unless an input is focused
 *   (modal-open alone does not block it). This allows a toggle binding
 *   to close the very modal it opened — e.g. ``?`` dismisses the cheat
 *   sheet on a second press.
 * - ``global: false`` (default) fires iff no input is focused AND no
 *   modal is open.
 *
 * Mirrors the doc §"Contexts" rules without expressing the modal +
 * input states as mutually exclusive (a modal can have an input
 * focused inside it; both flags can be ``true`` simultaneously).
 */
export function bindingAllowedInContext(
  binding: KeybindingSpec,
  state: { composerFocused: boolean; modalOpen: boolean },
): boolean {
  if (binding.global) return true;
  if (state.composerFocused) return false;
  if (state.modalOpen && !binding.allowInModalContext) return false;
  return true;
}

/**
 * Dispatch a keydown event against the registry. Pure-ish: the
 * function looks up + invokes a handler, but produces no side effects
 * beyond the handler call + ``preventDefault()``. Returns the action
 * id that was fired, or ``undefined`` when no handler ran (lookup
 * miss, blocked by context, or no handler bound).
 */
export function dispatchKeyEvent(event: KeyboardEvent): string | undefined {
  const binding = lookupBindingForEvent(event);
  if (binding === undefined) return undefined;
  if (!bindingAllowedInContext(binding, keybindingsState)) return undefined;
  const handler = getHandler(binding.id);
  if (handler === undefined) return undefined;
  event.preventDefault();
  handler();
  return binding.id;
}
