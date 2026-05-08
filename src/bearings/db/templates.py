"""``templates`` table queries — pre-baked session-config presets.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``templates``. Per ``docs/behavior/chat.md`` the
new-session dialog accepts a template selection that pre-populates the
form; per ``docs/behavior/keyboard-shortcuts.md`` §"Create" the ``t``
chord opens the template picker; per ``docs/behavior/context-menus.md``
§"Session row" the ``session.save_as_template`` action seeds a template
from a live session.

Public surface:

* :class:`Template` — frozen dataclass row mirror, with
  ``__post_init__`` validation against the routing/permission alphabets
  in :mod:`bearings.config.constants`.
* :func:`create`, :func:`get`, :func:`get_by_name`, :func:`list_all`,
  :func:`update`, :func:`delete` — CRUD; same return-shape conventions
  as :mod:`bearings.db.checkpoints`.

Tag set carrier
---------------

A template's tag set is persisted as a JSON-encoded array of tag
*names* (resolved to ids when the template is applied at the API layer
in item 1.10). Names rather than ids because tag rows can be deleted
and recreated; storing names lets a template survive a tag rebuild,
and the resolution-on-apply path naturally tolerates a missing tag
(it lands as a new tag). The :class:`Template` dataclass exposes the
list as a tuple (``tag_names: tuple[str, ...]``); serialisation /
deserialisation lives in :func:`_tag_names_to_json` and
:func:`_tag_names_from_json` so the JSON shape is exercised in one
place and the :class:`Template` dataclass stays frozen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import aiosqlite

from bearings.config.constants import (
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    KNOWN_EFFORT_LEVELS,
    KNOWN_EXECUTOR_MODELS,
    PERMISSION_PROFILE_NAMES,
    TEMPLATE_DESCRIPTION_MAX_LENGTH,
    TEMPLATE_NAME_MAX_LENGTH,
)
from bearings.db._id import now_iso
from bearings.db._validators import _is_known_model

# ---------------------------------------------------------------------------
# Template.__post_init__ validators
# ---------------------------------------------------------------------------


def _validate_template_name(name: str, description: str | None) -> None:
    """Raise if Template.name is empty/over-length or description is over-length."""
    if not name:
        raise ValueError("Template.name must be non-empty")
    if len(name) > TEMPLATE_NAME_MAX_LENGTH:
        raise ValueError(
            f"Template.name must be ≤ {TEMPLATE_NAME_MAX_LENGTH} chars (got {len(name)})"
        )
    if description is not None and len(description) > TEMPLATE_DESCRIPTION_MAX_LENGTH:
        raise ValueError(
            f"Template.description must be ≤ {TEMPLATE_DESCRIPTION_MAX_LENGTH} chars "
            f"(got {len(description)})"
        )


def _validate_template_routing(
    model: str,
    advisor_model: str | None,
    advisor_max_uses: int,
    effort_level: str,
    permission_profile: str,
) -> None:
    """Raise if any routing field violates its alphabet or floor constraint."""
    if not _is_known_model(model):
        raise ValueError(
            f"Template.model {model!r} is neither a known short name "
            f"{sorted(KNOWN_EXECUTOR_MODELS)} nor a full SDK ID prefixed "
            f"with {EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
        )
    if advisor_model is not None and not _is_known_model(advisor_model):
        raise ValueError(
            f"Template.advisor_model {advisor_model!r} is not a known "
            f"short name and does not begin with {EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
        )
    if advisor_max_uses < 0:
        raise ValueError(f"Template.advisor_max_uses must be ≥ 0 (got {advisor_max_uses})")
    if effort_level not in KNOWN_EFFORT_LEVELS:
        raise ValueError(
            f"Template.effort_level {effort_level!r} is not in {sorted(KNOWN_EFFORT_LEVELS)}"
        )
    if permission_profile not in PERMISSION_PROFILE_NAMES:
        raise ValueError(
            f"Template.permission_profile {permission_profile!r} is not in "
            f"{sorted(PERMISSION_PROFILE_NAMES)}"
        )


@dataclass(frozen=True)
class Template:
    """Row mirror for the ``templates`` table.

    Field semantics follow ``schema.sql`` and the routing-spec App A
    vocabulary. The ``tag_names`` field is the deserialised JSON-array
    column ``tag_names_json``; consumers should treat it as immutable
    (tuple of str) so the dataclass stays frozen.

    Validation in ``__post_init__`` mirrors
    :class:`bearings.agent.routing.RoutingDecision.__post_init__` for
    the routing-relevant fields so a template that could not satisfy
    a downstream :class:`RoutingDecision` cannot be inserted.
    """

    id: int
    name: str
    description: str | None
    model: str
    advisor_model: str | None
    advisor_max_uses: int
    effort_level: str
    permission_profile: str
    system_prompt_baseline: str | None
    working_dir_default: str | None
    tag_names: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        _validate_template_name(self.name, self.description)
        _validate_template_routing(
            self.model,
            self.advisor_model,
            self.advisor_max_uses,
            self.effort_level,
            self.permission_profile,
        )


def _tag_names_to_json(tag_names: tuple[str, ...]) -> str:
    """Serialise a tag-name tuple to its on-disk JSON-array form."""
    return json.dumps(list(tag_names))


def _tag_names_from_json(payload: str) -> tuple[str, ...]:
    """Deserialise the on-disk JSON-array column to an immutable tuple.

    Defensive: if the column carries malformed JSON (e.g. a manually-
    edited DB), surface a clear :class:`ValueError` rather than letting
    a ``json.JSONDecodeError`` bubble through opaquely.
    """
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Template.tag_names_json is not valid JSON: {payload!r}") from exc
    if not isinstance(decoded, list):
        raise ValueError(
            f"Template.tag_names_json must encode a JSON array (got {type(decoded).__name__})"
        )
    out: list[str] = []
    for item in decoded:
        if not isinstance(item, str):
            raise ValueError(
                f"Template.tag_names_json array entry must be a string (got {type(item).__name__})"
            )
        out.append(item)
    return tuple(out)


async def create(
    connection: aiosqlite.Connection,
    *,
    name: str,
    model: str,
    description: str | None = None,
    advisor_model: str | None = None,
    advisor_max_uses: int = 5,
    effort_level: str = "auto",
    permission_profile: str = "standard",
    system_prompt_baseline: str | None = None,
    working_dir_default: str | None = None,
    tag_names: tuple[str, ...] = (),
) -> Template:
    """Insert a new template row and return the populated dataclass.

    Validation lives in :class:`Template.__post_init__`; building the
    dataclass first means a malformed template raises before any DB
    write. The autoincremented integer id is read back via
    :attr:`aiosqlite.Cursor.lastrowid` so the returned :class:`Template`
    carries the canonical primary key the API layer surfaces.
    """
    timestamp = now_iso()
    cursor = await connection.execute(
        "INSERT INTO templates ("
        "name, description, model, advisor_model, advisor_max_uses, "
        "effort_level, permission_profile, system_prompt_baseline, "
        "working_dir_default, tag_names_json, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            description,
            model,
            advisor_model,
            advisor_max_uses,
            effort_level,
            permission_profile,
            system_prompt_baseline,
            working_dir_default,
            _tag_names_to_json(tag_names),
            timestamp,
            timestamp,
        ),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover — sqlite always returns a rowid on INSERT
        raise RuntimeError("templates.create: aiosqlite returned a None lastrowid")
    return Template(
        id=int(new_id),
        name=name,
        description=description,
        model=model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        permission_profile=permission_profile,
        system_prompt_baseline=system_prompt_baseline,
        working_dir_default=working_dir_default,
        tag_names=tag_names,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def get(connection: aiosqlite.Connection, template_id: int) -> Template | None:
    """Fetch a single template by id; ``None`` if no such row."""
    cursor = await connection.execute(
        _SELECT_TEMPLATE_COLUMNS + " WHERE id = ?",
        (template_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    return _row_to_template(row)


async def get_by_name(connection: aiosqlite.Connection, name: str) -> Template | None:
    """Fetch a single template by unique ``name``; ``None`` if absent.

    The schema's ``UNIQUE`` constraint on ``templates.name`` makes this
    a key lookup; the API layer (item 1.10) uses it to surface a
    "name already exists" 409 before attempting an INSERT.
    """
    cursor = await connection.execute(
        _SELECT_TEMPLATE_COLUMNS + " WHERE name = ?",
        (name,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    return _row_to_template(row)


async def list_all(connection: aiosqlite.Connection) -> list[Template]:
    """Every template, alphabetically by ``name``.

    Templates are admin-side primitives; the user picks one from a
    dropdown / picker (per ``docs/behavior/keyboard-shortcuts.md`` `t`
    chord). Alphabetical order matches the picker's natural rendering.
    """
    cursor = await connection.execute(_SELECT_TEMPLATE_COLUMNS + " ORDER BY name ASC")
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_template(row) for row in rows]


async def update(
    connection: aiosqlite.Connection,
    template_id: int,
    *,
    name: str,
    model: str,
    description: str | None,
    advisor_model: str | None,
    advisor_max_uses: int,
    effort_level: str,
    permission_profile: str,
    system_prompt_baseline: str | None,
    working_dir_default: str | None,
    tag_names: tuple[str, ...],
) -> Template | None:
    """Replace a template row's mutable fields; returns the new value.

    Returns ``None`` if no row with ``template_id`` existed, mirroring
    :func:`get`'s 404-friendly contract. ``created_at`` is preserved;
    ``updated_at`` is bumped to the current UTC instant. The full
    field set is required (not partial) because the API layer
    validates the resulting :class:`Template` shape and partial
    updates would necessitate a SELECT-then-merge dance whose semantics
    differ from a clean replace.
    """
    existing = await get(connection, template_id)
    if existing is None:
        return None
    timestamp = now_iso()
    cursor = await connection.execute(
        "UPDATE templates SET "
        "name = ?, description = ?, model = ?, advisor_model = ?, "
        "advisor_max_uses = ?, effort_level = ?, permission_profile = ?, "
        "system_prompt_baseline = ?, working_dir_default = ?, "
        "tag_names_json = ?, updated_at = ? "
        "WHERE id = ?",
        (
            name,
            description,
            model,
            advisor_model,
            advisor_max_uses,
            effort_level,
            permission_profile,
            system_prompt_baseline,
            working_dir_default,
            _tag_names_to_json(tag_names),
            timestamp,
            template_id,
        ),
    )
    await cursor.close()
    await connection.commit()
    return Template(
        id=template_id,
        name=name,
        description=description,
        model=model,
        advisor_model=advisor_model,
        advisor_max_uses=advisor_max_uses,
        effort_level=effort_level,
        permission_profile=permission_profile,
        system_prompt_baseline=system_prompt_baseline,
        working_dir_default=working_dir_default,
        tag_names=tag_names,
        created_at=existing.created_at,
        updated_at=timestamp,
    )


async def delete(connection: aiosqlite.Connection, template_id: int) -> bool:
    """Delete one template by id; returns ``True`` if a row was removed."""
    cursor = await connection.execute(
        "DELETE FROM templates WHERE id = ?",
        (template_id,),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


# Single source of truth for the column list — keeps the SELECT in
# four helpers synchronised. Adding a column means editing this string
# and :func:`_row_to_template` together.
_SELECT_TEMPLATE_COLUMNS = (
    "SELECT id, name, description, model, advisor_model, advisor_max_uses, "
    "effort_level, permission_profile, system_prompt_baseline, "
    "working_dir_default, tag_names_json, created_at, updated_at "
    "FROM templates"
)


def _row_to_template(row: aiosqlite.Row | tuple[object, ...]) -> Template:
    """Translate a raw SELECT tuple to a validated :class:`Template`.

    ``int(...)`` accepts ``str | int`` at runtime; the row tuple is
    typed ``object`` because aiosqlite does not parametrise its row
    accessor return types. Round-tripping through ``str()`` then
    ``int()`` keeps the function strict-mypy clean without an
    ``Any``-typed escape and tolerates either the native int the
    AUTOINCREMENT column produces or a stringified value if a future
    row factory wraps it.
    """
    return Template(
        id=int(str(row[0])),
        name=str(row[1]),
        description=None if row[2] is None else str(row[2]),
        model=str(row[3]),
        advisor_model=None if row[4] is None else str(row[4]),
        advisor_max_uses=int(str(row[5])),
        effort_level=str(row[6]),
        permission_profile=str(row[7]),
        system_prompt_baseline=None if row[8] is None else str(row[8]),
        working_dir_default=None if row[9] is None else str(row[9]),
        tag_names=_tag_names_from_json(str(row[10])),
        created_at=str(row[11]),
        updated_at=str(row[12]),
    )


__all__ = [
    "Template",
    "create",
    "delete",
    "get",
    "get_by_name",
    "list_all",
    "update",
]
