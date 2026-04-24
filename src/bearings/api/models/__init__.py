"""Public DTO surface for the `bearings.api` package.

Grouped into domain submodules to stay under the project's 400-line
file cap. Every name previously exported from the flat `models.py`
module is re-exported here, so callers continue to use
`from bearings.api.models import X`.
"""

from __future__ import annotations

from .artifacts import ArtifactOut, ArtifactRegister
from .checklists import (
    AutoRunStart,
    AutoRunStatus,
    ChecklistOut,
    ChecklistUpdate,
    ItemCreate,
    ItemOut,
    ItemToggle,
    ItemUpdate,
    ReorderRequest,
    ReorderResult,
)
from .checkpoints import CheckpointCreate, CheckpointForkRequest, CheckpointOut
from .commands import CommandOut, CommandsListOut
from .fs import FsEntryOut, FsListOut, FsPickOut, UploadOut
from .messages import Attachment, MessageOut, MessagePatchBody, TokenTotalsOut
from .paired import PairedChatCreate
from .prompts import SystemPromptLayerOut, SystemPromptOut
from .reorg import (
    ReorgAuditOut,
    ReorgMergeRequest,
    ReorgMergeResult,
    ReorgMoveRequest,
    ReorgMoveResult,
    ReorgSplitRequest,
    ReorgSplitResult,
    ReorgWarning,
)
from .search import SearchHit
from .sessions import (
    NewSessionSpec,
    SessionBulkBody,
    SessionBulkResult,
    SessionCreate,
    SessionExportBundle,
    SessionOut,
    SessionUpdate,
)
from .tags import TagCreate, TagGroup, TagMemoryOut, TagMemoryPut, TagOut, TagUpdate
from .templates import TemplateCreate, TemplateInstantiateRequest, TemplateOut
from .tools import TodoItemOut, TodosOut, ToolCallOut
from .vault import (
    VaultDocOut,
    VaultEntryOut,
    VaultIndexOut,
    VaultSearchHit,
    VaultSearchOut,
)

__all__ = [
    "ArtifactOut",
    "ArtifactRegister",
    "Attachment",
    "AutoRunStart",
    "AutoRunStatus",
    "ChecklistOut",
    "ChecklistUpdate",
    "CheckpointCreate",
    "CheckpointForkRequest",
    "CheckpointOut",
    "CommandOut",
    "CommandsListOut",
    "FsEntryOut",
    "FsListOut",
    "FsPickOut",
    "ItemCreate",
    "ItemOut",
    "ItemToggle",
    "ItemUpdate",
    "MessageOut",
    "MessagePatchBody",
    "NewSessionSpec",
    "PairedChatCreate",
    "ReorderRequest",
    "ReorderResult",
    "ReorgAuditOut",
    "ReorgMergeRequest",
    "ReorgMergeResult",
    "ReorgMoveRequest",
    "ReorgMoveResult",
    "ReorgSplitRequest",
    "ReorgSplitResult",
    "ReorgWarning",
    "SearchHit",
    "SessionBulkBody",
    "SessionBulkResult",
    "SessionCreate",
    "SessionExportBundle",
    "SessionOut",
    "SessionUpdate",
    "SystemPromptLayerOut",
    "SystemPromptOut",
    "TagCreate",
    "TagGroup",
    "TagMemoryOut",
    "TagMemoryPut",
    "TagOut",
    "TagUpdate",
    "TemplateCreate",
    "TemplateInstantiateRequest",
    "TemplateOut",
    "TodoItemOut",
    "TodosOut",
    "TokenTotalsOut",
    "ToolCallOut",
    "UploadOut",
    "VaultDocOut",
    "VaultEntryOut",
    "VaultIndexOut",
    "VaultSearchHit",
    "VaultSearchOut",
]
