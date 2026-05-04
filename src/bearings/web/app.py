"""FastAPI app factory.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/app.py`` is the
``create_app(...) -> FastAPI`` factory wiring lifespan + every route
module + the static-bundle mount. Item 1.2 laid the streaming-only
WebSocket surface; item 1.4 adds the tags + memories REST routes.
Future items (1.5+) extend with sessions / messages / checklists /
templates routes; the factory's signature stays additive.

Connection wiring
-----------------

The tags + memories route modules read a long-lived
:class:`aiosqlite.Connection` off ``app.state.db_connection``. Tests
inject a freshly-bootstrapped connection directly; production callers
(item 1.5+ ``cli/serve.py``) attach via FastAPI's lifespan event so
the connection lives for the app's lifetime and is closed at shutdown.
The factory accepts the connection as an optional argument so the
existing streaming-only test surface keeps working unchanged.

References:

* ``docs/architecture-v1.md`` §1.1.5 — web layer responsibilities.
* ``docs/behavior/tool-output-streaming.md`` — observable WS
  subscriber lifecycle.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Iterable

import aiosqlite
from fastapi import APIRouter, FastAPI, WebSocket

from bearings import __version__
from bearings.agent.auto_driver_runtime import AutoDriverRegistry, build_registry, build_runtime
from bearings.agent.prompt_dispatch import RateLimiter
from bearings.agent.quota import QuotaPoller
from bearings.agent.runner import RunnerFactory
from bearings.agent.session_bootstrap import build_session_setup
from bearings.agent.turn_driver import build_turn_driver
from bearings.config.constants import (
    OPENAPI_DESCRIPTION,
    OPENAPI_TITLE,
    ROUTE_TAG_APPROVALS,
    ROUTE_TAG_CHECKLISTS,
    ROUTE_TAG_COMMANDS,
    ROUTE_TAG_DIAG,
    ROUTE_TAG_FS,
    ROUTE_TAG_HEALTH,
    ROUTE_TAG_HISTORY,
    ROUTE_TAG_IMPORT,
    ROUTE_TAG_MEMORIES,
    ROUTE_TAG_MESSAGES,
    ROUTE_TAG_METRICS,
    ROUTE_TAG_PAIRED_CHATS,
    ROUTE_TAG_PREFERENCES,
    ROUTE_TAG_QUOTA,
    ROUTE_TAG_ROUTING,
    ROUTE_TAG_SESSIONS,
    ROUTE_TAG_SHELL,
    ROUTE_TAG_TAGS,
    ROUTE_TAG_UPLOADS,
    ROUTE_TAG_USAGE,
    ROUTE_TAG_VAULT,
    ROUTE_TAG_WS_SESSIONS,
    STREAM_HEARTBEAT_INTERVAL_S,
)
from bearings.config.settings import FsCfg, ShellCfg, UploadsCfg, VaultCfg
from bearings.db import checklists as checklists_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.metrics import BearingsMetrics
from bearings.web.routes.approvals import router as approvals_router
from bearings.web.routes.checklists import router as checklists_router
from bearings.web.routes.commands import router as commands_router
from bearings.web.routes.diag import router as diag_router
from bearings.web.routes.fs import router as fs_router
from bearings.web.routes.health import router as health_router
from bearings.web.routes.history import router as history_router
from bearings.web.routes.import_db import router as import_db_router
from bearings.web.routes.memories import router as memories_router
from bearings.web.routes.messages import router as messages_router
from bearings.web.routes.metrics import router as metrics_router
from bearings.web.routes.paired_chats import router as paired_chats_router
from bearings.web.routes.preferences import router as preferences_router
from bearings.web.routes.quota import router as quota_router
from bearings.web.routes.routing import router as routing_router
from bearings.web.routes.sessions import router as sessions_router
from bearings.web.routes.shell import router as shell_router
from bearings.web.routes.tags import router as tags_router
from bearings.web.routes.uploads import router as uploads_router
from bearings.web.routes.usage import router as usage_router
from bearings.web.routes.vault import router as vault_router
from bearings.web.routes.ws_sessions import SessionsBroadcaster
from bearings.web.routes.ws_sessions import router as ws_sessions_router
from bearings.web.runner_factory import (
    InProcessRunnerRegistry,
    build_in_process_factory,
)
from bearings.web.static import mount_static_bundle
from bearings.web.streaming import SINCE_SEQ_QUERY_PARAM, serve_session_stream

_LOG = logging.getLogger(__name__)


def _build_leg_session_factory(
    *,
    db: aiosqlite.Connection,
    sessions_broadcaster: SessionsBroadcaster,
) -> Callable[[int, int, str | None], Awaitable[str]]:
    """Return the :data:`LegSessionFactory` closure for the auto-driver runtime.

    The closure is called by :class:`bearings.agent.auto_driver_runtime.AgentRunnerDriverRuntime`
    when the driver needs to materialise a new chat session for a
    checklist item leg. It lives here (``web/`` layer) because it
    needs :class:`SessionsBroadcaster` from
    :mod:`bearings.web.routes.ws_sessions`, which the ``agent/`` layer
    must not import.

    Steps performed on each call:

    1. Look up the :class:`bearings.db.checklists.ChecklistItem` to get
       ``checklist_id`` and ``label``.
    2. Look up the parent checklist session to inherit ``working_dir``,
       ``model``, and routing fields.
    3. Inherit the parent's tag set via
       :func:`bearings.db.tags.list_for_session`.
    4. Create a new ``kind="chat"`` session with ``checklist_item_id``
       set (back-pointer used by ``GET /api/sessions/{id}/paired-chat-info``).
    5. Attach the inherited tags.
    6. Commit + broadcast the new session so the sidebar refreshes
       immediately.
    7. Return the new session id.

    Note: the :class:`bearings.agent.auto_driver.Driver` calls
    ``checklists_db.set_paired_chat`` *after* this factory returns, so
    the factory must NOT also call it (would double-write; the driver's
    write wins because it runs immediately after).
    """
    from bearings.web.routes.sessions import _to_out  # local import — avoids circularity

    async def _leg_session_factory(
        item_id: int,
        leg_number: int,
        plug: str | None,  # reserved for future prompt injection
    ) -> str:
        item = await checklists_db.get(db, item_id)
        if item is None:
            raise RuntimeError(f"leg_session_factory: checklist item {item_id} not found")
        checklist = await sessions_db.get(db, item.checklist_id)
        if checklist is None:
            raise RuntimeError(
                f"leg_session_factory: parent checklist session {item.checklist_id!r} not found"
            )
        tags = await tags_db.list_for_session(db, item.checklist_id)
        title = item.label if leg_number == 1 else f"{item.label} (leg {leg_number})"
        new_session = await sessions_db.create(
            db,
            kind="chat",
            title=title,
            working_dir=checklist.working_dir,
            model=checklist.model,
            checklist_item_id=item.id,
            routing_advisor_model=checklist.routing_advisor_model,
            routing_advisor_max_uses=checklist.routing_advisor_max_uses,
            routing_effort_level=checklist.routing_effort_level,
        )
        if tags:
            await tags_db.set_for_session(
                db,
                session_id=new_session.id,
                tag_ids=tuple(t.id for t in tags),
            )
        await db.commit()
        _LOG.info(
            "leg_session_factory: created leg session %r for item %d leg %d",
            new_session.id,
            item_id,
            leg_number,
        )
        sessions_broadcaster.publish_upsert(_to_out(new_session))
        return new_session.id

    return _leg_session_factory


def create_app(
    *,
    runner_factory: RunnerFactory | None = None,
    heartbeat_interval_s: float = STREAM_HEARTBEAT_INTERVAL_S,
    db_connection: aiosqlite.Connection | None = None,
    vault_cfg: VaultCfg | None = None,
    auto_driver_registry: AutoDriverRegistry | None = None,
    prompt_rate_limiter: RateLimiter | None = None,
    quota_poller: QuotaPoller | None = None,
    uploads_cfg: UploadsCfg | None = None,
    fs_cfg: FsCfg | None = None,
    shell_cfg: ShellCfg | None = None,
    extra_routers: Iterable[APIRouter] | None = None,
    enable_driver_dispatch: bool = False,
) -> FastAPI:
    """Construct the FastAPI app.

    ``runner_factory`` defaults to a fresh in-process registry so each
    app has its own runner fleet — important for parallel test runs
    that must not share runner state.

    ``heartbeat_interval_s`` is exposed for tests that want a short
    interval; production callers should leave the default.

    ``db_connection`` enables the tags + memories + vault REST routes.
    If ``None`` the routers are still mounted but every handler
    returns 503 (per :func:`bearings.web.routes.tags._db`); this
    matches the streaming-only contract item 1.2 ships under.

    ``vault_cfg`` is the :class:`VaultCfg` the vault routes scan with.
    Defaults to a fresh ``VaultCfg()`` (which points at
    ``~/.claude/plans`` + ``~/Projects/**/TODO.md``); tests inject a
    cfg whose roots / globs target a ``tmp_path`` so the vault
    surface is deterministic.

    ``auto_driver_registry`` is the live-driver registry the
    checklist run-control routes (item 1.6) dispatch
    stop / skip-current signals through. Defaults to a fresh
    :class:`AutoDriverRegistry` so each app has its own driver fleet
    (important for parallel test runs that must not share state).

    ``extra_routers`` is an injection seam used by E2E test harnesses
    (item 3.1; ``scripts/e2e_server.py``) to mount a debug router
    *before* the static-bundle mount so its endpoints take precedence
    over the SPA fallback. Production callers leave this ``None`` —
    no production code path uses it.
    """
    if heartbeat_interval_s <= 0:
        raise ValueError(f"heartbeat_interval_s must be > 0 (got {heartbeat_interval_s})")
    # When the caller hasn't injected a factory but DID supply a DB
    # connection, build the production supervisor binding: every
    # first-touch ``__call__`` materialises the per-session
    # AgentSession + composed OptionsKwargs from the row and spawns
    # ``run_session_loop`` as the worker. Per Slice A1.3 of
    # ``~/.claude/plans/wiring-agent-loop.md`` this is the seam that
    # makes POST /api/sessions/<id>/prompt actually run a turn.
    # Sessions-broadcast hub (item 2.6). Created unconditionally so the
    # ``/ws/sessions`` endpoint is always available; route handlers call
    # ``broadcaster.publish_*`` after every session mutation to fan
    # updates to all open sidebar tabs.
    sessions_broadcaster = SessionsBroadcaster()

    factory: RunnerFactory
    if runner_factory is not None:
        factory = runner_factory
    elif db_connection is not None:
        factory = build_in_process_factory(
            session_setup=build_session_setup(db_connection),
            sessions_broadcaster=sessions_broadcaster,
        )
    else:
        factory = build_in_process_factory(
            sessions_broadcaster=sessions_broadcaster,
        )
    app = FastAPI(
        title=OPENAPI_TITLE,
        description=OPENAPI_DESCRIPTION,
        version=__version__,
    )
    app.state.runner_factory = factory
    app.state.sessions_broadcaster = sessions_broadcaster
    app.state.heartbeat_interval_s = heartbeat_interval_s
    app.state.db_connection = db_connection
    app.state.vault_cfg = vault_cfg if vault_cfg is not None else VaultCfg()
    app.state.auto_driver_registry = (
        auto_driver_registry if auto_driver_registry is not None else build_registry()
    )
    # Auto-driver runtime (plan wiring-autodriver-dispatch). Built only
    # when both a DB connection is wired AND ``enable_driver_dispatch=True``
    # is passed. The flag defaults to ``False`` so test harnesses that
    # inject a DB connection (but do not want an autonomous driver running
    # in the background) are unaffected. Production callers (bearings serve CLI)
    # pass ``enable_driver_dispatch=True`` to activate the dispatch wire.
    if db_connection is not None and enable_driver_dispatch:
        _turn_driver = build_turn_driver(db_connection=db_connection)
        _leg_factory = _build_leg_session_factory(
            db=db_connection,
            sessions_broadcaster=sessions_broadcaster,
        )
        app.state.driver_runtime = build_runtime(
            runner_factory=factory,
            turn_driver=_turn_driver,
            leg_session_factory=_leg_factory,
        )
    else:
        app.state.driver_runtime = None
    # Misc-API sub-configurations (item 1.10; arch §1.1.5).
    app.state.uploads_cfg = uploads_cfg if uploads_cfg is not None else UploadsCfg()
    app.state.fs_cfg = fs_cfg if fs_cfg is not None else FsCfg()
    app.state.shell_cfg = shell_cfg if shell_cfg is not None else ShellCfg()
    # Process-uptime anchor (item 1.10; consumed by health + metrics +
    # diag/server). ``time.monotonic`` so a system-clock jump does not
    # fold uptime negative.
    app.state.start_time_monotonic = time.monotonic()
    # Per-app metrics bundle (arch §1.1.7). Owned by ``app.state`` so
    # parallel test runs don't clash on the global Prometheus
    # registry.
    app.state.metrics = BearingsMetrics(version=__version__)
    # Per-app rate limiter for the prompt endpoint (item 1.7;
    # ``docs/behavior/prompt-endpoint.md`` §"Rate-limit observable
    # behavior"). One limiter per app so parallel test runs do not
    # share rate-limit state across the in-memory deque.
    app.state.prompt_rate_limiter = (
        prompt_rate_limiter if prompt_rate_limiter is not None else RateLimiter()
    )
    # Optional quota poller (item 1.8; spec §4). The poller is
    # ``None``-able because tests routinely construct apps without
    # network access; the routing-preview + quota endpoints
    # gracefully fall back to the latest persisted snapshot when no
    # poller is wired. Production callers (``cli/serve.py`` once item
    # 1.10 lands) attach a real poller via the lifespan event.
    app.state.quota_poller = quota_poller

    @app.websocket("/ws/sessions/{session_id}")
    async def stream_endpoint(websocket: WebSocket, session_id: str) -> None:
        # Resume cursor — defaults to 0 (replay everything still in
        # ring buffer) per behavior doc §"Reconnect / replay". The
        # query parameter name is the constant from the streaming
        # module so a rename there fails type-check here.
        raw = websocket.query_params.get(SINCE_SEQ_QUERY_PARAM, "0")
        try:
            since_seq = int(raw)
        except ValueError:
            await websocket.close(code=1003, reason="invalid since_seq")
            return
        runner = await factory(session_id)
        await serve_session_stream(
            websocket,
            runner,
            since_seq=since_seq,
            heartbeat_interval_s=heartbeat_interval_s,
        )

    # Every router carries its tag so the ``/openapi.json`` export
    # groups operations correctly per coding-standards "no inline
    # string literals" — the tag names live in
    # :mod:`bearings.config.constants`.
    app.include_router(tags_router, tags=[ROUTE_TAG_TAGS])
    app.include_router(memories_router, tags=[ROUTE_TAG_MEMORIES])
    app.include_router(vault_router, tags=[ROUTE_TAG_VAULT])
    app.include_router(checklists_router, tags=[ROUTE_TAG_CHECKLISTS])
    app.include_router(sessions_router, tags=[ROUTE_TAG_SESSIONS])
    app.include_router(approvals_router, tags=[ROUTE_TAG_APPROVALS])
    app.include_router(messages_router, tags=[ROUTE_TAG_MESSAGES])
    app.include_router(paired_chats_router, tags=[ROUTE_TAG_PAIRED_CHATS])
    app.include_router(routing_router, tags=[ROUTE_TAG_ROUTING])
    app.include_router(quota_router, tags=[ROUTE_TAG_QUOTA])
    app.include_router(usage_router, tags=[ROUTE_TAG_USAGE])
    # Item 3.2 — user preferences singleton.
    app.include_router(preferences_router, tags=[ROUTE_TAG_PREFERENCES])
    # Item 2.3 — slash-command scanner.
    app.include_router(commands_router, tags=[ROUTE_TAG_COMMANDS])
    # Item 2.4 — history search.
    app.include_router(history_router, tags=[ROUTE_TAG_HISTORY])
    # Item 2.6 — sessions-broadcast WS channel.
    app.include_router(ws_sessions_router, tags=[ROUTE_TAG_WS_SESSIONS])
    # Item 1.10 — misc-API surfaces.
    app.include_router(uploads_router, tags=[ROUTE_TAG_UPLOADS])
    app.include_router(fs_router, tags=[ROUTE_TAG_FS])
    app.include_router(shell_router, tags=[ROUTE_TAG_SHELL])
    app.include_router(diag_router, tags=[ROUTE_TAG_DIAG])
    app.include_router(health_router, tags=[ROUTE_TAG_HEALTH])
    app.include_router(metrics_router, tags=[ROUTE_TAG_METRICS])
    app.include_router(import_db_router, tags=[ROUTE_TAG_IMPORT])
    # E2E harness extension seam (item 3.1) — extra routers mount
    # *between* the production routers and the static bundle so debug
    # endpoints take precedence over the SPA fallback. Production
    # callers always pass ``None``.
    if extra_routers is not None:
        for extra in extra_routers:
            app.include_router(extra)
    # SvelteKit static bundle — mounted last so every API/WS route
    # registered above takes precedence (item 2.1; arch §1.1.5
    # ``web/static.py``). Idempotent on a missing ``dist/`` so
    # backend-only test runs do not need a built frontend.
    mount_static_bundle(app)

    # Shutdown drain — when the factory is the InProcessRunnerRegistry
    # (the production path), cancel every per-session supervisor task
    # so the SDK CLI subprocesses tear down cleanly. Wired as a
    # FastAPI shutdown event so uvicorn's graceful-shutdown path
    # awaits the drain before exiting. Per ``~/.claude/plans/wiring-
    # agent-loop.md`` Slice A1.3.
    if isinstance(factory, InProcessRunnerRegistry):

        @app.on_event("startup")
        async def _start_reaper() -> None:
            factory.start_reaper()

        @app.on_event("shutdown")
        async def _drain_supervisors() -> None:
            await factory.aclose()

    return app


__all__ = ["create_app"]
