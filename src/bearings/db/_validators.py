"""Shared model-name validator for the ``db`` layer.

This module is the single source of truth for the ``_is_known_model``
predicate used by both :mod:`bearings.db.tags` and
:mod:`bearings.db.templates`.  Extracting it here ends the duplication
called out in V1_FEATURE_AUDIT.md feature 5 finding 9 and gives
:mod:`bearings.db` a clean, importable alphabet check that future DB
concern modules (e.g. routing, quota) can reuse without coupling
unrelated tables to each other.

The helper deliberately lives in the ``db`` package rather than in
``config`` because it combines two constants into a single boolean
predicate — a decision, not a raw configuration value.  The ``config``
package owns the alphabets (:data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS`,
:data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX`); this
module owns the composition.

Public surface
--------------
* :func:`_is_known_model` — returns ``True`` when ``name`` is either a
  recognised executor short name or a full SDK model-ID that begins with
  the approved prefix.
"""

from __future__ import annotations

from bearings.config.constants import (
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    KNOWN_EXECUTOR_MODELS,
)


def _is_known_model(name: str) -> bool:
    """Return ``True`` when ``name`` is a valid executor model identifier.

    A model identifier is valid when it is one of the recognised short
    names in :data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS`
    *or* when it is a full SDK model-ID that begins with
    :data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX`.
    This matches the alphabet enforced by
    :class:`bearings.agent.routing.RoutingDecision` at the agent layer.

    Used by :class:`bearings.db.tags.Tag.__post_init__` and
    :class:`bearings.db.templates.Template.__post_init__` to validate
    the ``default_model`` / ``model`` / ``advisor_model`` fields before
    any DB write.
    """
    return name in KNOWN_EXECUTOR_MODELS or name.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX)


__all__ = ["_is_known_model"]
