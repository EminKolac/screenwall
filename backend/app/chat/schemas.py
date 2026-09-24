"""Chat request/response models — mirror the "chat" section of frontend/src/api/contract.ts.

Change both sides together. Response models also act as an allow-list: a field that is not
declared here (e.g. a source's full text or a CLI's account details) cannot reach the browser.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProviderId = Literal["ollama", "claude_cli", "codex_cli"]

MAX_DOCS = 20
MAX_INPUT_CHARS = 20_000  # request bound; ChatService then caps to chat_max_message_chars
MAX_HISTORY = 8  # ChatService sends the last 8 turns; a request may not carry more


class ProviderStatus(BaseModel):
    id: ProviderId
    label: str
    local: bool
    available: bool
    installed: bool | None
    compatible: bool | None
    authenticated: bool | None
    version: str | None
    model: str | None
    login_command: str | None
    problem: str | None


class ProvidersResponse(BaseModel):
    default: ProviderId
    providers: list[ProviderStatus]


class ChatSource(BaseModel):
    id: str
    doc_id: str
    unit_id: str
    label: str
    excerpt: str


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("question must not be blank")
    return value


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_INPUT_CHARS)


class ChatPreviewRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=MAX_DOCS)
    question: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    provider: ProviderId
    # The exact history slice POST /api/chat will send: it is part of sent_text and preview_hash.
    history: list[ChatMessage] = Field(default_factory=list, max_length=MAX_HISTORY)

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        return _not_blank(value)


class ChatPreviewResponse(BaseModel):
    provider: ProviderId
    preview_hash: str
    destination: str
    sources: list[ChatSource]
    sent_text: str
    context_chars: int


class ChatRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=MAX_DOCS)
    question: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    provider: ProviderId
    preview_hash: str | None = Field(default=None, max_length=128)
    history: list[ChatMessage] = Field(default_factory=list, max_length=MAX_HISTORY)

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        return _not_blank(value)


class ChatResponse(BaseModel):
    answer: str
    citations: list[ChatSource]
    provider: ProviderId
    elapsed_ms: int
