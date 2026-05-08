"""Multi-overlay :class:`SessionConfig` assembler.

Per ``docs/architecture-v1.md`` §1.1.4 + §4.8 every code path that
materialises a fresh :class:`bearings.agent.session.SessionConfig`
flows through one canonical overlay chain. Item 1.7 lays this module
because three concrete consumers all need the same composition:

* paired-chat spawn (``agent/paired_chats.py:spawn_paired_chat``);
* the prompt-endpoint's lazy session creation (out of v0.18.0 scope —
  the endpoint per ``docs/behavior/prompt-endpoint.md`` only ever
  resumes existing sessions, but the assembler is the boundary the
  future create-on-POST surface will call);
* the auto-driver's ``leg_session_factory`` callback
  (``agent/auto_driver_runtime.py``) — each leg is a fresh chat
  session inheriting the parent checklist's tags + working dir.

Overlay precedence (most-specific wins; tested in
``tests/test_session_assembly.py``):

1. **Global default** — :data:`bearings.config.constants` workhorse
   pair (``DEFAULT_TEMPLATE_MODEL`` = ``sonnet``,
   ``DEFAULT_TEMPLATE_ADVISOR_MODEL`` = ``opus``,
   ``DEFAULT_TEMPLATE_ADVISOR_MAX_USES`` = 5,
   ``DEFAULT_TEMPLATE_EFFORT_LEVEL`` = ``auto``,
   ``DEFAULT_TEMPLATE_PERMISSION_PROFILE`` = ``standard``). These are
   the spec §3 priority-1000 always-rule defaults.
2. **Template overlay** — when ``template_id`` is supplied, the
   template's executor / advisor / effort / permission_profile fields
   land per :func:`bearings.agent.templates.build_session_config_from_template`.
3. **Tag-default overlay** — when ``tags`` is non-empty, the tag-side
   ``default_model`` / ``working_dir`` resolve via
   :func:`bearings.agent.tags.resolve_default_model` /
   :func:`bearings.agent.tags.resolve_working_dir`. Tag defaults beat
   template defaults because the user picked the tag *for this
   session* (the template was a starting shape; the tag is the
   classification).
4. **Explicit user input** — every keyword argument the API request
   set (``model``, ``advisor_model``, ``working_dir``, etc.) wins over
   every overlay below it. Mirrors the new-session-dialog observable
   per ``docs/behavior/chat.md`` §"When the user creates a chat":
   what the user typed in the form is what the session gets.

Routing-decision plumbing (item 1.8 swap-in):

The assembler now invokes the real
:func:`bearings.agent.routing.evaluate` when ``first_message`` is
supplied AND no explicit routing-field override is. In that path the
pure evaluator walks tag rules → system rules → absolute fallback
(spec §3) and :func:`bearings.agent.quota.apply_quota_guard` folds
quota-aware downgrades (spec §4) on top. ``RoutingDecision.source``
takes its real spec values (``tag_rule`` / ``system_rule`` /
``default`` / ``quota_downgrade``) instead of the item-1.7
placeholder ``manual`` / ``default`` pair.

When ``first_message`` is absent (paired-chat spawn, auto-driver leg
session, any caller that materialises a session before the first
user prompt is in hand) the assembler still emits the placeholder
``manual`` / ``default`` shape — these flows have no message to feed
the evaluator and the row needs *some* routing decision at create
time. Item 1.9's per-message persistence path then carries the real
evaluation result on the first user message of those flows.
"""

from __future__ import annotations

import aiosqlite

from bearings.agent.quota import apply_quota_guard, load_latest
from bearings.agent.routing import RoutingDecision, evaluate
from bearings.agent.session import PermissionProfile, SessionConfig
from bearings.agent.tags import resolve_default_model, resolve_working_dir
from bearings.config.constants import (
    DEFAULT_TEMPLATE_ADVISOR_MAX_USES,
    DEFAULT_TEMPLATE_ADVISOR_MODEL,
    DEFAULT_TEMPLATE_EFFORT_LEVEL,
    DEFAULT_TEMPLATE_MODEL,
    DEFAULT_TEMPLATE_PERMISSION_PROFILE,
)
from bearings.db import routing as routing_db
from bearings.db import tags as tags_db
from bearings.db import templates as templates_db
from bearings.db.tags import Tag
from bearings.db.templates import Template


