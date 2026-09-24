"""Chat service — the single choke point for any external LLM call (Codex CRITICAL fix).

ALL chat goes through `ChatService.preview` / `ChatService.ask`. For EVERY provider and EVERY
selected document it enforces:
  1. document status is APPROVED (`ensure_chat_allowed`);
  2. the requested data is the externally-shareable chat-context layer (`assert_shareable`);
  3. an approved chat-context artifact actually exists.
Only storage layer 5 (CHAT_CONTEXT) is ever read. User-supplied messages (the question and every
history turn) are PII-redacted, then length-capped, before leaving the machine.

Cloud providers (Claude / Codex CLI, `provider.local is False`) add a fourth gate, consent: `ask`
refuses unless the request carries the `preview_hash` that `preview` returned. The hash covers
the provider, the model, the documents and `sent_text` — the exact text `provider.chat` sends
(for a CLI: the stdin envelope, byte for byte), which includes the system prompt, the sources,
the history and the question. It is recomputed from fresh reads, so a changed document, question
or history drops the consent (plan §5.6). Every cloud send is recorded without content
(`chat/dispatches.py`) before the provider is called.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass

from app.chat import dispatches, retrieval
from app.chat.base import ChatError, ChatNotAllowed, SelectableProvider, ensure_chat_allowed
from app.chat.retrieval import Source
from app.config import Settings
from app.models.document import Document
from app.security.logging import redact
from app.storage.base import StorageBackend, StorageLayer, assert_shareable

_CONTEXT_NAME = "context.txt"
_HISTORY_MESSAGES = 8  # earlier turns sent along with a question (V2: the last 8)
_ROLES = frozenset({"user", "assistant"})


def preview_hash(provider_id: str, model: str, doc_ids: Sequence[str], sent_text: str) -> str:
    """sha256 over canonical JSON of what the user consents to: where it goes (provider and
    model), which documents, and the exact text that leaves the machine. Any change → another
    hash."""
    canonical = json.dumps(
        {"provider": provider_id, "model": model, "doc_ids": sorted(doc_ids),
         "sent_text": sent_text},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Prepared:
    doc_ids: list[str]
    sources: list[Source]
    system_prompt: str
    messages: list[dict]
    sent_text: str
    preview_hash: str


class ChatService:
    def __init__(self, storage: StorageBackend, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings

    def _sanitize(self, messages: list[dict]) -> list[dict]:
        """Redact structured PII from user content, then cap its length. Redacting first means a
        cut can never leave half of a value that the redactor would no longer recognise."""
        cap = self.settings.chat_max_message_chars
        out = []
        for m in messages:
            content = redact(str(m.get("content", "")))[:cap]
            role = m.get("role")  # a client must not smuggle in a second "system" message
            out.append({"role": role if role in _ROLES else "user", "content": content})
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

    def _prepare(
        self,
        docs: Sequence[Document],
        question: str,
        provider: SelectableProvider,
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
        # Old citation markers go BEFORE redaction: stripping them afterwards would glue a value
        # split by a marker ("ali[S1]@example.com") back together behind the redactor's back.
        earlier = self._sanitize([
            {**m, "content": retrieval.strip_citations(str(m.get("content", "")))}
            for m in list(history)[-_HISTORY_MESSAGES:]
        ])
        messages = [*earlier, {"role": "user", "content": asked}]
        system_prompt = retrieval.system_prompt(sources)
        model = getattr(provider, "model", "")
        doc_ids = [d.id for d in selected]
        sent_text = provider.render(system_prompt, messages, model)
        return _Prepared(
            doc_ids=doc_ids,
            sources=sources,
            system_prompt=system_prompt,
            messages=messages,
            sent_text=sent_text,
            preview_hash=preview_hash(provider.id, model, doc_ids, sent_text),
        )

    def preview(
        self,
        docs: Sequence[Document],
        question: str,
        provider: SelectableProvider,
        history: Sequence[dict] = (),
    ) -> dict:
        """Contract ChatPreviewResponse. No provider call; the consent dialog's exact text. The
        caller must pass the same history it will send with `ask`."""
        prepared = self._prepare(docs, question, provider, history)
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
        provider: SelectableProvider,
        *,
        preview_hash: str | None = None,
        history: Sequence[dict] = (),
    ) -> dict:
        """Contract ChatResponse. Cloud providers need the matching preview_hash (gate 4), and
        every cloud send is recorded before it happens."""
        started = time.monotonic()
        prepared = self._prepare(docs, question, provider, history)
        if not getattr(provider, "local", False):
            if not preview_hash:
                raise ChatError("preview_required")
            if not hmac.compare_digest(
                preview_hash.encode("utf-8"), prepared.preview_hash.encode("utf-8")
            ):
                raise ChatError("preview_mismatch")
            dispatches.record(
                self.settings, provider=provider.id, model=getattr(provider, "model", ""),
                doc_ids=prepared.doc_ids, preview_hash=prepared.preview_hash,
                chars=len(prepared.sent_text),
            )
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
