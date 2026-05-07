# Memories — observable behavior

## Global memories index (gap-cycle-13-007)

The ``/memories`` route renders a **global flat-list view** of every
memory across every tag as its default state. This is the ``MemoriesIndex``
component.

### Index view layout

- **Header** — "Memories" heading.
- **Tag chip row** — a ``role="group"`` row of tag-name chips derived
  from the response. Chips only appear when **more than one tag** is
  represented in the list (single-tag installs skip the row).
  Each chip is a ``<button aria-pressed>`` toggle; clicking activates
  the filter, clicking the active chip clears it.
- **Flat memory list** — one row per ``(tag, memory)`` pair sorted by
  ``(tag_name ASC, memory_title ASC)`` — grouping by tag is implied
  by the sort. Each row shows the memory title, tag name badge, and a
  truncated body preview. Disabled memories render at reduced opacity
  with a "disabled" badge.
- **Empty state** — the copy "No memories yet — pick a tag to add one."
  renders **only** when ``GET /api/memories`` returns ``[]``. It is NOT
  shown when a chip filter reduces the visible rows to zero (the full
  list is still non-empty in that case).

### Navigation to per-tag editor

Clicking any row in the global index opens the per-tag editor
(``MemoriesEditor``) with:

1. The row's ``tag_id`` set as the active tag (fires ``setActiveTag``).
2. The row's ``memory_id`` passed as ``initialMemoryId``; once the
   memory list loads, the editor automatically opens that memory for
   editing (the form is pre-filled, ``editingId`` set to the memory
   id).

A "← All memories" back button in the editor shell returns to the
global index. Back clears ``editorTagId`` and ``editorMemoryId``.

### API contract — ``GET /api/memories``

| Field | Type | Notes |
|---|---|---|
| ``tag_id`` | int | Parent tag id |
| ``tag_name`` | str | Tag name as stored |
| ``tag_color`` | str \| null | Tag color hex string; null if unset |
| ``memory_id`` | int | Memory primary key |
| ``memory_title`` | str | Memory title |
| ``memory_body_preview`` | str | Body truncated to ``MEMORY_BODY_PREVIEW_MAX_LENGTH`` (200) chars |
| ``enabled`` | bool | Enabled state |
| ``updated_at`` | str | ISO-8601 UTC |

Sort order: ``(tag_name ASC, memory_title ASC)``.

Query params:

- ``?only_enabled=true`` — restricts to memories where ``enabled = true``.
  Same semantics as the per-tag ``GET /api/tags/{id}/memories`` endpoint.

Empty database → ``[]`` (not 404).

### Per-tag editor (existing behavior, unchanged)

``MemoriesEditor`` is still accessible directly — the ``/memories``
page now wraps it in the index/editor shell rather than rendering it
at the top level. Its internal behavior (tag selector, CRUD form,
enabled toggle, validation) is unchanged.

The ``initialTagId`` prop pre-selects a tag on mount (existing).
The ``initialMemoryId`` prop (added gap-cycle-13-007) auto-opens a
specific memory for editing once the memories list has loaded; consumed
once, then cleared.
