"""Pydantic models for API request/response validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)

class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=6)
    name: str = ""

class AuthResponse(BaseModel):
    token: str
    email: str
    name: str = ""
    user_id: int

class UserInfo(BaseModel):
    user_id: int
    email: str
    name: str = ""


# ── Chat ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None
    lang: str = "en"

class SessionSummary(BaseModel):
    id: int
    title: str
    agent_slug: str | None = None
    updated_at: str

class MessageOut(BaseModel):
    role: str
    content: str
    agent_slug: str | None = None

class SessionDetail(BaseModel):
    id: int
    title: str
    agent_slug: str | None = None
    messages: list[MessageOut]

class ShareResponse(BaseModel):
    token: str
    url: str


# ── Agents ────────────────────────────────────────────────────────────

class AgentOut(BaseModel):
    slug: str
    name: str
    category: str
    icon: str
    one_liner: str
    prefix: str
    example_prompts: list[str]