class SessionAssemblyError(ValueError):
    """The overlay chain could not assemble a complete :class:`SessionConfig`.

    Distinct from :class:`ValueError` so the API layer (and the
    paired-chat / auto-driver call sites) can pattern-match a missing
    working directory (the one mandatory field that has no default
    anywhere in the chain) versus a SessionConfig field-shape problem.
    """


class _TemplateFields:
    """Flat snapshot of a template's routing fields (or all-None when absent).

    Replaces per-field ``None if template is None else template.X``
    guards in :func:`build_session_config` so each resolve call uses a
    simple attribute access instead of an inline conditional.
    """

    __slots__ = (
        "advisor_max_uses",
        "advisor_model",
        "effort_level",
        "model",
        "name",
        "permission_profile",
        "working_dir_default",
    )

    def __init__(self, template: Template | None) -> None:
        if template is None:
            self.model: str | None = None
            self.advisor_model: str | None = None
            self.advisor_max_uses: int | None = None
            self.effort_level: str | None = None
            self.permission_profile: str | None = None
            self.working_dir_default: str | None = None
            self.name: str | None = None
        else:
            self.model = template.model
            self.advisor_model = template.advisor_model
            self.advisor_max_uses = template.advisor_max_uses
            self.effort_level = template.effort_level
            self.permission_profile = template.permission_profile
            self.working_dir_default = template.working_dir_default
            self.name = template.name


def _compute_routing_source(
    working_dir: str | None,
    model: str | None,
    advisor_model: str | None,
    advisor_max_uses: int | None,
    effort_level: str | None,
    permission_profile: str | None,
    template: Template | None,
    tags: list[Tag],
) -> str:
    """Return ``'manual'`` when any user-side signal is present; ``'default'`` otherwise."""
    user_supplied = any(
        v is not None
        for v in (
            working_dir,
            model,
            advisor_model,
            advisor_max_uses,
            effort_level,
            permission_profile,
        )
    )
    if user_supplied or template is not None or any(t.default_model is not None for t in tags):
        return "manual"
    return "default"


def _no_routing_override(
    model: str | None,
    advisor_model: str | None,
    advisor_max_uses: int | None,
    effort_level: str | None,
    template: Template | None,
) -> bool:
    """Return True when no explicit routing override and no template was supplied."""
    return (
        model is None
        and advisor_model is None
        and advisor_max_uses is None
        and effort_level is None
        and template is None
    )


