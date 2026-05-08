"""Consolidated session module — lifecycle, model config, permissions.

Per arch §1.1.4 + §2.1 + §2.3 #1, this module collapses v0.17.x's
seven-mixin ``agent/session/`` package into one canonical
:class:`AgentSession` class with a single constructor shape
(:class:`SessionConfig`). Three concern surfaces:

* **Lifecycle** — :class:`SessionState` + :data:`LIFECYCLE_TRANSITIONS`
  are the explicit state machine ``docs/behavior/chat.md`` §"The agent
  loop start/stop semantics" + §"Error states" describes; transitions
  acquire :attr:`AgentSession._lock` so concurrent callers serialise.
* **Model config** — :class:`SessionConfig` is the frozen-dataclass
  shape per arch §4.8; ``__post_init__`` validates non-empty IDs,
  positive ``tool_output_cap_chars``, non-negative ``max_budget_usd``,
  and the SDK literal alphabets for ``permission_mode`` /
  ``setting_sources``. Embeds :class:`bearings.agent.routing.RoutingDecision`
  for spec §App A executor + advisor + effort.
* **Permission profiles** — :class:`PermissionProfile` resolves to the
  SDK ``permission_mode`` + ``allowed_tools`` + ``disallowed_tools``
  triple via constants-module tables; an explicit
  :attr:`SessionConfig.permission_mode` overrides the profile's
  resolved mode (more-specific wins).

The streaming surface (``stream(prompt) -> AsyncIterator[AgentEvent]``)
is item 1.2's territory; item 1.1 lays the type surface only. SDK
forwards (:meth:`set_model`, :meth:`set_permission_mode`,
:meth:`interrupt`) per arch §5 #8 / #9 forward to a client attached
via :meth:`attach_sdk_client` once the runner connects it.

References: arch §1.1.4 / §2.1 / §2.3 #1 / §3 / §4.8 / §5 #8-#9;
``docs/behavior/chat.md``; ``docs/model-routing-v1-spec.md`` §App A.
"""

from __future__ import annotations

import asyncio
import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast, get_args

import aiosqlite

from bearings.agent.routing import RoutingDecision
from bearings.config.constants import (
    DEFAULT_TOOL_OUTPUT_CAP_CHARS,
    KNOWN_SDK_PERMISSION_MODES,
    KNOWN_SDK_SETTING_SOURCES,
    PERMISSION_PROFILE_ALLOWED_TOOLS,
    PERMISSION_PROFILE_DISALLOWED_TOOLS,
    PERMISSION_PROFILE_TO_SDK_MODE,
)

if TYPE_CHECKING:
    # SDK bidirectional streaming client (context7 query
    # ``/anthropics/claude-agent-sdk-python``, 2026-04-28). Item 1.2
    # connects one and attaches via :meth:`attach_sdk_client`; item
    # 1.1 only needs the type for forwarding-method signatures.
    from claude_agent_sdk import ClaudeSDKClient


# Local SDK ``permission_mode`` Literal so the
# :meth:`AgentSession.set_permission_mode` cast at the boundary is
# typed against a known alphabet rather than ``str``. Mirrors
# :data:`KNOWN_SDK_PERMISSION_MODES`; the assertion below keeps them
# in lockstep so a future SDK alphabet change cannot silently drift.
_SdkPermissionMode = Literal[
    "default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"
]
assert set(get_args(_SdkPermissionMode)) == KNOWN_SDK_PERMISSION_MODES


# ---------------------------------------------------------------------------
# Lifecycle state machine
# ---------------------------------------------------------------------------


class SessionState(enum.StrEnum):
    """Five states a session can occupy.

    * ``INITIALIZING`` — config built, SDK client not yet attached.
    * ``RUNNING`` — SDK client attached and live (mid-turn or idle).
    * ``PAUSED`` — alive but streaming gated; ``resume()`` returns
      to ``RUNNING``. Used by the spec §7 manual-switch flow.
    * ``ERROR`` — recoverable error captured; ``recover()`` or
      ``close()`` are valid.
    * ``CLOSED`` — terminal. Per ``docs/behavior/chat.md`` §"Error
      states", composer is replaced with "Reopen session" and the
      prompt-endpoint returns 409.
    """

    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    CLOSED = "closed"


