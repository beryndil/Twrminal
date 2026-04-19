from __future__ import annotations

from pydantic import BaseModel


class SessionCreate(BaseModel):
    working_dir: str
    model: str
    title: str | None = None
    description: str | None = None
    max_budget_usd: float | None = None


class SessionUpdate(BaseModel):
    """Partial update for an existing session. Any unset field is left
    unchanged; explicit `None` for any nullable field clears it."""

    title: str | None = None
    description: str | None = None
    max_budget_usd: float | None = None
    session_instructions: str | None = None
    # Distinguishes "not provided" from "set to null" for the nullable
    # columns. Pydantic writes `model_fields_set` so routes can dispatch
    # off what was actually passed.


class SessionOut(BaseModel):
    id: str
    created_at: str
    updated_at: str
    working_dir: str
    model: str
    title: str | None = None
    description: str | None = None
    max_budget_usd: float | None = None
    total_cost_usd: float = 0.0
    message_count: int = 0
    session_instructions: str | None = None


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    thinking: str | None = None
    created_at: str


class ToolCallOut(BaseModel):
    id: str
    session_id: str
    message_id: str | None = None
    name: str
    input: str
    output: str | None = None
    error: str | None = None
    started_at: str
    finished_at: str | None = None


class SearchHit(BaseModel):
    message_id: str
    session_id: str
    session_title: str | None = None
    model: str
    role: str
    snippet: str
    created_at: str


class TagCreate(BaseModel):
    name: str
    color: str | None = None
    pinned: bool = False
    sort_order: int = 0


class TagUpdate(BaseModel):
    """Partial update for an existing tag. Any unset field is left
    unchanged; explicit `None` for `color` clears it."""

    name: str | None = None
    color: str | None = None
    pinned: bool | None = None
    sort_order: int | None = None


class TagOut(BaseModel):
    id: int
    name: str
    color: str | None = None
    pinned: bool
    sort_order: int
    created_at: str
    session_count: int = 0


class TagMemoryPut(BaseModel):
    content: str


class TagMemoryOut(BaseModel):
    tag_id: int
    content: str
    updated_at: str


class SystemPromptLayerOut(BaseModel):
    name: str
    kind: str
    content: str
    token_count: int


class SystemPromptOut(BaseModel):
    layers: list[SystemPromptLayerOut]
    total_tokens: int
