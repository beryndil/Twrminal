from __future__ import annotations

from pydantic import BaseModel


class SessionCreate(BaseModel):
    working_dir: str
    model: str
    title: str | None = None
    max_budget_usd: float | None = None


class SessionOut(BaseModel):
    id: str
    created_at: str
    updated_at: str
    working_dir: str
    model: str
    title: str | None = None
    max_budget_usd: float | None = None
    total_cost_usd: float = 0.0


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