# Allowed transitions; lookups are O(1) via frozenset. Any transition
# whose target is not in the source state's set raises
# :class:`SessionStateError` per the autonomy contract's
# "transitions valid only from named source states" directive.
LIFECYCLE_TRANSITIONS: Final[Mapping[SessionState, frozenset[SessionState]]] = {
    SessionState.INITIALIZING: frozenset(
        {SessionState.RUNNING, SessionState.ERROR, SessionState.CLOSED}
    ),
    SessionState.RUNNING: frozenset({SessionState.PAUSED, SessionState.ERROR, SessionState.CLOSED}),
    SessionState.PAUSED: frozenset({SessionState.RUNNING, SessionState.ERROR, SessionState.CLOSED}),
    SessionState.ERROR: frozenset({SessionState.RUNNING, SessionState.CLOSED}),
    SessionState.CLOSED: frozenset(),
}


class SessionStateError(RuntimeError):
    """Invalid lifecycle transition or SDK forward.

    Distinct from :class:`ValueError` (which the dataclass post-init
    raises for config-shape problems) so handlers can pattern-match.
    """


# ---------------------------------------------------------------------------
# Permission profiles
# ---------------------------------------------------------------------------


class PermissionProfile(enum.StrEnum):
    """Bearings-internal permission preset.

    Resolution to the SDK triple lives in
    :mod:`bearings.config.constants` per the item-0.5 "no inline
    literals" gate. Three postures: read-only inspection
    (``RESTRICTED``), normal day-to-day editing (``STANDARD``,
    default), and fully autonomous (``EXPANDED``).
    """

    RESTRICTED = "restricted"
    STANDARD = "standard"
    EXPANDED = "expanded"


# ---------------------------------------------------------------------------
# SessionConfig validators
# ---------------------------------------------------------------------------


def _validate_config_basics(
    session_id: str,
    working_dir: str,
    tool_output_cap_chars: int,
    max_budget_usd: float | None,
) -> None:
    """Raise if required strings are empty or numeric bounds are violated."""
    if not session_id:
        raise ValueError("SessionConfig.session_id must be non-empty")
    if not working_dir:
        raise ValueError("SessionConfig.working_dir must be non-empty")
    if tool_output_cap_chars <= 0:
        raise ValueError(
            f"SessionConfig.tool_output_cap_chars must be > 0 (got {tool_output_cap_chars})"
        )
    if max_budget_usd is not None and max_budget_usd < 0:
        raise ValueError(f"SessionConfig.max_budget_usd must be >= 0 if set (got {max_budget_usd})")


def _validate_config_perms(
    permission_mode: str | None,
    setting_sources: tuple[str, ...] | None,
) -> None:
    """Raise if permission_mode or setting_sources fall outside their alphabets."""
    if permission_mode is not None and permission_mode not in KNOWN_SDK_PERMISSION_MODES:
        raise ValueError(
            f"SessionConfig.permission_mode {permission_mode!r} is not "
            f"in {sorted(KNOWN_SDK_PERMISSION_MODES)}"
        )
    if setting_sources is not None:
        for src in setting_sources:
            if src not in KNOWN_SDK_SETTING_SOURCES:
                raise ValueError(
                    f"SessionConfig.setting_sources entry {src!r} is not "
                    f"in {sorted(KNOWN_SDK_SETTING_SOURCES)}"
                )


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionConfig:
    """Arch §4.8 — frozen single-arg constructor for :class:`AgentSession`.

    ``__post_init__`` catches the four shape mistakes a downstream
    constructor is most likely to make: empty ``session_id`` /
    ``working_dir``, non-positive ``tool_output_cap_chars``, negative
    ``max_budget_usd``, and ``permission_mode`` / ``setting_sources``
    outside the SDK's literal alphabets. The :attr:`decision` field
    carries executor + advisor + effort per spec §App A.
    """

    session_id: str
    working_dir: str
    decision: RoutingDecision
    db: aiosqlite.Connection | None
    sdk_session_id: str | None = None
    permission_profile: PermissionProfile = PermissionProfile.STANDARD
    permission_mode: str | None = None
    # ``thinking`` carries the SDK's ThinkingConfig union as a
    # (kind, budget_tokens) tuple so the dataclass stays frozen; SDK
    # construction lives in ``agent/options.py`` (item 1.2). ``None``
    # means "use the SDK default".
    thinking: tuple[str, int | None] | None = None
    setting_sources: tuple[str, ...] | None = None
    inherit_mcp_servers: bool = True
    inherit_hooks: bool = True
    tool_output_cap_chars: int = DEFAULT_TOOL_OUTPUT_CAP_CHARS
    enable_bearings_mcp: bool = True
    enable_precompact_steering: bool = True
    enable_researcher_subagent: bool = False
    max_budget_usd: float | None = None

    def __post_init__(self) -> None:
        _validate_config_basics(
            self.session_id,
            self.working_dir,
            self.tool_output_cap_chars,
            self.max_budget_usd,
        )
        _validate_config_perms(self.permission_mode, self.setting_sources)


