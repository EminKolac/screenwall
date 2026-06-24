"""Chat service — the single choke point for any external LLM call (Codex CRITICAL fix).

ALL chat goes through `ChatService.chat`. It enforces, in order:
  1. document status is APPROVED (`ensure_chat_allowed`);
  2. the requested data is the externally-shareable chat-context layer (`assert_shareable`);
  3. an approved chat-context artifact actually exists.
Only storage layer 5 (CHAT_CONTEXT) is ever read. User-supplied messages are length-capped and
PII-redacted before leaving the machine, so a user cannot smuggle raw PII into the provider call.
"""
from __future__ import annotations

from app.chat.base import ChatNotAllowed, ChatProvider, ensure_chat_allowed
from app.config import Settings
from app.models.document import Document
from app.security.logging import redact
from app.storage.base import StorageBackend, StorageLayer, assert_shareable

_CONTEXT_NAME = "context.txt"

_SYSTEM_TEMPLATE = (
    "You are a helpful assistant. You may ONLY use the anonymized document context below. "
    "It has been de-identified; do not attempt to guess or reconstruct any hidden values "
    "(tokens like <PERSON_1>). If asked for information that is not present, say so.\n\n"
    "=== ANONYMIZED CONTEXT ===\n{context}\n=== END CONTEXT ==="
)


class ChatService:
    def __init__(self, provider: ChatProvider, storage: StorageBackend, settings: Settings) -> None:
        self.provider = provider
        self.storage = storage
        self.settings = settings

    def _sanitize(self, messages: list[dict]) -> list[dict]:
        """Cap length and redact structured PII from user content before any external call."""
        cap = self.settings.chat_max_message_chars
        out = []
        for m in messages:
            content = str(m.get("content", ""))[:cap]
            out.append({"role": m.get("role", "user"), "content": redact(content)})
        return out

    def chat(self, doc: Document, user_messages: list[dict]) -> str:
        ensure_chat_allowed(doc)                       # gate 1: approved only
        assert_shareable(StorageLayer.CHAT_CONTEXT)    # gate 2: layer policy
        if not self.storage.exists(StorageLayer.CHAT_CONTEXT, doc.id, _CONTEXT_NAME):
            raise ChatNotAllowed(f"no approved chat-context artifact for document {doc.id}")
        # gate 3: read ONLY the anonymized chat-context layer.
        context = self.storage.read_bytes(StorageLayer.CHAT_CONTEXT, doc.id, _CONTEXT_NAME).decode("utf-8")
        system_prompt = _SYSTEM_TEMPLATE.format(context=context)
        return self.provider.chat(system_prompt, self._sanitize(user_messages), self.settings.chat_model)