async def build_session_config(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    tag_ids: list[int] | None = None,
    template_id: int | None = None,
    working_dir: str | None = None,
    model: str | None = None,
    advisor_model: str | None = None,
    advisor_max_uses: int | None = None,
    effort_level: str | None = None,
    permission_profile: str | None = None,
    first_message: str | None = None,
) -> SessionConfig:
    """Compose a :class:`SessionConfig` from layered defaults.

    Args:
        connection: Open aiosqlite connection (reads tags + templates).
        session_id: The new session's id (caller-supplied;
            :class:`SessionConfig` rejects empty).
        tag_ids: Optional list of tag ids; their
            :attr:`Tag.default_model` / :attr:`Tag.working_dir` flow
            through the precedence chain via
            :func:`bearings.agent.tags.resolve_default_model` /
            :func:`bearings.agent.tags.resolve_working_dir`.
        template_id: Optional template row id; its routing fields land
            below tag overlay but above the global default.
        working_dir: Explicit user pick — wins over every overlay.
        model: Explicit executor pick.
        advisor_model: Explicit advisor pick. Pass ``""`` (empty
            string) to *positively* disable the advisor; ``None``
            means "fall through to overlays".
        advisor_max_uses: Explicit advisor max-uses pick.
        effort_level: Explicit effort label.
        permission_profile: Explicit permission profile name.
        first_message: Optional first user message — when supplied,
            :func:`bearings.agent.routing.evaluate` walks the
            tag-rule + system-rule chain (spec §3) and
            :func:`bearings.agent.quota.apply_quota_guard` folds
            quota-aware downgrades. Passing ``None`` keeps the
            placeholder ``manual``/``default`` behaviour for callers
            that materialise a session before the first prompt is in
            hand (paired-chat spawn, auto-driver leg session).

    Returns:
        A frozen :class:`SessionConfig`. When ``first_message`` is
        provided and no routing-field override is supplied, the
        decision's ``source`` is the spec §App A real value
        (``tag_rule`` / ``system_rule`` / ``default`` /
        ``quota_downgrade``); otherwise ``"manual"`` if any explicit
        routing field was supplied or the template contributed,
        ``"default"`` for the pure global-default fallback.

    Raises:
        SessionAssemblyError: Working directory could not be resolved
            from any overlay.
        TemplateNotFoundError: ``template_id`` does not match a row.
        ValueError: A composed field is invalid against
            :class:`SessionConfig.__post_init__` (e.g. unknown effort
            label, malformed model id).
    """
    tags = await _load_tags(connection, tag_ids)
    template = None
    if template_id is not None:
        template = await templates_db.get(connection, template_id)
        if template is None:
            from bearings.agent.templates import TemplateNotFoundError

            raise TemplateNotFoundError(f"no template with id {template_id}")

    tf = _TemplateFields(template)
    source = _compute_routing_source(
        working_dir,
        model,
        advisor_model,
        advisor_max_uses,
        effort_level,
        permission_profile,
        template,
        tags,
    )

    # Resolve each routing field — explicit > template > tags > global.
    resolved_model = _resolve_executor_model(explicit=model, template_value=tf.model, tags=tags)
    resolved_advisor = _resolve_advisor(explicit=advisor_model, template_value=tf.advisor_model)
    resolved_advisor_max = _resolve_int(
        explicit=advisor_max_uses,
        template_value=tf.advisor_max_uses,
        global_value=DEFAULT_TEMPLATE_ADVISOR_MAX_USES,
    )
    resolved_effort = _resolve_str(
        explicit=effort_level,
        template_value=tf.effort_level,
        global_value=DEFAULT_TEMPLATE_EFFORT_LEVEL,
    )
    resolved_profile_name = _resolve_str(
        explicit=permission_profile,
        template_value=tf.permission_profile,
        global_value=DEFAULT_TEMPLATE_PERMISSION_PROFILE,
    )
    resolved_working_dir = _resolve_working_dir(
        explicit=working_dir,
        template_value=tf.working_dir_default,
        tags=tags,
    )
    if not resolved_working_dir:
        raise SessionAssemblyError(
            "working_dir could not be resolved — supply explicitly, set on a tag, "
            "or pick a template with working_dir_default"
        )

    # Item 1.8 swap-in: when a first user message is supplied AND
    # no explicit routing-field override is, run the real evaluator.
    # Otherwise fall back to the manual/default placeholder shape so
    # paired-chat spawns + auto-driver leg sessions (which have no
    # message at create time) still produce a valid SessionConfig.
    decision: RoutingDecision
    if first_message is not None and _no_routing_override(
        model, advisor_model, advisor_max_uses, effort_level, template
    ):
        decision = await _evaluate_with_guard(connection, tags=tags, first_message=first_message)
    else:
        decision = RoutingDecision(
            executor_model=resolved_model,
            advisor_model=resolved_advisor,
            advisor_max_uses=resolved_advisor_max,
            effort_level=resolved_effort,
            source=source,
            reason=_build_reason(source=source, template_name=tf.name, tag_count=len(tags)),
            matched_rule_id=None,
        )

    profile = PermissionProfile(resolved_profile_name)
    return SessionConfig(
        session_id=session_id,
        working_dir=resolved_working_dir,
        decision=decision,
        db=connection,
        permission_profile=profile,
    )


async def _evaluate_with_guard(
    connection: aiosqlite.Connection,
    *,
    tags: list[Tag],
    first_message: str,
) -> RoutingDecision:
    """Run :func:`evaluate` + :func:`apply_quota_guard` against the live DB.

    Loads enabled tag rules + enabled system rules + the latest
    quota snapshot, then composes the two pure functions per spec
    §3 (rule walk) and §4 (quota guard). Item 1.8 swap-in target
    cited by the item-1.7 placeholder docstring.
    """
    tag_ids = [tag.id for tag in tags]
    tags_with_rules = await routing_db.list_for_tags(
        connection,
        tag_ids,
        enabled_only=True,
    )
    system_rules = await routing_db.list_system_rules(
        connection,
        enabled_only=True,
    )
    snapshot = await load_latest(connection)
    raw_decision = evaluate(
        first_message,
        tags_with_rules,
        system_rules,
        snapshot,
    )
    return apply_quota_guard(raw_decision, snapshot)


