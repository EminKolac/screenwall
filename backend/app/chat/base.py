"""External chat provider interface + the hard approval gate.

Chat is allowed ONLY for approved documents and may read ONLY the anonymized chat context
(storage layer 5). `ensure_chat_allowed` is the single choke point enforcing this.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models.document import Document


class ChatNotAllowed(PermissionError):
    """Raised when chat is attempted on a non-approved document."""


class ChatError(Exception):
    """A fixed contract ErrorCode (frontend/src/api/contract.ts) raised by the chat layer.

    Only `code` ever crosses the HTTP boundary — never provider output, CLI stderr or
    exception text.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def ensure_chat_allowed(doc: Document) -> None:
    if not doc.chat_enabled:
        raise ChatNotAllowed(
            f"Chat disabled: document {doc.id} status is '{doc.status.value}', not 'Approved'."
        )


@runtime_checkable
class ChatProvider(Protocol):
    name: str  # "ollama" | "claude_cli" | "codex_cli" (bkz. chat/providers.py)
    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str: ...


class SelectableProvider(ChatProvider, Protocol):
    """What the multi-provider chat flow needs on top of `chat` (see chat/providers.py)."""

    id: str  # contract ProviderId
    label: str
    local: bool  # True only for ollama; False means the consent gate (preview_hash) applies
    destination: str  # "Bu bilgisayar" | "Anthropic (Claude)" | "OpenAI (ChatGPT)"
    model: str

    def render(self, system_prompt: str, messages: list[dict], model: str = "") -> str:
        """The exact text `chat` sends for these inputs (shown in the consent preview)."""
        ...

    def status(self) -> dict:
        """Contract ProviderStatus. Never raises; never returns account identifiers."""
        ...