# ---------------------------------------------------------------------------
# Canonical session class
# ---------------------------------------------------------------------------


class AgentSession:
    """Arch §2.1 — canonical per-WS-session SDK wrapper.

    Surface laid by item 1.1: lifecycle methods + :attr:`state`;
    permission-profile resolution; SDK forwards (:meth:`set_model`,
    :meth:`set_permission_mode`, :meth:`interrupt`) per arch §5 #8/#9;
    client attach/detach. Item 1.2 connects a
    :class:`claude_agent_sdk.ClaudeSDKClient`, attaches via
    :meth:`attach_sdk_client`, and adds ``stream(prompt)``.

    All lifecycle transitions hold :attr:`_lock` (asyncio.Lock); SDK
    forwards do not (the SDK's bidirectional client is itself
    concurrency-safe per its docs).
    """

    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._state: SessionState = SessionState.INITIALIZING
        self._lock = asyncio.Lock()
        self._client: ClaudeSDKClient | None = None
        self._error_message: str | None = None

    # -- properties --------------------------------------------------

    @property
    def config(self) -> SessionConfig:
        """The frozen-dataclass config the session was built with."""
        return self._config

    @property
    def state(self) -> SessionState:
        """Current lifecycle state. Mutate via lifecycle methods only."""
        return self._state

    @property
    def error_message(self) -> str | None:
        """Last :meth:`mark_error` message; ``None`` outside ``ERROR``."""
        return self._error_message

    @property
    def has_sdk_client(self) -> bool:
        """``True`` between :meth:`attach_sdk_client` and detach."""
        return self._client is not None

    # -- client attach / detach -------------------------------------

    def attach_sdk_client(self, client: ClaudeSDKClient) -> None:
        """Register a live SDK client; reject double-attach."""
        if self._client is not None:
            raise SessionStateError(
                "AgentSession already has an attached SDK client; call detach_sdk_client() first"
            )
        self._client = client

    def detach_sdk_client(self) -> ClaudeSDKClient | None:
        """Release the attached client; idempotent (returns ``None`` if none)."""
        client = self._client
        self._client = None
        return client

    # -- lifecycle methods ------------------------------------------

    async def start(self) -> None:
        """Transition ``INITIALIZING -> RUNNING``."""
        async with self._lock:
            if self._state is not SessionState.INITIALIZING:
                raise SessionStateError(
                    f"start() requires {SessionState.INITIALIZING.value!r}; "
                    f"current state is {self._state.value!r}"
                )
            self._guard_transition(SessionState.RUNNING)
            self._state = SessionState.RUNNING

    async def pause(self) -> None:
        """Transition ``RUNNING -> PAUSED`` (spec §7 manual-switch hold)."""
        async with self._lock:
            self._guard_transition(SessionState.PAUSED)
            self._state = SessionState.PAUSED

    async def resume(self) -> None:
        """Transition ``PAUSED -> RUNNING`` or ``ERROR -> RUNNING``."""
        async with self._lock:
            if self._state not in {SessionState.PAUSED, SessionState.ERROR}:
                raise SessionStateError(
                    f"resume() requires {SessionState.PAUSED.value!r} or "
                    f"{SessionState.ERROR.value!r}; current state is "
                    f"{self._state.value!r}"
                )
            self._guard_transition(SessionState.RUNNING)
            self._error_message = None
            self._state = SessionState.RUNNING

    async def close(self) -> None:
        """Transition any non-terminal state to terminal ``CLOSED``.

        The SDK client is *not* detached here — the runner owns the
        client lifecycle and detaches after its ``async with`` exits.
        """
        async with self._lock:
            self._guard_transition(SessionState.CLOSED)
            self._state = SessionState.CLOSED

    async def mark_error(self, message: str) -> None:
        """Transition any non-terminal state to ``ERROR``; sets
        :attr:`error_message` for the WS ``runner_status`` frame."""
        async with self._lock:
            self._guard_transition(SessionState.ERROR)
            self._error_message = message
            self._state = SessionState.ERROR

    async def recover(self) -> None:
        """Transition ``ERROR -> RUNNING`` after the user retries."""
        await self.resume()

    def _guard_transition(self, target: SessionState) -> None:
        allowed = LIFECYCLE_TRANSITIONS[self._state]
        if target not in allowed:
            raise SessionStateError(
                f"invalid transition {self._state.value!r} -> {target.value!r}; "
                f"allowed targets from {self._state.value!r} are "
                f"{sorted(s.value for s in allowed)}"
            )

    # -- permission-profile resolution -------------------------------

    def effective_permission_mode(self) -> str:
        """Resolved SDK ``permission_mode`` (explicit override beats profile)."""
        if self._config.permission_mode is not None:
            return self._config.permission_mode
        return PERMISSION_PROFILE_TO_SDK_MODE[self._config.permission_profile.value]

    def effective_allowed_tools(self) -> tuple[str, ...]:
        """Resolved ``allowed_tools`` allowance per profile."""
        return PERMISSION_PROFILE_ALLOWED_TOOLS[self._config.permission_profile.value]

    def effective_disallowed_tools(self) -> tuple[str, ...]:
        """Resolved ``disallowed_tools`` deny list per profile."""
        return PERMISSION_PROFILE_DISALLOWED_TOOLS[self._config.permission_profile.value]

    # -- SDK forwards ------------------------------------------------

    async def set_model(self, model: str) -> None:
        """Forward to :meth:`ClaudeSDKClient.set_model` (arch §5 #8)."""
        client = self._require_client_in_running("set_model")
        await client.set_model(model)

    async def set_permission_mode(self, mode: str) -> None:
        """Validate ``mode`` then forward to the SDK (arch §5 #9).

        The cast bridges the validated runtime ``str`` to the SDK's
        Literal-typed parameter (mypy can't narrow through the
        ``frozenset`` membership test above).
        """
        if mode not in KNOWN_SDK_PERMISSION_MODES:
            raise ValueError(
                f"unknown SDK permission_mode {mode!r}; expected one of "
                f"{sorted(KNOWN_SDK_PERMISSION_MODES)}"
            )
        client = self._require_client_in_running("set_permission_mode")
        await client.set_permission_mode(cast(_SdkPermissionMode, mode))

    async def interrupt(self) -> None:
        """Forward to :meth:`ClaudeSDKClient.interrupt`; valid in
        ``RUNNING`` or ``PAUSED``."""
        if self._client is None:
            raise SessionStateError("cannot interrupt: no SDK client attached")
        if self._state not in {SessionState.RUNNING, SessionState.PAUSED}:
            raise SessionStateError(
                f"cannot interrupt from state {self._state.value!r}; "
                "valid only in RUNNING or PAUSED"
            )
        await self._client.interrupt()

    def _require_client_in_running(self, method_name: str) -> ClaudeSDKClient:
        if self._state != SessionState.RUNNING:
            raise SessionStateError(
                f"cannot call {method_name} from state {self._state.value!r}; valid only in RUNNING"
            )
        if self._client is None:
            raise SessionStateError(f"cannot call {method_name}: no SDK client attached")
        return self._client


__all__ = [
    "LIFECYCLE_TRANSITIONS",
    "AgentSession",
    "PermissionProfile",
    "SessionConfig",
    "SessionState",
    "SessionStateError",
]
