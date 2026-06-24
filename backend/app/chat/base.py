"""External chat provider interface + the hard approval gate.

Chat is allowed ONLY for approved documents and may read ONLY the anonymized chat context
(storage layer 5). `ensure_chat_allowed` is the single choke point enforcing this.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models.document import Document


class ChatNotAllowed(PermissionError):
    """Raised when chat is attempted on a non-approved document."""


def ensure_chat_allowed(doc: Document) -> None:
    if not doc.chat_enabled:
        raise ChatNotAllowed(
            f"Chat disabled: document {doc.id} status is '{doc.status.value}', not 'Approved'."
        )


@runtime_checkable
class ChatProvider(Protocol):
    name: str  # openai | anthropic | azure
    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str: ...
