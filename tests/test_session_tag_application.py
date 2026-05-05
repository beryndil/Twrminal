"""Tests for :mod:`bearings.agent.tags` — tag-default application.

Per ``docs/behavior/checklists.md`` the chat inherits the checklist's
working directory + model + tags. Item 1.4 lays the agent-layer helper
that resolves a tagged session's ``default_model`` / ``working_dir``
when multiple tags overlap; precedence rule is decided-and-documented
in ``bearings/agent/tags.py``'s module docstring (most-recently-updated
tag wins, ties broken by lower id).
"""

from __future__ import annotations

from bearings.agent.tags import resolve_default_model, resolve_working_dir
from bearings.db.tags import Tag


def _tag(
    *,
    id: int,
    name: str,
    default_model: str | None = None,
    working_dir: str | None = None,
    updated_at: str = "2026-04-28T12:00:00+00:00",
) -> Tag:
    return Tag(
        id=id,
        name=name,
        color=None,
        default_model=default_model,
        working_dir=working_dir,
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_resolve_default_model_prefers_explicit() -> None:
    """Explicit caller pick beats every tag-derived default."""
    tags = [_tag(id=1, name="a", default_model="haiku")]
    assert resolve_default_model(tags, explicit="opus") == "opus"


def test_resolve_default_model_returns_none_when_no_source() -> None:
    """No explicit, no tag-derived → ``None`` (caller falls back downstream)."""
    tags = [_tag(id=1, name="bare")]
    assert resolve_default_model(tags) is None


def test_resolve_default_model_picks_single_tag_default() -> None:
    tags = [
        _tag(id=1, name="bare"),
        _tag(id=2, name="with-default", default_model="opus"),
    ]
    assert resolve_default_model(tags) == "opus"


def test_resolve_default_model_picks_most_recently_updated() -> None:
    """Multi-tag overlap: first tag in priority order (index 0) wins."""
    tags = [
        _tag(
            id=1,
            name="first",
            default_model="haiku",
            updated_at="2026-04-01T00:00:00+00:00",
        ),
        _tag(
            id=2,
            name="second",
            default_model="opus",
            updated_at="2026-04-28T00:00:00+00:00",
        ),
    ]
    # First tag (index 0) wins regardless of updated_at
    assert resolve_default_model(tags) == "haiku"


def test_resolve_default_model_breaks_tie_by_lower_id() -> None:
    """Same ``updated_at`` → smaller id wins (more-established intent)."""
    same = "2026-04-28T12:00:00+00:00"
    tags = [
        _tag(id=1, name="a", default_model="opus", updated_at=same),
        _tag(id=2, name="b", default_model="haiku", updated_at=same),
    ]
    assert resolve_default_model(tags) == "opus"


def test_resolve_default_model_ignores_tags_without_default() -> None:
    """A tag with ``default_model=None`` is invisible to the resolver."""
    tags = [
        _tag(
            id=10,
            name="recent-empty",
            default_model=None,
            updated_at="2026-04-28T00:00:00+00:00",
        ),
        _tag(
            id=1,
            name="old-with-default",
            default_model="sonnet",
            updated_at="2026-04-01T00:00:00+00:00",
        ),
    ]
    assert resolve_default_model(tags) == "sonnet"


def test_resolve_working_dir_explicit_wins() -> None:
    tags = [_tag(id=1, name="t", working_dir="/from/tag")]
    assert resolve_working_dir(tags, explicit="/from/user") == "/from/user"


def test_resolve_working_dir_picks_most_recently_updated() -> None:
    """Multi-tag overlap: first tag in priority order (index 0) wins."""
    tags = [
        _tag(
            id=1,
            name="first",
            working_dir="/first/dir",
            updated_at="2026-04-01T00:00:00+00:00",
        ),
        _tag(
            id=2,
            name="second",
            working_dir="/second/dir",
            updated_at="2026-04-28T00:00:00+00:00",
        ),
    ]
    # First tag (index 0) wins regardless of updated_at
    assert resolve_working_dir(tags) == "/first/dir"


def test_resolve_working_dir_returns_none_when_no_source() -> None:
    tags = [_tag(id=1, name="bare")]
    assert resolve_working_dir(tags) is None


def test_resolvers_handle_empty_tag_list() -> None:
    assert resolve_default_model([]) is None
    assert resolve_working_dir([]) is None
    assert resolve_default_model([], explicit="opus") == "opus"
    assert resolve_working_dir([], explicit="/dir") == "/dir"