async def _load_tags(
    connection: aiosqlite.Connection,
    tag_ids: list[int] | None,
) -> list[Tag]:
    """Resolve ``tag_ids`` to :class:`Tag` rows, dropping any that vanished.

    A tag the API caller named that no longer exists is silently
    dropped (no exception). The decided-and-documented rationale: a
    user who attaches a tag and then deletes it before submit should
    see the post-deletion state — the assembler is downstream of the
    tag CRUD path and treats the input list as a hint, not a contract.
    """
    if not tag_ids:
        return []
    resolved: list[Tag] = []
    for tag_id in tag_ids:
        tag = await tags_db.get(connection, tag_id)
        if tag is not None:
            resolved.append(tag)
    return resolved


def _resolve_executor_model(
    *,
    explicit: str | None,
    template_value: str | None,
    tags: list[Tag],
) -> str:
    """Walk the precedence chain for executor model.

    Order: explicit > tags > template > global default. (Tags beat
    template because the per-session classification is more specific
    than the template starting shape — see module docstring.)
    """
    if explicit is not None:
        return explicit
    tag_resolved = resolve_default_model(tags)
    if tag_resolved is not None:
        return tag_resolved
    if template_value is not None:
        return template_value
    return DEFAULT_TEMPLATE_MODEL


def _resolve_advisor(
    *,
    explicit: str | None,
    template_value: str | None,
) -> str | None:
    """Walk the precedence chain for advisor model.

    The empty-string convention: ``explicit=""`` means the user
    *positively* disabled the advisor in the new-session dialog
    (per ``docs/behavior/chat.md`` advisor toggle), and overrides any
    template default. ``explicit=None`` means "fall through to
    overlays".
    """
    if explicit is not None:
        return explicit if explicit else None
    if template_value is not None:
        return template_value
    return DEFAULT_TEMPLATE_ADVISOR_MODEL


def _resolve_int(
    *,
    explicit: int | None,
    template_value: int | None,
    global_value: int,
) -> int:
    """Walk the precedence chain for an int field with a global fallback."""
    if explicit is not None:
        return explicit
    if template_value is not None:
        return template_value
    return global_value


def _resolve_str(
    *,
    explicit: str | None,
    template_value: str | None,
    global_value: str,
) -> str:
    """Walk the precedence chain for a string field with a global fallback."""
    if explicit is not None:
        return explicit
    if template_value is not None:
        return template_value
    return global_value


def _resolve_working_dir(
    *,
    explicit: str | None,
    template_value: str | None,
    tags: list[Tag],
) -> str | None:
    """Walk the precedence chain for working_dir.

    Returns ``None`` if no overlay supplies a value — the caller
    surfaces :class:`SessionAssemblyError` since working_dir has no
    global default. Tags beat template per the module-level
    precedence rationale.
    """
    if explicit is not None:
        return explicit
    tag_resolved = resolve_working_dir(tags)
    if tag_resolved is not None:
        return tag_resolved
    return template_value


def _build_reason(
    *,
    source: str,
    template_name: str | None,
    tag_count: int,
) -> str:
    """Produce the ``RoutingDecision.reason`` string for the placeholder.

    The exact wording surfaces in the routing-badge tooltip (spec
    §App A) once item 1.8's evaluator runs — until then this is the
    placeholder text. Pinned for stable test assertions.
    """
    if source == "default":
        return "global default (workhorse Sonnet + Opus advisor)"
    if template_name is not None:
        return f"composed: template {template_name!r}, {tag_count} tag(s)"
    if tag_count > 0:
        return f"composed: {tag_count} tag(s) + explicit overrides"
    return "composed: explicit overrides"


__all__ = ["SessionAssemblyError", "build_session_config"]
