"""Chat service — the single choke point for any external LLM call (Codex CRITICAL fix).

ALL chat goes through `ChatService` (`chat` for the legacy single-document route; `preview` and
`ask` for the multi-provider flow). For EVERY provider and EVERY selected document it enforces:
  1. document status is APPROVED (`ensure_chat_allowed`);
  2. the requested data is the externally-shareable chat-context layer (`assert_shareable`);
  3. an approved chat-context artifact actually exists.
Only storage layer 5 (CHAT_CONTEXT) is ever read. User-supplied messages are length-capped and
PII-redacted before leaving the machine, so a user cannot smuggle raw PII into the provider call.

Cloud providers (Claude / Codex CLI, `provider.local is False`) add a fourth gate, consent: `ask`
refuses unless the request carries the `preview_hash` that `preview` returned for the same
provider, documents, question and sources — recomputed from fresh reads, so a changed document
drops the consent (plan §5.6). The preview's `sent_text` is `provider.render(...)`, i.e. exactly
the text `provider.chat` sends (for a CLI: the stdin envelope, byte for byte).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass

from app.chat import retrieval
from app.chat.base import ChatError, ChatNotAllowed, ChatProvider, ensure_chat_allowed
from app.chat.retrieval import Source
from app.config import Settings
from app.models.document import Document
from app.security.logging import redact
from app.storage.base import StorageBackend, StorageLayer, assert_shareable

_CONTEXT_NAME = "context.txt"
_HISTORY_MESSAGES = 8  # earlier turns sent along with a question (V2: the last 8)
_ROLES = frozenset({"user", "assistant"})

_SYSTEM_TEMPLATE = (
    "You are a helpful assistant. You may ONLY use the anonymized document context below. "
    "It has been de-identified; do not attempt to guess or reconstruct any hidden values "
    "(tokens like <PERSON_1>). If asked for information that is not present, say so.\n\n"
    "=== ANONYMIZED CONTEXT ===\n{context}\n=== END CONTEXT ==="
)


def preview_hash(
    provider_id: str, doc_ids: Sequence[str], question: str, sources: Sequence[Source]
) -> str:
    """sha256 over canonical JSON of what the user consents to: the destination, the documents,
    the (sanitized) question and every source exactly as sent. Any change → another hash."""
    canonical = json.dumps(
        {
            "provider": provider_id,
            "doc_ids": sorted(doc_ids),
            "question": question,
            "sources": [
                {
                    "id": s.id,
                    "doc_id": s.doc_id,
                    "unit_id": s.unit_id,
                    "label": s.label,
                    "text": s.text,
                }
                for s in sources
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Prepared:
    sources: list[Source]
    system_prompt: str
    messages: list[dict]
    sent_text: str
    preview_hash: str


class ChatService:
    def __init__(self, provider: ChatProvider, storage: StorageBackend, settings: Settings) -> None:
        self.provider = provider  # the local default; the legacy single-document route uses it
        self.storage = storage
        self.settings = settings

    def _sanitize(self, messages: list[dict]) -> list[dict]:
        """Cap length and redact structured PII from user content before any external call."""
        cap = self.settings.chat_max_message_chars
        out = []
        for m in messages:
            content = str(m.get("content", ""))[:cap]
            role = m.get("role")  # a client must not smuggle in a second "system" message
            out.append({"role": role if role in _ROLES else "user", "content": redact(content)})
        return out

    def _approved_contexts(self, docs: Sequence[Document]) -> list[tuple[Document, str]]:
        """Gates 1-3 for every document, then read ONLY the anonymized chat-context layer."""
        for doc in docs:
            ensure_chat_allowed(doc)                   # gate 1: approved only
        assert_shareable(StorageLayer.CHAT_CONTEXT)    # gate 2: layer policy
        contexts = []
        for doc in docs:
            if not self.storage.exists(StorageLayer.CHAT_CONTEXT, doc.id, _CONTEXT_NAME):
                raise ChatNotAllowed(f"no approved chat-context artifact for document {doc.id}")
            raw = self.storage.read_bytes(StorageLayer.CHAT_CONTEXT, doc.id, _CONTEXT_NAME)
            contexts.append((doc, raw.decode("utf-8")))
        return contexts

    def chat(self, doc: Document, user_messages: list[dict]) -> str:
        """Legacy single-document chat (old UI): the whole approved context, local provider."""
        [(_, context)] = self._approved_contexts([doc])
        system_prompt = _SYSTEM_TEMPLATE.format(context=context)
        return self.provider.chat(
            system_prompt, self._sanitize(user_messages), self.settings.chat_ollama_model
        )

    # ------------------------------------------------ multi-provider flow (contract "chat")

    def _prepare(
        self,
        docs: Sequence[Document],
        question: str,
        provider,
        history: Sequence[dict] = (),
    ) -> _Prepared:
        # Sorted, de-duplicated ids: numbering, prompt and hash never depend on request order.
        selected = sorted({d.id: d for d in docs}.values(), key=lambda d: d.id)
        if not selected:
            raise ChatNotAllowed("no document selected")
        contexts = self._approved_contexts(selected)
        asked = self._sanitize([{"role": "user", "content": question}])[0]["content"]
        sources = retrieval.retrieve(
            [(doc.id, doc.filename, text) for doc, text in contexts], asked
        )
        if not sources:
            raise ChatNotAllowed("the approved chat context is empty")
        earlier = [
            {**m, "content": retrieval.strip_citations(m["content"])}
            for m in self._sanitize(list(history)[-_HISTORY_MESSAGES:])
        ]
        messages = [*earlier, {"role": "user", "content": asked}]
        system_prompt = retrieval.system_prompt(sources)
        model = getattr(provider, "model", "")
        return _Prepared(
            sources=sources,
            system_prompt=system_prompt,
            messages=messages,
            sent_text=provider.render(system_prompt, messages, model),
            preview_hash=preview_hash(provider.id, [d.id for d in selected], asked, sources),
        )

    def preview(self, docs: Sequence[Document], question: str, provider) -> dict:
        """Contract ChatPreviewResponse. No provider call; the consent dialog's exact text."""
        prepared = self._prepare(docs, question, provider)
        return {
            "provider": provider.id,
            "preview_hash": prepared.preview_hash,
            "destination": provider.destination,
            "sources": [s.public() for s in prepared.sources],
            "sent_text": prepared.sent_text,
            "context_chars": sum(len(s.text) for s in prepared.sources),
        }

    def ask(
        self,
        docs: Sequence[Document],
        question: str,
        provider,
        *,
        preview_hash: str | None = None,
        history: Sequence[dict] = (),
    ) -> dict:
        """Contract ChatResponse. Cloud providers need the matching preview_hash (gate 4)."""
        started = time.monotonic()
        prepared = self._prepare(docs, question, provider, history)
        if not getattr(provider, "local", False):
            if not preview_hash:
                raise ChatError("preview_required")
            if not hmac.compare_digest(
                preview_hash.encode("utf-8"), prepared.preview_hash.encode("utf-8")
            ):
                raise ChatError("preview_mismatch")
        raw = provider.chat(
            prepared.system_prompt, prepared.messages, getattr(provider, "model", "")
        )
        answer = retrieval.normalize_citations(str(raw or "").strip())
        cited = retrieval.cited_sources(answer, prepared.sources)
        return {
            "answer": answer,
            "citations": [s.public() for s in cited],
            "provider": provider.id,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
