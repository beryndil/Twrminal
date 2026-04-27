"""Per-item state machine and followup application.

:class:`_DispatchMixin` carries the bulk of the driver's behavior:
``_drive_item`` walks one checklist item through up to ``max_legs``
legs, parsing sentinels and applying followups; ``_drive_blocking_children``
recurses into freshly-filed blocker children; ``_apply_followups``
materializes the agent's filed work into checklist rows.

Extracted from ``auto_driver.py`` (§FileSize); bodies unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite

from bearings.agent.auto_driver import prompts
from bearings.agent.auto_driver.contracts import (
    DriverConfig,
    DriverRuntime,
    _ItemOutcome,
)
from bearings.agent.checklist_sentinels import Followup
from bearings.agent.checklist_sentinels import parse as parse_sentinels
from bearings.db import store

log = logging.getLogger(__name__)


class _DispatchMixin:
    """Driver methods for the per-item state machine."""

    # Type-only attribute declarations (populated by Driver.__init__).
    _conn: aiosqlite.Connection
    _runtime: DriverRuntime
    _config: DriverConfig
    _stop: asyncio.Event
    _items_completed: int
    _items_skipped: int
    _items_blocked: int
    _legs_spawned: int

    # Methods provided by sibling mixins. Declaring them here keeps
    # mypy strict happy when this mixin's bodies call self._mark_done
    # etc. without inheriting from the sibling class directly. The
    # concrete Driver subclass picks up real implementations from
    # _PersistenceMixin and _SessionsMixin via multiple inheritance;
    # the bodies below are unreachable in practice. Raising rather
    # than returning makes the wrong inheritance order loud instead
    # of silently returning None.
    _MIXIN_NOT_BOUND = (
        "Mixin stub called directly. Driver must inherit "
        "_PersistenceMixin and _SessionsMixin before _DispatchMixin "
        "so MRO resolves real implementations first."
    )

    async def _mark_done(self, item_id: int) -> None:
        raise NotImplementedError(self._MIXIN_NOT_BOUND)

    async def _mark_blocked(
        self,
        item_id: int,
        *,
        category: str,
        reason: str,
        tried: tuple[str, ...],
    ) -> None:
        raise NotImplementedError(self._MIXIN_NOT_BOUND)

    async def _record_failure(self, item_id: int, reason: str) -> None:
        raise NotImplementedError(self._MIXIN_NOT_BOUND)

    async def _existing_open_session(self, item: dict[str, Any]) -> str | None:
        raise NotImplementedError(self._MIXIN_NOT_BOUND)

    async def _existing_session_still_open(self, session_id: str) -> bool:
        raise NotImplementedError(self._MIXIN_NOT_BOUND)

    async def _request_completion_nudge(self, leg_session_id: str, *, under_pressure: bool) -> str:
        raise NotImplementedError(self._MIXIN_NOT_BOUND)

    async def _drive_item(self, item: dict[str, Any], *, depth: int) -> _ItemOutcome:
        """Work a single item (possibly recursively). Returns one of
        DONE / FAILED / SKIPPED / BLOCKED so the outer loop can apply
        the right policy:

        - DONE: item is checked, advance.
        - FAILED: item couldn't complete; halt (default) or advance
          (failure_policy=skip).
        - SKIPPED: item was deliberately not attempted (visit-mode
          with no linked session); always advance.
        - BLOCKED: item set aside for Dave; always advance.
        """
        if depth > self._config.max_followup_depth:
            await self._record_failure(
                item["id"],
                f"followup nesting exceeded depth {self._config.max_followup_depth}",
            )
            return _ItemOutcome.FAILED

        # A prior leg may have left blocking children. Drive them
        # first — the parent can't complete until every child is
        # checked (the toggle cascade enforces this at the storage
        # layer, but the driver needs to respect it explicitly so we
        # don't waste a leg proving the point).
        if not await self._drive_blocking_children(item, depth=depth):
            return _ItemOutcome.FAILED

        # Visit-existing mode: leg 1 uses the session already linked
        # to this item via `chat_session_id`, if one exists and is
        # open. Items with no usable existing session are skipped
        # entirely — recorded in `items_skipped` and the outer loop
        # advances. Handoff legs (leg 2+) still spawn fresh as usual;
        # the contract is "first leg uses what's there, successors
        # are mine".
        existing_for_leg_one: str | None = None
        if self._config.visit_existing_sessions:
            existing_for_leg_one = await self._existing_open_session(item)
            if existing_for_leg_one is None:
                # No usable existing session. The skip-when-unlinked
                # rule applies only to TOP-LEVEL user-curated items
                # (the visit-existing contract is "walk a curated set
                # of pre-paired chats"). A nested child item — created
                # by the driver itself when a parent emitted
                # CHECKLIST_BLOCKED / CHECKLIST_FOLLOWUP block=yes —
                # has no pre-existing chat by construction; it's a
                # fresh fix-it session the driver needs to spawn. Fall
                # through to the spawn path for those (the leg loop
                # below will spawn_leg since existing_for_leg_one is
                # still None). Top-level unlinked items still skip.
                if item.get("parent_item_id") is None:
                    self._items_skipped += 1
                    log.info(
                        "autonomous driver: skipping item %s — no open chat "
                        "session linked (visit_existing_sessions=True)",
                        item["id"],
                    )
                    return _ItemOutcome.SKIPPED

        plug: str | None = None
        # Labels of blocking children resolved in the most recent
        # iteration. Non-empty means "we just finished a fix-and-return
        # blocker cycle; this leg is the parent resuming." Drives the
        # continuation-prompt path below and the visit-existing
        # reentry decision (reuse the original session so the agent's
        # in-context memory of what it was trying isn't thrown away).
        resolved_blocker_labels: list[str] = []
        for leg in range(1, self._config.max_legs_per_item + 1):
            if self._stop.is_set():
                return _ItemOutcome.FAILED
            # Three scenarios for which session this leg runs against:
            #
            # 1. Visit-existing leg 1 — reuse the session linked via
            #    `chat_session_id`. Already established above.
            # 2. Visit-existing parent reentry after blocker fixes —
            #    REUSE the same existing session id so the agent
            #    picks up where it left off with full memory of what
            #    it was trying. The fix-and-return contract ("go back
            #    to the first session"). Requires the existing
            #    session is still open; if it closed mid-blocker
            #    (rare — close cascade on an unrelated path), fall
            #    through to spawn-fresh.
            # 3. Anything else (spawn-fresh mode, visit-existing
            #    handoff legs, blocker reentry when the original
            #    session is gone) — spawn a fresh leg.
            leg_was_spawned = True
            visit_reentry = False
            if leg == 1 and existing_for_leg_one is not None:
                leg_session_id = existing_for_leg_one
                leg_was_spawned = False
            elif (
                resolved_blocker_labels
                and existing_for_leg_one is not None
                and await self._existing_session_still_open(existing_for_leg_one)
            ):
                leg_session_id = existing_for_leg_one
                leg_was_spawned = False
                visit_reentry = True
            else:
                leg_session_id = await self._runtime.spawn_leg(item=item, leg_number=leg, plug=plug)
            self._legs_spawned += 1
            try:
                if visit_reentry:
                    prompt = prompts.build_continuation_prompt(item, resolved_blocker_labels)
                else:
                    prompt = prompts.build_kickoff_prompt(item, leg, plug)
                # Consume the resolved-labels carry so a subsequent
                # iteration that doesn't follow a blocker cycle uses
                # the kickoff prompt path.
                resolved_blocker_labels = []
                assistant_text = await self._runtime.run_turn(
                    session_id=leg_session_id, prompt=prompt
                )
            except Exception as exc:
                # A runtime-raised exception ends the leg as a failure;
                # the item is not retryable via another leg because we
                # don't know the agent's state. Fail-safe halt.
                if leg_was_spawned:
                    await self._runtime.teardown_leg(leg_session_id)
                await self._record_failure(
                    item["id"],
                    f"runtime error in leg {leg}: {exc}",
                )
                return _ItemOutcome.FAILED
            if leg_was_spawned:
                await self._runtime.teardown_leg(leg_session_id)

            sentinels = parse_sentinels(assistant_text)
            created_blocking = await self._apply_followups(item, sentinels.followups)

            if sentinels.item_done:
                # If the agent tried to file blocking followups AND
                # call itself done, honor blocking-first: drive the
                # children, then mark done. The toggle cascade ensures
                # the parent's checked_at only sticks when children
                # are all checked, but we want both flags set in the
                # order the agent implied.
                if created_blocking:
                    if not await self._drive_blocking_children(item, depth=depth):
                        return _ItemOutcome.FAILED
                await self._mark_done(item["id"])
                self._items_completed += 1
                return _ItemOutcome.DONE

            if sentinels.item_blocked is not None:
                # Item is genuinely outside the agent's reach (pay a
                # bill, plug in hardware, supply a 2FA code). Stamp
                # blocked, leave the paired session OPEN for Dave,
                # advance regardless of `failure_policy`. The parser
                # already enforced category-whitelist + non-empty
                # TRIED:; reaching this branch means the sentinel
                # was well-formed and the agent provided real
                # attempt evidence. The leg is torn down (already
                # happened above) but the session row stays alive
                # in the sidebar for Dave to type into.
                blocked = sentinels.item_blocked
                await self._mark_blocked(
                    item["id"],
                    category=blocked.category,
                    reason=blocked.reason,
                    tried=blocked.tried,
                )
                return _ItemOutcome.BLOCKED

            if sentinels.handoff_plug is not None:
                plug = sentinels.handoff_plug
                continue

            if created_blocking:
                # Agent chose to block the item on newly-filed children
                # without marking done or handing off. Drive the
                # children, then re-enter the parent.
                #
                # Capture the just-filed blocker labels BEFORE driving
                # so the next iteration can use them in the
                # continuation prompt ("the blocker(s) you raised
                # have been resolved: ..."). In visit-existing mode
                # the next iteration also reuses the same existing
                # session id so the agent's prior context (what it
                # was trying, what it had ruled out) carries forward.
                resolved_blocker_labels = [fu.label for fu in sentinels.followups if fu.blocking]
                if not await self._drive_blocking_children(item, depth=depth):
                    return _ItemOutcome.FAILED
                plug = None
                continue

            # No done, no handoff, no blocking children. Before calling
            # it a silent-exit failure, ALWAYS nudge once. This used to
            # fire only under context pressure on the assumption that
            # silent-exits below the handoff threshold meant the agent
            # had genuinely nothing to say — but the L4.1 leg on
            # 2026-04-26 disproved that: an agent answered design
            # questions in normal prose, ended its turn without a
            # sentinel, and the run halted at low context. The nudge is
            # cheap (one extra turn) and recovers the common
            # forgot-the-sentinel failure mode. We adapt the prompt to
            # the pressure state so the agent knows whether HANDOFF or
            # DONE is the more likely missing sentinel; the agent is
            # free to emit either regardless.
            pct = self._runtime.last_context_percentage(leg_session_id)
            under_pressure = pct is not None and pct >= self._config.handoff_threshold_percent
            nudge_text = await self._request_completion_nudge(
                leg_session_id, under_pressure=under_pressure
            )
            nudge_sentinels = parse_sentinels(nudge_text)
            # A nudge-turn followup would be unusual (the ask was
            # "just emit a sentinel") but we honor one if it arrives
            # to avoid losing agent-noted work.
            await self._apply_followups(item, nudge_sentinels.followups)
            if nudge_sentinels.item_done:
                await self._mark_done(item["id"])
                self._items_completed += 1
                return _ItemOutcome.DONE
            if nudge_sentinels.item_blocked is not None:
                # Same path as the main-turn handler — agent realized
                # mid-nudge that the item is blocked. Honor it.
                blocked = nudge_sentinels.item_blocked
                await self._mark_blocked(
                    item["id"],
                    category=blocked.category,
                    reason=blocked.reason,
                    tried=blocked.tried,
                )
                return _ItemOutcome.BLOCKED
            if nudge_sentinels.handoff_plug is not None:
                plug = nudge_sentinels.handoff_plug
                continue
            # Nudge also silent — fall through to failure. Two reason
            # strings so the UI can distinguish "stubbornly refused
            # under pressure" from "still didn't realize the sentinel
            # protocol applied at low context."
            if under_pressure:
                assert pct is not None
                reason = (
                    f"context at {pct:.1f}% but agent refused to emit "
                    "a handoff plug even when asked explicitly"
                )
            else:
                reason = (
                    "agent ended turn without emitting a completion "
                    "sentinel (CHECKLIST_ITEM_DONE / CHECKLIST_HANDOFF); "
                    "nudge response also produced no sentinel"
                )
            await self._record_failure(item["id"], reason)
            return _ItemOutcome.FAILED

        # Max legs exceeded — the agent kept handing off. Something is
        # wrong with how the item is scoped.
        await self._record_failure(
            item["id"],
            f"exceeded max_legs_per_item ({self._config.max_legs_per_item})",
        )
        return _ItemOutcome.FAILED

    async def _drive_blocking_children(self, item: dict[str, Any], *, depth: int) -> bool:
        """Drive every unchecked direct child of ``item`` to completion.
        Returns True when every child succeeds, False on the first
        failure (the parent can't proceed). A child SKIPPED outcome
        also blocks the parent — a blocking child the driver couldn't
        even attempt is still incomplete from the parent's POV."""
        while True:
            if self._stop.is_set():
                return False
            children = await store.list_unchecked_children(self._conn, item["id"])
            if not children:
                return True
            child = children[0]
            child_outcome = await self._drive_item(child, depth=depth + 1)
            if child_outcome != _ItemOutcome.DONE:
                return False

    async def _apply_followups(self, item: dict[str, Any], followups: list[Followup]) -> bool:
        """Create checklist items for each followup.

        Blocking followups are appended as children of ``item`` (via
        ``parent_item_id``) and will be driven before the parent can
        complete. Non-blocking followups become top-level items at
        the end of the list and are picked up by the outer loop.

        Returns True if any blocking children were created on this
        call — signals the per-item loop to recurse before advancing.
        """
        created_blocking = False
        for fu in followups:
            if fu.blocking:
                await store.create_item(
                    self._conn,
                    item["checklist_id"],
                    label=fu.label,
                    parent_item_id=item["id"],
                )
                created_blocking = True
            else:
                await store.create_item(
                    self._conn,
                    item["checklist_id"],
                    label=fu.label,
                )
        return created_blocking
