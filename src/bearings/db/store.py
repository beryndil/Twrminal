"""Public DB surface — a thin facade over the split `_common` /
`_sessions` / `_messages` / `_tags` modules. Callers keep using
`from bearings.db import store` + `store.create_session(...)` and
`store.attach_tag(...)`; the implementation lives in the sibling
modules one layer down.

This file is deliberately a re-export wall. Do not grow it with new
logic — add new functions to whichever `_*.py` module owns the
concern, then re-export here.
"""

from __future__ import annotations

from bearings.db._common import MIGRATIONS_DIR, init_db
from bearings.db._messages import (
    append_tool_output,
    attach_tool_calls_to_message,
    finish_tool_call,
    get_session_token_totals,
    insert_message,
    insert_tool_call_start,
    list_all_messages,
    list_all_tool_calls,
    list_messages,
    list_tool_calls,
    search_messages,
)
from bearings.db._reorg import (
    MoveResult,
    ReorgOp,
    delete_reorg_audit,
    detect_tool_call_group_warnings,
    list_reorg_audits,
    move_messages_tx,
    record_reorg_audit,
)
from bearings.db._sessions import (
    add_session_cost,
    create_session,
    delete_session,
    get_session,
    import_session,
    list_all_sessions,
    list_sessions,
    set_sdk_session_id,
    set_session_context_usage,
    set_session_permission_mode,
    update_session,
)
from bearings.db._tags import (
    attach_tag,
    create_tag,
    delete_tag,
    delete_tag_memory,
    detach_tag,
    get_tag,
    get_tag_memory,
    list_session_ids_for_tag,
    list_session_tags,
    list_tags,
    put_tag_memory,
    update_tag,
)

__all__ = [
    "MIGRATIONS_DIR",
    "MoveResult",
    "ReorgOp",
    "add_session_cost",
    "append_tool_output",
    "attach_tag",
    "attach_tool_calls_to_message",
    "create_session",
    "create_tag",
    "delete_session",
    "delete_reorg_audit",
    "delete_tag",
    "delete_tag_memory",
    "detach_tag",
    "detect_tool_call_group_warnings",
    "finish_tool_call",
    "get_session",
    "get_session_token_totals",
    "get_tag",
    "get_tag_memory",
    "import_session",
    "init_db",
    "insert_message",
    "insert_tool_call_start",
    "list_all_messages",
    "list_all_sessions",
    "list_all_tool_calls",
    "list_messages",
    "list_reorg_audits",
    "list_session_ids_for_tag",
    "list_session_tags",
    "list_sessions",
    "list_tags",
    "list_tool_calls",
    "move_messages_tx",
    "put_tag_memory",
    "record_reorg_audit",
    "search_messages",
    "set_sdk_session_id",
    "set_session_context_usage",
    "set_session_permission_mode",
    "update_session",
    "update_tag",
]
