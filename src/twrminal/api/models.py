from __future__ import annotations

from pydantic import BaseModel


class SessionCreate(BaseModel):
    working_dir: str
    model: str
    title: str | None = None


class SessionOut(BaseModel):
    id: str
    created_at: str
    updated_at: str
    working_dir: str
    model: str
    title: str | None = None


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: str
