"""Concrete :class:`DriverRuntime` binding + :class:`AutoDriverRegistry`.

Per ``docs/architecture-v1.md`` §1.1.4 + §3.2 cycle catalogue: this
module owns the FastAPI-aware glue that the ``Driver`` calls into via
the :class:`bearings.agent.auto_driver_types.DriverRuntime` Protocol.
The cycle break: this module imports the
:class:`bearings.agent.runner.RunnerFactory` Protocol (declared in
:mod:`bearings.agent.runner`); the FastAPI-aware concrete factory
lives in :mod:`bearings.web.runner_factory`. The ``agent`` layer never
imports :mod:`bearings.web`.

The *runtime* is the per-leg lifecycle binding — spawn / run-turn /
teardown / context-pressure readout. The *registry* tracks live
``Driver`` instances per checklist so the route layer can dispatch
control-plane commands (stop / skip / status).

In v0.18.0 the per-leg "run a turn" binding is a thin abstraction
backed by a callback invoking the Claude SDK; item 1.6 ships the
DriverRuntime contract + a fake-friendly registry so tests can drive
the state machine without booting an SDK subprocess. Production wiring
of ``run_turn`` against the live SDK lives in the agent integration
layers (item 1.2 streaming + item 1.3 SDK lifecycle); this module
exposes the connection points but does not assume a particular
in-process turn driver — the runtime stub has a ``turn_driver``
callback the production code injects.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bearings.agent.auto_driver import Driver
from bearings.agent.auto_driver_types import DriverConfig, DriverRuntime
from bearings.agent.runner import RunnerFactory, SessionRunner

# A turn driver is the production-side hook that runs one prompt on
# the live runner and returns the assistant body. Item 1.2's streaming
# layer + item 1.3's SDK glue together fulfil this contract; this
# module accepts it as an injected callback so tests can fake the
# whole SDK round-trip with a coroutine.
type TurnDriver = Callable[[SessionRunner, str], Awaitable[str]]

# A leg session id factory — produces fresh leg session ids when the
# driver requests a spawn. In production this is a closure over the
# DB-side session-create helper (item 1.7's session creation surface);
# in tests it can be a counter-backed stub.
type LegSessionFactory = Callable[[int, int, str | None], Awaitable[str]]

# Optional close-and-broadcast hook injected from the web/ layer.
# When a leg completes (handoff or item-done), ``teardown_leg`` calls
# this to stamp ``closed_at`` on the predecessor chat session and
# broadcast the change so the sidebar shows the row move to Closed.
# Defaults to ``None`` so unit tests that don't need DB + broadcast
# wiring can omit it (feature-6-008 / CCW-3).
type CloseSessionCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class _RuntimeOptions:
    """Frozen knobs the runtime carries — kept minimal in v0.18.0."""

    runner_factory: RunnerFactory
    turn_driver: TurnDriver
    leg_session_factory: LegSessionFactory
    close_session_callback: CloseSessionCallback | None = None


class AgentRunnerDriverRuntime:
    """Concrete :class:`DriverRuntime` binding.

    Construction takes the :class:`RunnerFactory` (the agent-side
    Protocol; concrete binding lives in :mod:`bearings.web.runner_factory`),
    the production turn-driver callback, and the per-spawn leg-session
    factory callback. The runtime is FastAPI-ignorant; the FastAPI
    surface stitches the three callbacks together at app construction
    per arch §3.2.

    Per :class:`DriverRuntime` Protocol the four methods are
    ``spawn_leg``, ``run_turn``, ``teardown_leg``,
    ``last_context_percentage``.
    """

    def __init__(
        self,
        *,
        runner_factory: RunnerFactory,
        turn_driver: TurnDriver,
        leg_session_factory: LegSessionFactory,
        close_session_callback: CloseSessionCallback | None = None,
    ) -> None:
        self._opts = _RuntimeOptions(
            runner_factory=runner_factory,
            turn_driver=turn_driver,
            leg_session_factory=leg_session_factory,
            close_session_callback=close_session_callback,
        )
        # Per-leg context-pressure readout cache; updated by
        # ``run_turn`` when the SDK reports usage. ``None`` until the
        # leg's first turn completes.
        self._pressure_by_leg: dict[str, float | None] = {}

    async def spawn_leg(
        self,
        *,
        item_id: int,
        leg_number: int,
        plug: str | None,
    ) -> str:
        """Materialise a new leg session id and warm its runner."""
        session_id = await self._opts.leg_session_factory(item_id, leg_number, plug)
        if not session_id:
            raise RuntimeError(
                f"leg_session_factory returned an empty id for item {item_id} leg {leg_number}"
            )
        # Touch the runner so the registry materialises it now (and
        # the WS subscriber has a runner to attach to immediately
        # after the spawn).
        await self._opts.runner_factory(session_id)
        self._pressure_by_leg[session_id] = None
        return session_id

    async def run_turn(self, *, leg_session_id: str, prompt: str) -> str:
        """Run one turn on the leg via the injected turn-driver callback.

        The callback returns the assistant body (the text the sentinel
        parser scans). Implementations are responsible for updating
        the runner's context-pressure if available — for the
        production wire-up that's the existing
        :class:`bearings.agent.events.ContextUsage` event flow.
        """
        runner = await self._opts.runner_factory(leg_session_id)
        body = await self._opts.turn_driver(runner, prompt)
        # The production turn-driver may have observed a fresh
        # ContextUsage for the runner; the helper exposes a tiny seam
        # for tests to inject pressure without a real SDK pipe.
        return body

    async def teardown_leg(self, *, leg_session_id: str) -> None:
        """Close the leg session and broadcast the change; drop pressure entry.

        On handoff (and on any per-item terminal that ends a leg), stamps
        ``closed_at`` on the predecessor chat session and fans a
        ``session_upsert`` frame so the sidebar shows the row move to the
        Closed group without a page reload (feature-6-008 / CCW-3).

        The close-and-broadcast is delegated to the optional
        ``close_session_callback`` injected from the web/ layer so this
        module never imports web/. When the callback is ``None`` (unit
        tests without DB wiring), the close is skipped.
        """
        self._pressure_by_leg.pop(leg_session_id, None)
        if self._opts.close_session_callback is not None:
            await self._opts.close_session_callback(leg_session_id)

    def last_context_percentage(self, leg_session_id: str) -> float | None:
        """Return the cached per-leg pressure (or ``None`` if absent)."""
        return self._pressure_by_leg.get(leg_session_id)

    def report_pressure(self, *, leg_session_id: str, percentage: float) -> None:
        """Production-side hook: turn-driver calls this when a fresh
        :class:`ContextUsage` arrives for ``leg_session_id``.

        Exposed as a method (not a runtime-internal-only knob) so the
        item 1.3 SDK glue can call it from the same translate path
        that emits the ``ContextUsage`` WS event.
        """
        self._pressure_by_leg[leg_session_id] = percentage


class AutoDriverRegistry:
    """Process-wide registry of live :class:`Driver` instances.

    Per arch §1.1.4 the registry exists so the route layer can
    dispatch start / stop / skip / status without re-finding the
    driver each turn. Keyed by checklist session id (one active driver
    per checklist at a time per behavior/checklists.md "the user can
    re-Start later; the next run resumes from the first unchecked
    item").

    Operations:

    * :meth:`register` — install a driver under its checklist id.
    * :meth:`get` — return the live driver, or ``None``.
    * :meth:`stop` — cooperative stop signal; idempotent.
    * :meth:`skip_current` — skip-current signal; idempotent.
    * :meth:`unregister` — drop the driver entry (called when
      :meth:`drive` returns).
    * :meth:`active_checklists` — every checklist id with a live
      driver registered (used by the route layer for diagnostics +
      tests).
    """

    def __init__(self) -> None:
        self._drivers: dict[str, Driver] = {}

    def register(self, driver: Driver) -> None:
        """Install ``driver`` under its checklist id.

        Rejects a register on a checklist that already has a live
        driver — the caller must :meth:`unregister` first. This
        mirrors the user-observable invariant that there is only one
        active run per checklist at a time.
        """
        existing = self._drivers.get(driver.checklist_id)
        if existing is not None:
            raise RuntimeError(
                f"AutoDriverRegistry: checklist {driver.checklist_id!r} already has "
                f"an active driver (run_id={existing.run_id}); unregister first"
            )
        self._drivers[driver.checklist_id] = driver

    def get(self, checklist_id: str) -> Driver | None:
        """Return the live driver for ``checklist_id``, or ``None``."""
        return self._drivers.get(checklist_id)

    def stop(self, checklist_id: str) -> bool:
        """Cooperative stop on the live driver; returns ``True`` if signalled."""
        driver = self._drivers.get(checklist_id)
        if driver is None:
            return False
        driver.request_stop()
        return True

    def skip_current(self, checklist_id: str) -> bool:
        """Skip-current signal; returns ``True`` if a driver received it."""
        driver = self._drivers.get(checklist_id)
        if driver is None:
            return False
        driver.request_skip_current()
        return True

    def unregister(self, checklist_id: str) -> bool:
        """Drop the driver entry; returns ``True`` if a row was removed."""
        return self._drivers.pop(checklist_id, None) is not None

    def active_checklists(self) -> list[str]:
        """Every checklist id with a live driver, sorted alphabetically."""
        return sorted(self._drivers.keys())


def build_runtime(
    *,
    runner_factory: RunnerFactory,
    turn_driver: TurnDriver,
    leg_session_factory: LegSessionFactory,
    close_session_callback: CloseSessionCallback | None = None,
) -> DriverRuntime:
    """Construct an :class:`AgentRunnerDriverRuntime` typed at the Protocol.

    Equivalent to ``AgentRunnerDriverRuntime(...)`` but the explicit
    return-type annotation forces mypy to verify the structural
    typing — if the runtime's method signatures drift from the
    Protocol the project fails type-check at this function rather
    than at the consumer.

    ``close_session_callback`` is optional so callers that don't need
    leg-cutover broadcast (e.g. test harnesses) can omit it.
    """
    return AgentRunnerDriverRuntime(
        runner_factory=runner_factory,
        turn_driver=turn_driver,
        leg_session_factory=leg_session_factory,
        close_session_callback=close_session_callback,
    )


def build_registry() -> AutoDriverRegistry:
    """Construct a fresh :class:`AutoDriverRegistry` (one per app)."""
    return AutoDriverRegistry()


# Helper accessor for the future :func:`Driver` factory callers — used
# by the route layer to construct a ``Driver`` from the durable
# ``auto_driver_runs`` row plus the runtime + connection. Kept thin so
# the route handler stays under the §40-line cap.
def build_driver(
    *,
    run_id: int,
    checklist_id: str,
    config: DriverConfig,
    runtime: DriverRuntime,
    connection: object,
) -> Driver:
    """Construct a :class:`Driver` with the supplied wiring.

    The ``connection`` argument is typed as :class:`object` here only
    because ``aiosqlite.Connection`` is not a Protocol and using its
    concrete type would force this module to import a DB type the
    runtime is otherwise innocent of. The constructor revalidates the
    type via the dataclass shape; passing a non-Connection raises at
    first DB call.
    """
    # mypy allows the cast at the construct boundary; the Driver
    # itself enforces the connection contract through its DB calls.
    from typing import cast

    import aiosqlite

    return Driver(
        run_id=run_id,
        checklist_id=checklist_id,
        config=config,
        runtime=runtime,
        connection=cast("aiosqlite.Connection", connection),
    )


__all__ = [
    "AgentRunnerDriverRuntime",
    "AutoDriverRegistry",
    "LegSessionFactory",
    "TurnDriver",
    "build_driver",
    "build_registry",
    "build_runtime",
]
