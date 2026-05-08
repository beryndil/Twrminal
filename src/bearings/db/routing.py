"""``tag_routing_rules`` + ``system_routing_rules`` table queries.

Per ``docs/architecture-v1.md`` §1.1.3 + §4.2 this concern module owns
every query that touches the two routing-rule tables (per
``docs/model-routing-v1-spec.md`` §3 schema). The pure
:func:`bearings.agent.routing.evaluate` function consumes the row
dataclasses defined here; the API surface in
:mod:`bearings.web.routes.routing` performs CRUD via these helpers.

Public surface:

* :class:`RoutingRule` — frozen row mirror for ``tag_routing_rules``.
* :class:`SystemRoutingRule` — frozen row mirror for
  ``system_routing_rules``; carries the additional ``seeded`` flag.
* CRUD functions: :func:`create_tag_rule`, :func:`get_tag_rule`,
  :func:`list_tag_rules`, :func:`list_for_tag`,
  :func:`list_for_tags`, :func:`update_tag_rule`,
  :func:`delete_tag_rule`, :func:`reorder_tag_rules`,
  :func:`create_system_rule`, :func:`get_system_rule`,
  :func:`list_system_rules`, :func:`update_system_rule`,
  :func:`delete_system_rule`.

Validation lives in :meth:`RoutingRule.__post_init__` /
:meth:`SystemRoutingRule.__post_init__` — same alphabet
(:data:`bearings.config.constants.KNOWN_MATCH_TYPES`,
:data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS`,
:data:`bearings.config.constants.KNOWN_EFFORT_LEVELS`) the schema
``CHECK`` constraints enforce, but raised in Python for friendlier
422 messaging at the API boundary.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    KNOWN_EFFORT_LEVELS,
    KNOWN_EXECUTOR_MODELS,
    KNOWN_MATCH_TYPES,
)


def _now_unix() -> int:
    """Return the current unix-seconds timestamp.

    The ``tag_routing_rules`` / ``system_routing_rules`` tables declare
    ``created_at`` / ``updated_at`` as ``INTEGER NOT NULL`` (per spec §3
    schema verbatim), distinct from the ISO-string convention the
    user-facing tables use. The integer form keeps the override-rate
    aggregator's 14-day window math (:mod:`bearings.agent.override_aggregator`)
    a single subtraction.
    """
    return int(time.time())


def _is_known_model(name: str) -> bool:
    """Return ``True`` if ``name`` is a known short name or full SDK ID."""
    return name in KNOWN_EXECUTOR_MODELS or name.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX)


@dataclass(frozen=True)
class RoutingRule:
    """Row mirror for ``tag_routing_rules`` — spec §3 schema verbatim.

    Field semantics follow ``schema.sql``:

    * ``id`` — INTEGER PRIMARY KEY AUTOINCREMENT.
    * ``tag_id`` — FK to ``tags.id``, ON DELETE CASCADE.
    * ``priority`` — lower number = checked earlier (spec §3 step 1).
    * ``enabled`` — disabled rules are skipped, not deleted.
    * ``match_type`` — one of
      :data:`bearings.config.constants.KNOWN_MATCH_TYPES`.
    * ``match_value`` — the per-match-type value (NULL valid only for
      ``always``).
    * ``executor_model`` / ``advisor_model`` — short name from
      :data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS` or full
      SDK ID prefixed with
      :data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX`.
    * ``advisor_max_uses`` — 0-N; ignored when ``advisor_model`` is
      ``None``.
    * ``effort_level`` — one of
      :data:`bearings.config.constants.KNOWN_EFFORT_LEVELS`.
    * ``reason`` — surfaced in the routing-badge tooltip when this rule
      fires.
    * ``created_at`` / ``updated_at`` — unix seconds.
    """

    id: int
    tag_id: int
    priority: int
    enabled: bool
    match_type: str
    match_value: str | None
    executor_model: str
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    reason: str
    created_at: int
    updated_at: int

    def __post_init__(self) -> None:
        _validate_rule_fields(
            match_type=self.match_type,
            match_value=self.match_value,
            executor_model=self.executor_model,
            advisor_model=self.advisor_model,
            advisor_max_uses=self.advisor_max_uses,
            effort_level=self.effort_level,
            reason=self.reason,
        )


@dataclass(frozen=True)
class SystemRoutingRule:
    """Row mirror for ``system_routing_rules`` — spec §3 schema verbatim.

    Same shape as :class:`RoutingRule` minus the ``tag_id`` column,
    plus a ``seeded`` flag distinguishing the seven shipped defaults
    (per spec §3 default table) from user-added rows.
    """

    id: int
    priority: int
    enabled: bool
    match_type: str
    match_value: str | None
    executor_model: str
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    reason: str
    seeded: bool
    created_at: int
    updated_at: int

    def __post_init__(self) -> None:
        _validate_rule_fields(
            match_type=self.match_type,
            match_value=self.match_value,
            executor_model=self.executor_model,
            advisor_model=self.advisor_model,
            advisor_max_uses=self.advisor_max_uses,
            effort_level=self.effort_level,
            reason=self.reason,
        )


def _validate_rule_match(match_type: str, match_value: str | None) -> None:
    """Raise if match_type is unknown or match_value is missing for non-always types."""
    if match_type not in KNOWN_MATCH_TYPES:
        raise ValueError(f"match_type {match_type!r} is not in {sorted(KNOWN_MATCH_TYPES)}")
    if match_type != "always" and (match_value is None or not match_value):
        raise ValueError(f"match_type {match_type!r} requires a non-empty match_value")


def _validate_rule_models(executor_model: str, advisor_model: str | None) -> None:
    """Raise if executor_model or advisor_model are not valid model identifiers."""
    if not executor_model or not _is_known_model(executor_model):
        raise ValueError(
            f"executor_model {executor_model!r} is neither a known short name "
            f"{sorted(KNOWN_EXECUTOR_MODELS)} nor a full SDK ID prefixed with "
            f"{EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
        )
    if advisor_model is not None and not _is_known_model(advisor_model):
        raise ValueError(
            f"advisor_model {advisor_model!r} is neither a known short name "
            f"nor prefixed with {EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
        )


def _validate_rule_fields(
    *,
    match_type: str,
    match_value: str | None,
    executor_model: str,
    advisor_model: str | None,
    advisor_max_uses: int,
    effort_level: str,
    reason: str,
) -> None:
    """Shared validation for both rule dataclasses.

    Centralised so :class:`RoutingRule` and :class:`SystemRoutingRule`
    cannot drift on the alphabet. Mirrors the schema CHECK constraints
    plus the spec's "match_value NULL valid only for ``always``" rule
    so the API layer surfaces a 422 with a precise diagnosis instead
    of an opaque integrity error.
    """
    _validate_rule_match(match_type, match_value)
    _validate_rule_models(executor_model, advisor_model)
    if advisor_max_uses < 0:
        raise ValueError(f"advisor_max_uses must be ≥ 0 (got {advisor_max_uses})")
    if effort_level not in KNOWN_EFFORT_LEVELS:
        raise ValueError(f"effort_level {effort_level!r} is not in {sorted(KNOWN_EFFORT_LEVELS)}")
    if not reason:
        raise ValueError("reason must be non-empty")


# ---------------------------------------------------------------------------
# Tag rule CRUD
# ---------------------------------------------------------------------------


_TAG_RULE_COLUMNS = (
    "SELECT id, tag_id, priority, enabled, match_type, match_value, "
    "executor_model, advisor_model, advisor_max_uses, effort_level, "
    "reason, created_at, updated_at FROM tag_routing_rules"
)


def _row_to_tag_rule(row: aiosqlite.Row | tuple[object, ...]) -> RoutingRule:
    return RoutingRule(
        id=int(str(row[0])),
        tag_id=int(str(row[1])),
        priority=int(str(row[2])),
        enabled=bool(row[3]),
        match_type=str(row[4]),
        match_value=None if row[5] is None else str(row[5]),
        executor_model=str(row[6]),
        advisor_model=None if row[7] is None else str(row[7]),
        advisor_max_uses=int(str(row[8])),
        effort_level=str(row[9]),
        reason=str(row[10]),
        created_at=int(str(row[11])),
        updated_at=int(str(row[12])),
    )


async def create_tag_rule(
    connection: aiosqlite.Connection,
    *,
    tag_id: int,
    priority: int = 100,
    enabled: bool = True,
    match_type: str,
    match_value: str | None,
    executor_model: str,
    advisor_model: str | None,
    advisor_max_uses: int = 5,
    effort_level: str = "auto",
    reason: str,
) -> RoutingRule:
    """Insert a new ``tag_routing_rules`` row and return it populated.

    Validation runs against a phantom :class:`RoutingRule` instance
    before INSERT so a bad shape never touches the DB. FK violation on
    ``tag_id`` surfaces as :class:`aiosqlite.IntegrityError` for the
    API layer to translate to 404.
    """
    timestamp = _now_unix()
    RoutingRule(
        id=0,
        tag_id=tag_id,
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        created_at=timestamp,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "INSERT INTO tag_routing_rules ("
        "tag_id, priority, enabled, match_type, match_value, "
        "executor_model, advisor_model, advisor_max_uses, effort_level, "
        "reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            tag_id,
            priority,
            1 if enabled else 0,
            match_type,
            match_value,
            executor_model,
            advisor_model,
            advisor_max_uses,
            effort_level,
            reason,
            timestamp,
            timestamp,
        ),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover — sqlite always returns rowid
        raise RuntimeError("create_tag_rule: aiosqlite returned a None lastrowid")
    return RoutingRule(
        id=int(new_id),
        tag_id=tag_id,
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def get_tag_rule(
    connection: aiosqlite.Connection,
    rule_id: int,
) -> RoutingRule | None:
    """Fetch a single tag rule by id; ``None`` if absent."""
    cursor = await connection.execute(_TAG_RULE_COLUMNS + " WHERE id = ?", (rule_id,))
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_tag_rule(row)


async def list_for_tag(
    connection: aiosqlite.Connection,
    tag_id: int,
    *,
    enabled_only: bool = False,
) -> list[RoutingRule]:
    """Tag rules for a single ``tag_id``, ordered by priority, then id.

    ``enabled_only=True`` filters disabled rules; the evaluator path
    pre-filters in Python (see
    :func:`bearings.agent.routing.evaluate`) so the API surface uses
    the default ``False`` to render the full set in the rule editor.
    """
    if enabled_only:
        sql = _TAG_RULE_COLUMNS + (
            " WHERE tag_id = ? AND enabled = 1 ORDER BY priority ASC, id ASC"
        )
    else:
        sql = _TAG_RULE_COLUMNS + " WHERE tag_id = ? ORDER BY priority ASC, id ASC"
    cursor = await connection.execute(sql, (tag_id,))
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_tag_rule(row) for row in rows]


async def list_for_tags(
    connection: aiosqlite.Connection,
    tag_ids: list[int],
    *,
    enabled_only: bool = False,
) -> list[tuple[int, list[RoutingRule]]]:
    """Tag rules for every tag in ``tag_ids`` — one entry per tag, in input order.

    Returns ``[(tag_id, rules), …]`` so
    :func:`bearings.agent.routing.evaluate` can preserve cross-tag
    priority ordering exactly as spec §3 step 1 specifies.
    """
    out: list[tuple[int, list[RoutingRule]]] = []
    for tag_id in tag_ids:
        rules = await list_for_tag(connection, tag_id, enabled_only=enabled_only)
        out.append((tag_id, rules))
    return out


async def list_tag_rules(
    connection: aiosqlite.Connection,
) -> list[RoutingRule]:
    """Every tag rule across every tag, ordered by tag then priority then id.

    Used by the global override-rate aggregator (item 1.8) to compute
    per-rule rates without N+1 queries.
    """
    cursor = await connection.execute(
        _TAG_RULE_COLUMNS + " ORDER BY tag_id ASC, priority ASC, id ASC",
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_tag_rule(row) for row in rows]


async def update_tag_rule(
    connection: aiosqlite.Connection,
    rule_id: int,
    *,
    priority: int,
    enabled: bool,
    match_type: str,
    match_value: str | None,
    executor_model: str,
    advisor_model: str | None,
    advisor_max_uses: int,
    effort_level: str,
    reason: str,
) -> RoutingRule | None:
    """Replace mutable fields on a tag rule; ``None`` if not found.

    The full mutable shape is required (PATCH semantics enforced at
    the API layer) so a partial body cannot accidentally clear a
    column. Validation runs via a phantom :class:`RoutingRule`
    pre-UPDATE.
    """
    existing = await get_tag_rule(connection, rule_id)
    if existing is None:
        return None
    timestamp = _now_unix()
    RoutingRule(
        id=rule_id,
        tag_id=existing.tag_id,
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        created_at=existing.created_at,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "UPDATE tag_routing_rules SET priority=?, enabled=?, match_type=?, "
        "match_value=?, executor_model=?, advisor_model=?, "
        "advisor_max_uses=?, effort_level=?, reason=?, updated_at=? WHERE id=?",
        (
            priority,
            1 if enabled else 0,
            match_type,
            match_value,
            executor_model,
            advisor_model,
            advisor_max_uses,
            effort_level,
            reason,
            timestamp,
            rule_id,
        ),
    )
    await cursor.close()
    await connection.commit()
    return RoutingRule(
        id=rule_id,
        tag_id=existing.tag_id,
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        created_at=existing.created_at,
        updated_at=timestamp,
    )


async def delete_tag_rule(
    connection: aiosqlite.Connection,
    rule_id: int,
) -> bool:
    """Delete a tag rule; ``True`` if a row was removed."""
    cursor = await connection.execute(
        "DELETE FROM tag_routing_rules WHERE id = ?",
        (rule_id,),
    )
    removed = cursor.rowcount or 0
    await cursor.close()
    await connection.commit()
    return removed > 0


async def reorder_tag_rules(
    connection: aiosqlite.Connection,
    tag_id: int,
    ids_in_priority_order: list[int],
) -> list[RoutingRule]:
    """Re-stamp ``priority`` columns to match the supplied order.

    Per spec §9 the request body is a list of rule ids in their new
    priority order; this helper assigns ``priority = (index + 1) * 10``
    so subsequent inserts can land between existing rules without a
    second reorder. Rules belonging to other tags or rules not in
    ``ids_in_priority_order`` are left untouched. Raises :class:`ValueError`
    if any id refers to a rule whose ``tag_id`` does not match.
    """
    if not ids_in_priority_order:
        return await list_for_tag(connection, tag_id)
    # Verify every id belongs to this tag — fail loudly rather than
    # silently re-assigning some rules and not others.
    placeholders = ",".join("?" * len(ids_in_priority_order))
    cursor = await connection.execute(
        f"SELECT id, tag_id FROM tag_routing_rules WHERE id IN ({placeholders})",
        tuple(ids_in_priority_order),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    found: dict[int, int] = {int(str(row[0])): int(str(row[1])) for row in rows}
    for rid in ids_in_priority_order:
        if rid not in found:
            raise ValueError(f"rule id {rid} does not exist")
        if found[rid] != tag_id:
            raise ValueError(f"rule id {rid} belongs to tag {found[rid]}, not tag {tag_id}")
    timestamp = _now_unix()
    for index, rid in enumerate(ids_in_priority_order):
        new_priority = (index + 1) * 10
        cursor = await connection.execute(
            "UPDATE tag_routing_rules SET priority=?, updated_at=? WHERE id=?",
            (new_priority, timestamp, rid),
        )
        await cursor.close()
    await connection.commit()
    return await list_for_tag(connection, tag_id)


# ---------------------------------------------------------------------------
# System rule CRUD
# ---------------------------------------------------------------------------


_SYSTEM_RULE_COLUMNS = (
    "SELECT id, priority, enabled, match_type, match_value, "
    "executor_model, advisor_model, advisor_max_uses, effort_level, "
    "reason, seeded, created_at, updated_at FROM system_routing_rules"
)


def _row_to_system_rule(row: aiosqlite.Row | tuple[object, ...]) -> SystemRoutingRule:
    return SystemRoutingRule(
        id=int(str(row[0])),
        priority=int(str(row[1])),
        enabled=bool(row[2]),
        match_type=str(row[3]),
        match_value=None if row[4] is None else str(row[4]),
        executor_model=str(row[5]),
        advisor_model=None if row[6] is None else str(row[6]),
        advisor_max_uses=int(str(row[7])),
        effort_level=str(row[8]),
        reason=str(row[9]),
        seeded=bool(row[10]),
        created_at=int(str(row[11])),
        updated_at=int(str(row[12])),
    )


async def create_system_rule(
    connection: aiosqlite.Connection,
    *,
    priority: int = 1000,
    enabled: bool = True,
    match_type: str,
    match_value: str | None,
    executor_model: str,
    advisor_model: str | None,
    advisor_max_uses: int = 5,
    effort_level: str = "auto",
    reason: str,
) -> SystemRoutingRule:
    """Insert a new user-added system rule (``seeded = 0``)."""
    timestamp = _now_unix()
    SystemRoutingRule(
        id=0,
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        seeded=False,
        created_at=timestamp,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "INSERT INTO system_routing_rules ("
        "priority, enabled, match_type, match_value, executor_model, "
        "advisor_model, advisor_max_uses, effort_level, reason, seeded, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            priority,
            1 if enabled else 0,
            match_type,
            match_value,
            executor_model,
            advisor_model,
            advisor_max_uses,
            effort_level,
            reason,
            0,
            timestamp,
            timestamp,
        ),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover — sqlite always returns rowid
        raise RuntimeError("create_system_rule: aiosqlite returned a None lastrowid")
    return SystemRoutingRule(
        id=int(new_id),
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        seeded=False,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def get_system_rule(
    connection: aiosqlite.Connection,
    rule_id: int,
) -> SystemRoutingRule | None:
    """Fetch a single system rule by id; ``None`` if absent."""
    cursor = await connection.execute(
        _SYSTEM_RULE_COLUMNS + " WHERE id = ?",
        (rule_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_system_rule(row)


async def list_system_rules(
    connection: aiosqlite.Connection,
    *,
    enabled_only: bool = False,
) -> list[SystemRoutingRule]:
    """Every system rule, ordered by priority then id."""
    if enabled_only:
        sql = _SYSTEM_RULE_COLUMNS + " WHERE enabled = 1 ORDER BY priority ASC, id ASC"
    else:
        sql = _SYSTEM_RULE_COLUMNS + " ORDER BY priority ASC, id ASC"
    cursor = await connection.execute(sql)
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_system_rule(row) for row in rows]


async def update_system_rule(
    connection: aiosqlite.Connection,
    rule_id: int,
    *,
    priority: int,
    enabled: bool,
    match_type: str,
    match_value: str | None,
    executor_model: str,
    advisor_model: str | None,
    advisor_max_uses: int,
    effort_level: str,
    reason: str,
) -> SystemRoutingRule | None:
    """Replace mutable fields on a system rule; ``None`` if not found.

    Seeded rules are editable (the user may want to retune the default
    keyword list); the ``seeded`` flag is preserved unchanged so the
    UI can still distinguish shipped rules from user-added ones.
    """
    existing = await get_system_rule(connection, rule_id)
    if existing is None:
        return None
    timestamp = _now_unix()
    SystemRoutingRule(
        id=rule_id,
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        seeded=existing.seeded,
        created_at=existing.created_at,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "UPDATE system_routing_rules SET priority=?, enabled=?, match_type=?, "
        "match_value=?, executor_model=?, advisor_model=?, "
        "advisor_max_uses=?, effort_level=?, reason=?, updated_at=? WHERE id=?",
        (
            priority,
            1 if enabled else 0,
            match_type,
            match_value,
            executor_model,
            advisor_model,
            advisor_max_uses,
            effort_level,
            reason,
            timestamp,
            rule_id,
        ),
    )
    await cursor.close()
    await connection.commit()
    return SystemRoutingRule(
        id=rule_id,
        priority=priority,
        enabled=enabled,
        match_type=match_type,
        match_value=match_value,
        executor_model=executor_model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        reason=reason,
        seeded=existing.seeded,
        created_at=existing.created_at,
        updated_at=timestamp,
    )


async def delete_system_rule(
    connection: aiosqlite.Connection,
    rule_id: int,
) -> bool:
    """Delete a system rule; ``True`` if a row was removed.

    Note: deleting a seeded rule is permitted — re-running the schema
    bootstrap on this DB will not re-create it (the partial unique
    index on ``(priority) WHERE seeded=1`` blocks the re-INSERT only
    if a *different* row at the same priority exists, but the original
    is gone). Restoring a deleted seed requires a fresh DB or a manual
    INSERT. The UI surfaces this with a "Delete" confirmation per the
    rule-editor behaviour.
    """
    cursor = await connection.execute(
        "DELETE FROM system_routing_rules WHERE id = ?",
        (rule_id,),
    )
    removed = cursor.rowcount or 0
    await cursor.close()
    await connection.commit()
    return removed > 0


__all__ = [
    "RoutingRule",
    "SystemRoutingRule",
    "create_system_rule",
    "create_tag_rule",
    "delete_system_rule",
    "delete_tag_rule",
    "get_system_rule",
    "get_tag_rule",
    "list_for_tag",
    "list_for_tags",
    "list_system_rules",
    "list_tag_rules",
    "reorder_tag_rules",
    "update_system_rule",
    "update_tag_rule",
]
