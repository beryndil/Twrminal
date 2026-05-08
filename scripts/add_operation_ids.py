#!/usr/bin/env python3
"""Add operation_id= to every @router.<verb>(...) decorator in web/routes/*.py.

Run from the repo root:
    uv run python scripts/add_operation_ids.py [--dry-run]

Idempotent: skips decorators that already carry operation_id=.
Single-line decorators that would exceed 100 chars after the addition are
automatically expanded to multi-line form.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROUTES_DIR = Path("src/bearings/web/routes")
MAX_LINE_LENGTH = 100

# Mapping: (file_stem, function_name) → stable kebab-case operation_id.
OPERATION_IDS: dict[tuple[str, str], str] = {
    ("approvals", "resolve_approval"): "resolve-approval",
    ("checklists", "create_item"): "create-checklist-item",
    ("checklists", "list_items"): "list-checklist-items",
    ("checklists", "get_overview"): "get-checklist-overview",
    ("checklists", "get_item"): "get-checklist-item",
    ("checklists", "update_item"): "update-checklist-item",
    ("checklists", "delete_item"): "delete-checklist-item",
    ("checklists", "check_item"): "check-checklist-item",
    ("checklists", "uncheck_item"): "uncheck-checklist-item",
    ("checklists", "block_item"): "block-checklist-item",
    ("checklists", "unblock_item"): "unblock-checklist-item",
    ("checklists", "link_chat"): "link-checklist-item-chat",
    ("checklists", "unlink_chat"): "unlink-checklist-item-chat",
    ("checklists", "list_item_legs"): "list-checklist-item-legs",
    ("checklists", "move_item"): "move-checklist-item",
    ("checklists", "indent_item"): "indent-checklist-item",
    ("checklists", "outdent_item"): "outdent-checklist-item",
    ("checklists", "start_run"): "start-checklist-run",
    ("checklists", "stop_run"): "stop-checklist-run",
    ("checklists", "pause_run"): "pause-checklist-run",
    ("checklists", "resume_run"): "resume-checklist-run",
    ("checklists", "skip_current"): "skip-current-checklist-item",
    ("checklists", "run_status"): "get-checklist-run-status",
    ("checkpoints", "create_checkpoint"): "create-checkpoint",
    ("checkpoints", "list_checkpoints"): "list-checkpoints",
    ("checkpoints", "delete_checkpoint"): "delete-checkpoint",
    ("checkpoints", "fork_checkpoint"): "fork-checkpoint",
    ("commands", "list_commands"): "list-commands",
    ("diag", "get_server"): "get-server-diag",
    ("diag", "get_sessions"): "get-runner-diag",
    ("diag", "get_drivers"): "get-driver-diag",
    ("diag", "get_quota_diag"): "get-quota-diag",
    ("fs", "get_list"): "fs-list",
    ("fs", "get_read"): "fs-read",
    ("fs", "post_pick"): "fs-pick",
    ("health", "get_health"): "get-health",
    ("history", "search_history"): "search-history",
    ("import_db", "post_import_bearings"): "import-bearings-db",
    ("memories", "create_memory"): "create-tag-memory",
    ("memories", "list_memories_for_tag"): "list-tag-memories",
    ("memories", "list_all_memories"): "list-all-memories",
    ("memories", "get_memory"): "get-memory",
    ("memories", "update_memory"): "update-memory",
    ("memories", "delete_memory"): "delete-memory",
    ("messages", "list_messages"): "list-messages",
    ("messages", "get_message"): "get-message",
    ("messages", "patch_message_pinned"): "patch-message-pinned",
    ("messages", "patch_message_hidden"): "patch-message-hidden",
    ("messages", "delete_message"): "delete-message",
    ("messages", "move_message"): "move-message",
    ("metrics", "get_metrics"): "get-metrics",
    ("paired_chats", "spawn_chat"): "spawn-paired-chat",
    ("pending", "resolve_pending_op"): "resolve-pending-op",
    ("pending", "delete_pending_op"): "delete-pending-op",
    ("preferences", "get_preferences"): "get-preferences",
    ("preferences", "patch_preferences"): "patch-preferences",
    ("preferences", "get_avatar"): "get-avatar",
    ("preferences", "create_avatar"): "create-avatar",
    ("preferences", "delete_avatar"): "delete-avatar",
    ("preferences", "refresh_from_system"): "sync-preferences-from-system",
    ("quota", "get_current"): "get-quota-current",
    ("quota", "refresh"): "refresh-quota",
    ("quota", "get_history"): "get-quota-history",
    ("reorg", "merge_session"): "reorg-merge-sessions",
    ("reorg", "fork_session"): "reorg-split-session",
    ("reorg", "move_message"): "reorg-move-message",
    ("reorg", "list_reorg_audits"): "list-reorg-audits",
    ("reorg", "delete_reorg_audit"): "undo-reorg",
    ("routing", "list_tag_rules"): "list-tag-routing-rules",
    ("routing", "create_tag_rule"): "create-tag-routing-rule",
    ("routing", "update_tag_rule"): "update-routing-rule",
    ("routing", "delete_tag_rule"): "delete-routing-rule",
    ("routing", "reorder_tag_rules"): "reorder-tag-routing-rules",
    ("routing", "list_system_rules"): "list-system-routing-rules",
    ("routing", "create_system_rule"): "create-system-routing-rule",
    ("routing", "update_system_rule"): "update-system-routing-rule",
    ("routing", "delete_system_rule"): "delete-system-routing-rule",
    ("routing", "preview_routing"): "preview-routing",
    ("sessions_bulk", "run_sessions_bulk"): "bulk-sessions",
    ("sessions", "list_sessions"): "list-sessions",
    ("sessions", "create_session"): "create-session",
    ("sessions", "get_session"): "get-session",
    ("sessions", "patch_session"): "patch-session",
    ("sessions", "delete_session"): "delete-session",
    ("sessions", "close_session"): "close-session",
    ("sessions", "patch_session_model"): "patch-session-model",
    ("sessions", "patch_session_permission_mode"): "patch-session-permission-mode",
    ("sessions", "patch_session_pinned"): "patch-session-pinned",
    ("sessions", "reopen_session"): "reopen-session",
    ("sessions", "update_session_viewed"): "mark-session-viewed",
    ("sessions", "resume_session"): "recover-session",
    ("sessions", "get_paired_chat_info_route"): "get-session-paired-chat-info",
    ("sessions", "list_session_tool_calls"): "list-session-tool-calls",
    ("sessions", "get_session_todos"): "get-session-todos",
    ("sessions", "get_session_system_prompt"): "get-session-system-prompt",
    ("sessions", "get_session_tokens"): "get-session-tokens",
    ("sessions", "export_session"): "export-session",
    ("sessions", "import_session"): "import-session",
    ("sessions", "regenerate_session"): "regenerate-session",
    ("sessions", "regenerate_from_message"): "regenerate-session-from-message",
    ("sessions", "stop_session_turn"): "stop-session-turn",
    ("sessions", "prompt_session"): "prompt-session",
    ("shell", "post_exec"): "shell-exec",
    ("spawn_from_reply", "spawn_from_reply"): "spawn-session-from-reply",
    ("tags", "create_tag"): "create-tag",
    ("tags", "list_tags"): "list-tags",
    ("tags", "update_tags_sort_order"): "update-tags-sort-order",
    ("tags", "list_tag_groups"): "list-tag-groups",
    ("tags", "get_tag"): "get-tag",
    ("tags", "update_tag"): "update-tag",
    ("tags", "patch_tag_pinned"): "patch-tag-pinned",
    ("tags", "delete_tag"): "delete-tag",
    ("tags", "list_session_tags"): "list-session-tags",
    ("tags", "attach_tag"): "attach-tag-to-session",
    ("tags", "detach_tag"): "detach-tag-from-session",
    ("templates", "create_template"): "create-template",
    ("templates", "list_templates"): "list-templates",
    ("templates", "get_template"): "get-template",
    ("templates", "patch_template"): "patch-template",
    ("templates", "delete_template"): "delete-template",
    ("templates", "create_session_from_template"): "instantiate-template",
    ("uploads", "post_upload"): "create-upload",
    ("uploads", "list_uploads"): "list-uploads",
    ("uploads", "get_upload"): "get-upload",
    ("uploads", "get_upload_content"): "get-upload-content",
    ("uploads", "delete_upload"): "delete-upload",
    ("usage", "by_model"): "get-usage-by-model",
    ("usage", "by_tag"): "get-usage-by-tag",
    ("usage", "override_rates"): "get-usage-override-rates",
    ("vault", "list_vault"): "list-vault",
    ("vault", "search_vault"): "search-vault",
    ("vault", "get_vault_doc_by_path"): "get-vault-doc-by-path",
    ("vault", "get_vault_doc"): "get-vault-doc",
    # ws_sessions.py: @router.websocket — no operation_id (not an OpenAPI operation)
}

_DECORATOR_START = re.compile(r"^(\s*)@router\.(get|post|put|patch|delete|options|head|trace)\(")
_DEF_LINE = re.compile(r"^\s*async\s+def\s+(\w+)\s*\(")


def _expand_single_line(line: str, indent: str, op_id: str) -> str:
    """Expand a single-line decorator to multi-line, appending operation_id.

    Input:  @router.get("/api/foo", response_model=FooOut)
    Output: @router.get(\n    "/api/foo",\n    response_model=FooOut,\n    operation_id="...",\n)
    """
    # Strip trailing newline for manipulation
    stripped = line.rstrip("\n")
    # Find opening paren
    open_idx = stripped.index("(")
    verb_part = stripped[: open_idx + 1]  # e.g. '@router.get('
    inner = stripped[open_idx + 1 :]  # e.g. '"/api/foo", response_model=FooOut)'
    # Remove trailing ')'
    assert inner.endswith(")"), f"Unexpected decorator end: {inner!r}"
    inner = inner[:-1]  # strip closing paren

    # Split the args on commas (top-level only — safe for these decorators since
    # their args are simple keyword arguments, no nested commas in practice)
    args = [a.strip() for a in inner.split(",") if a.strip()]
    child_indent = indent + "    "
    lines = [verb_part + "\n"]
    for arg in args:
        lines.append(f"{child_indent}{arg},\n")
    lines.append(f'{child_indent}operation_id="{op_id}",\n')
    lines.append(f"{indent})\n")
    return "".join(lines)


def process_file(path: Path, dry_run: bool = False) -> tuple[int, int]:
    """Process one route file. Returns (decorators_found, decorators_patched)."""
    lines = path.read_text().splitlines(keepends=True)
    file_stem = path.stem
    found = 0
    patched = 0
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        dm = _DECORATOR_START.match(line)
        if not dm:
            result.append(line)
            i += 1
            continue

        indent = dm.group(1)

        # Collect the full decorator block (track paren depth to find end)
        dec_lines: list[str] = []
        depth = 0
        j = i
        while j < len(lines):
            ln = lines[j]
            dec_lines.append(ln)
            depth += ln.count("(") - ln.count(")")
            j += 1
            if depth <= 0:
                break

        found += 1
        block_text = "".join(dec_lines)

        # Skip if operation_id already present
        if "operation_id=" in block_text:
            result.extend(dec_lines)
            i = j
            continue

        # Find the function name in the lines immediately following
        func_name: str | None = None
        for k in range(j, min(j + 5, len(lines))):
            fm = _DEF_LINE.match(lines[k])
            if fm:
                func_name = fm.group(1)
                break

        if func_name is None:
            result.extend(dec_lines)
            i = j
            continue

        key = (file_stem, func_name)
        op_id = OPERATION_IDS.get(key)
        if op_id is None:
            print(f"  WARNING: no mapping for {key}", file=sys.stderr)
            result.extend(dec_lines)
            i = j
            continue

        is_single_line = len(dec_lines) == 1
        if is_single_line:
            # Try inline insertion first
            last = dec_lines[0]
            close_pos = last.rfind(")")
            candidate = last[:close_pos] + f', operation_id="{op_id}"' + last[close_pos:]
            if len(candidate.rstrip("\n")) <= MAX_LINE_LENGTH:
                result.append(candidate)
            else:
                # Expand to multi-line
                result.append(_expand_single_line(last, indent, op_id))
        else:
            # Multi-line: insert a new kwarg line before the closing ')'
            last = dec_lines[-1]
            close_pos = last.rfind(")")
            last_nl = last.rfind("\n", 0, close_pos)
            indent_of_close = "" if last_nl == -1 else last[last_nl + 1 : close_pos]
            new_last = indent_of_close + f'    operation_id="{op_id}",\n' + last
            result.extend([*dec_lines[:-1], new_last])

        patched += 1
        i = j

    new_source = "".join(result)
    if not dry_run:
        path.write_text(new_source)
    return found, patched


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    total_found = 0
    total_patched = 0

    for py_file in sorted(ROUTES_DIR.glob("*.py")):
        if py_file.stem.startswith("_"):
            continue
        found, patched = process_file(py_file, dry_run=dry_run)
        if found > 0:
            print(f"  {py_file.name}: {found} decorators, {patched} patched")
        total_found += found
        total_patched += patched

    print(f"\nTotal: {total_found} decorators found, {total_patched} patched")
    if dry_run:
        print("(dry-run — no files written)")


if __name__ == "__main__":
    main()
