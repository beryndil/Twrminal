/**
 * Checkpoint refresh bus (G6) — a tiny shared store the composer and
 * message-turn surfaces bump after creating a checkpoint, so that the
 * gutter (which fetches the per-session list itself) refreshes without
 * a tight coupling between writer and reader.
 *
 * The composer's ``/checkpoint`` slash-command and the
 * ``message.split_here`` / ``message.fork_from_here`` context-menu
 * actions create checkpoints via the API; bumping ``refreshKey`` on a
 * shared store is cheaper than passing a callback prop down through
 * every parent in between. The gutter watches the key as a dependency
 * inside its ``listCheckpoints`` effect.
 */

interface CheckpointBusState {
  /** Monotonically increasing tick — bump to nudge the gutter to re-fetch. */
  refreshKey: number;
}

const state: CheckpointBusState = $state({
  refreshKey: 0,
});

export const checkpointBus = state;

/** Bump ``refreshKey`` so the gutter re-fetches its list. */
export function bumpCheckpointRefresh(): void {
  state.refreshKey += 1;
}

/** Test seam — resets the tick to zero. */
export function _resetForTests(): void {
  state.refreshKey = 0;
}
